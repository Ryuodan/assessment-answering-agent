"""Who is using the system, which team's work they see, and who may say so.

Signing in takes two things: an address that has been added to the system, and
the **access code** shared by that person's team. The address says who you are
and the code proves you were told it — neither alone is enough, which is what
separates this from the earlier allow-list-only version, where knowing a
colleague's address was sufficient.

Access is administered **from inside the application**, not from `.env`.
Whoever operates the host may not be whoever decides who uses the system, and
an allow-list in a config file can only be changed by the former. So a `users`
row is the allow-list; `ALLOWED_EMAILS` merely seeds it on a first run, and
everything after that happens on the admin page.

`ADMIN_EMAIL` / `ADMIN_PASSWORD` are the exception, and deliberately so: they
are the break-glass account, re-applied at every startup. That is the one thing
the operator sets, and the way back in if every other credential is lost.

This is still not a strong authentication system — there is no email
verification, and a team's code is shared by everyone on it, so it identifies a
group and attributes to a name rather than proving an individual. It is a good
door lock. It is not a safe.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from functools import lru_cache
from datetime import datetime, timedelta, timezone

from src import credentials, store
from src.config import settings

logger = logging.getLogger(__name__)

SESSION_COOKIE = "session"
LOCAL_EMAIL = "local@localhost"

MEMBER = "member"
ADMIN = "admin"
ROLES = (MEMBER, ADMIN)


class AccessDenied(Exception):
    """Sign-in was refused. The message is safe to show the person."""


class NotAllowed(Exception):
    """An administrative action the caller may not perform."""


@dataclass(frozen=True)
class User:
    """A signed-in person: their own work, and the team they share a corpus with."""

    email: str
    team_id: str
    role: str = MEMBER

    @property
    def is_admin(self) -> bool:
        return self.role == ADMIN


def normalise(email: str) -> str:
    """Lower-case and strip. Addresses are not case-sensitive; storage is."""
    return email.strip().casefold()


@lru_cache(maxsize=1)
def _decoy_hash() -> str:
    """A real hash of nothing in particular, to spend time against.

    Cached rather than computed per attempt: the point is to match the cost of
    a verification, not to add a second one. Derived from a random secret so it
    can never accidentally match anything a person could type.
    """
    return credentials.hash_secret(secrets.token_urlsafe(16))


def _hash_token(token: str) -> str:
    """What gets stored for a session. The token itself never touches the database.

    SHA-256 rather than scrypt, unlike the secrets in `credentials`: this is 256
    random bits with nothing to guess, so there is no offline attack for a slow
    hash to frustrate, and sessions are verified on every single request.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------


def ensure_team(team_id: str, *, name: str = "") -> str:
    """Create the team if it is new. Returns the id, for chaining."""
    conn = store.connect()
    conn.execute(
        "INSERT INTO teams (id, created_at, name) VALUES (?, ?, ?) ON CONFLICT(id) DO NOTHING",
        (team_id, store.utcnow(), name or team_id),
    )
    conn.commit()
    return team_id


def set_access_code(team_id: str, code: str | None = None) -> str:
    """Set or rotate a team's access code. Returns the plaintext, once.

    The caller is the only place the code exists in readable form — after this
    returns, only the hash is kept, so a code that is not written down is gone.
    That is the intended behaviour: it is what makes a stolen database useless
    for signing in.
    """
    code = code or credentials.generate_code()
    conn = store.connect()
    conn.execute(
        "UPDATE teams SET access_code_hash = ?, code_set_at = ? WHERE id = ?",
        (credentials.hash_secret(credentials.normalise_code(code)), store.utcnow(), team_id),
    )
    conn.commit()
    return code


def team_has_code(team_id: str) -> bool:
    conn = store.connect()
    row = conn.execute("SELECT access_code_hash FROM teams WHERE id = ?", (team_id,)).fetchone()
    return bool(row and row["access_code_hash"])


def list_teams() -> list[dict]:
    """Every team, with member counts. For the admin page."""
    conn = store.connect()
    rows = conn.execute(
        """
        SELECT t.id, t.name, t.created_at, t.code_set_at,
               t.access_code_hash != '' AS has_code,
               COUNT(u.email) AS members
        FROM teams t
        LEFT JOIN users u ON u.team_id = t.id
        GROUP BY t.id
        ORDER BY t.created_at
        """
    ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"] or row["id"],
            "created_at": row["created_at"],
            "code_set_at": row["code_set_at"],
            "has_code": bool(row["has_code"]),
            "members": row["members"],
        }
        for row in rows
    ]


def delete_team(team_id: str) -> None:
    """Remove an empty team.

    Refuses while anyone is still on it rather than cascading: the members would
    lose their history along with their access, and nothing about clicking
    'delete team' says that should happen.
    """
    conn = store.connect()
    members = conn.execute("SELECT COUNT(*) FROM users WHERE team_id = ?", (team_id,)).fetchone()[0]
    if members:
        raise NotAllowed(f"{team_id} still has {members} member(s). Move or remove them first.")
    conn.execute("DELETE FROM teams WHERE id = ?", (team_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def _row_to_user(row) -> User:
    return User(email=row["email"], team_id=row["team_id"], role=row["role"])


def find_user(email: str) -> User | None:
    """An enabled user, or None. Disabled and unknown are the same answer."""
    conn = store.connect()
    row = conn.execute(
        "SELECT email, team_id, role FROM users WHERE email = ? AND disabled = 0",
        (normalise(email),),
    ).fetchone()
    return _row_to_user(row) if row else None


def is_allowed(email: str) -> bool:
    """Whether this address is known to the system and not disabled."""
    return find_user(email) is not None


def add_user(
    email: str,
    *,
    team_id: str | None = None,
    role: str = MEMBER,
    password: str | None = None,
    added_by: str = "",
) -> User:
    """Add someone, or update the team and role of someone already here."""
    address = normalise(email)
    if "@" not in address or address.startswith("@") or address.endswith("@"):
        raise NotAllowed(f"{email!r} is not an email address.")
    if role not in ROLES:
        raise NotAllowed(f"Unknown role {role!r}.")

    team = ensure_team(team_id or settings.default_team)
    now = store.utcnow()
    conn = store.connect()
    conn.execute(
        """
        INSERT INTO users (email, team_id, created_at, last_seen_at, role, added_by)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(email) DO UPDATE SET
            team_id = excluded.team_id,
            role    = excluded.role,
            disabled = 0
        """,
        (address, team, now, now, role, added_by),
    )
    if password:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE email = ?",
            (credentials.hash_secret(password), address),
        )
    conn.commit()
    return User(email=address, team_id=team, role=role)


def update_user(
    email: str,
    *,
    team_id: str | None = None,
    role: str | None = None,
    disabled: bool | None = None,
) -> User:
    """Change a user's team, role, or whether they may sign in."""
    address = normalise(email)
    if find_user_any(address) is None:
        raise NotAllowed(f"No user {address}.")
    if role is not None and role not in ROLES:
        raise NotAllowed(f"Unknown role {role!r}.")

    conn = store.connect()
    if team_id is not None:
        conn.execute("UPDATE users SET team_id = ? WHERE email = ?", (ensure_team(team_id), address))
    if role is not None:
        conn.execute("UPDATE users SET role = ? WHERE email = ?", (role, address))
    if disabled is not None:
        conn.execute("UPDATE users SET disabled = ? WHERE email = ?", (int(disabled), address))
        if disabled:
            # Access ends now, not when the session happens to expire.
            conn.execute("DELETE FROM sessions WHERE email = ?", (address,))
    conn.commit()
    return find_user_any(address)


def set_password(email: str, password: str | None) -> None:
    """Give someone a password, or take it away.

    A password is what lets an admin sign in without their team's code, so it
    is the difference between an administrator and a member who is merely
    marked as one. Clearing it drops them back to the shared code.
    """
    address = normalise(email)
    conn = store.connect()
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE email = ?",
        (credentials.hash_secret(password) if password else "", address),
    )
    conn.commit()


def remove_user(email: str) -> None:
    """Delete a user and end their sessions.

    Their runs and events stay: the history records what happened, and someone
    leaving does not unmake the answers they wrote.
    """
    address = normalise(email)
    conn = store.connect()
    conn.execute("DELETE FROM sessions WHERE email = ?", (address,))
    conn.execute("DELETE FROM users WHERE email = ?", (address,))
    conn.commit()


def find_user_any(email: str) -> User | None:
    """Like `find_user`, but finds disabled accounts too. For administration."""
    conn = store.connect()
    row = conn.execute("SELECT email, team_id, role FROM users WHERE email = ?", (normalise(email),)).fetchone()
    return _row_to_user(row) if row else None


def list_users(team_id: str | None = None) -> list[dict]:
    """Everyone, for the admin page. Never includes a hash."""
    conn = store.connect()
    # Not the local stand-in: it is nobody, and it cannot be signed in to.
    sql = (
        "SELECT email, team_id, role, disabled, created_at, last_seen_at, added_by, "
        "password_hash != '' AS has_password FROM users WHERE email != ?"
    )
    params: list[object] = [LOCAL_EMAIL]
    if team_id:
        sql += " AND team_id = ?"
        params.append(team_id)
    rows = conn.execute(sql + " ORDER BY created_at", params).fetchall()
    return [
        {
            "email": row["email"],
            "team": row["team_id"],
            "role": row["role"],
            "disabled": bool(row["disabled"]),
            "created_at": row["created_at"],
            "last_seen_at": row["last_seen_at"],
            "added_by": row["added_by"],
            "has_password": bool(row["has_password"]),
        }
        for row in rows
    ]


def admin_count() -> int:
    """Enabled admins. Used to refuse removing the last one.

    The local stand-in is an administrator on paper and nobody in fact. Counted,
    it let the one real administrator demote or remove themselves.
    """
    conn = store.connect()
    return conn.execute(
        "SELECT COUNT(*) FROM users WHERE role = ? AND disabled = 0 AND email != ?",
        (ADMIN, LOCAL_EMAIL),
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# Throttling
# ---------------------------------------------------------------------------


def _record_attempt(email: str, succeeded: bool) -> None:
    conn = store.connect()
    conn.execute(
        "INSERT INTO sign_in_attempts (email, created_at, succeeded) VALUES (?, ?, ?)",
        (email, store.utcnow(), int(succeeded)),
    )
    if succeeded:
        # A correct sign-in clears the slate, so an earlier typo cannot lock
        # someone out an hour later.
        conn.execute("DELETE FROM sign_in_attempts WHERE email = ? AND succeeded = 0", (email,))
    conn.commit()


def _locked_out(email: str) -> bool:
    """Whether this address has failed too many times too recently.

    Per address rather than per IP: the thing being guessed is a code shared by
    a whole team, and an attacker who knows one address can otherwise spread
    guesses across a proxy pool. Rate-limiting what is actually scarce — the
    number of tries against one account — is what makes a typeable code safe.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=settings.sign_in_lockout_minutes)).isoformat(
        timespec="seconds"
    )
    conn = store.connect()
    failures = conn.execute(
        "SELECT COUNT(*) FROM sign_in_attempts WHERE email = ? AND succeeded = 0 AND created_at > ?",
        (email, cutoff),
    ).fetchone()[0]
    return failures >= settings.sign_in_max_attempts


def purge_old_attempts() -> int:
    """Drop attempt rows older than the lockout window. Housekeeping."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=settings.sign_in_lockout_minutes)).isoformat(
        timespec="seconds"
    )
    conn = store.connect()
    cursor = conn.execute("DELETE FROM sign_in_attempts WHERE created_at <= ?", (cutoff,))
    conn.commit()
    return cursor.rowcount


# ---------------------------------------------------------------------------
# Signing in
# ---------------------------------------------------------------------------


def sign_in(email: str, secret: str) -> tuple[str, User]:
    """Verify an address and its secret, and open a session.

    The secret is the person's own password when they have one, and otherwise
    their team's shared access code. One field, because from the person's side
    there is only ever one thing to type — and an admin whose password did not
    work should not be told that a team code would have.
    """
    address = normalise(email)
    if not address:
        raise AccessDenied("Enter your email address.")
    if not secret:
        raise AccessDenied("Enter your access code.")

    if _locked_out(address):
        raise AccessDenied(f"Too many attempts. Wait {settings.sign_in_lockout_minutes} minutes and try again.")

    conn = store.connect()
    row = conn.execute(
        "SELECT email, team_id, role, password_hash, disabled FROM users WHERE email = ?",
        (address,),
    ).fetchone()

    # One message for every failure. Which addresses exist, which are disabled
    # and which have passwords are all things an attacker would like to learn
    # from a login form, and none of them help the person who simply mistyped.
    refusal = AccessDenied("That email and access code do not match.")

    # The local stand-in is refused like an unknown address. It is created as an
    # administrator with no password the first time the app is opened before
    # anybody is added, and a row with no password signs in with the team's
    # code -- so, left open, everyone who knew the code could become an
    # administrator by typing `local@localhost`.
    if row is None or row["disabled"] or address == LOCAL_EMAIL:
        # Verify against a decoy so an unknown address costs what a known one
        # does. Without this the identical message is undone by the clock:
        # measured, a known address took 50 ms to refuse and an unknown one
        # 2.7 ms, because only the known one reached the hash. Nineteen times is
        # not a subtle signal -- it is a working way to enumerate the allow-list
        # from outside.
        credentials.verify_secret(secret, _decoy_hash())
        _record_attempt(address, False)
        raise refusal

    if row["password_hash"]:
        ok = credentials.verify_secret(secret, row["password_hash"])
    else:
        team = conn.execute("SELECT access_code_hash FROM teams WHERE id = ?", (row["team_id"],)).fetchone()
        ok = bool(team) and credentials.verify_secret(credentials.normalise_code(secret), team["access_code_hash"])

    if not ok:
        _record_attempt(address, False)
        raise refusal

    _record_attempt(address, True)
    now = store.utcnow()
    conn.execute("UPDATE users SET last_seen_at = ? WHERE email = ?", (now, address))

    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=settings.session_ttl_days)
    conn.execute(
        "INSERT INTO sessions (token_hash, email, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (_hash_token(token), address, now, expires.isoformat(timespec="seconds")),
    )
    conn.commit()
    return token, _row_to_user(row)


def resolve(token: str | None) -> User | None:
    """The user behind a session token, or None if there isn't one.

    Returns None rather than raising for every ordinary reason a token fails —
    absent, unknown, expired, since-removed — because all of them mean the same
    thing to a caller: show the sign-in screen. A user disabled or deleted since
    the session opened stops working on their next request.
    """
    if not token:
        return None
    conn = store.connect()
    row = conn.execute(
        "SELECT s.expires_at, u.email, u.team_id, u.role, u.disabled "
        "FROM sessions s JOIN users u ON u.email = s.email WHERE s.token_hash = ?",
        (_hash_token(token),),
    ).fetchone()
    if row is None or row["disabled"] or row["expires_at"] <= store.utcnow():
        return None
    if row["email"] == LOCAL_EMAIL:
        return None  # never a session of its own; see `sign_in`
    return _row_to_user(row)


def sign_out(token: str | None) -> None:
    """End one session. Silent when the token is already gone."""
    if not token:
        return
    conn = store.connect()
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash_token(token),))
    conn.commit()


def purge_expired_sessions() -> int:
    """Delete sessions past their expiry. Returns how many went."""
    conn = store.connect()
    cursor = conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (store.utcnow(),))
    conn.commit()
    return cursor.rowcount


def team_members(team_id: str) -> list[str]:
    """Addresses on one team, oldest first."""
    conn = store.connect()
    rows = conn.execute("SELECT email FROM users WHERE team_id = ? ORDER BY created_at", (team_id,)).fetchall()
    return [row["email"] for row in rows]


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------


def sign_in_required() -> bool:
    """Whether this deployment gates access.

    True as soon as anybody has been added, which is the honest signal: an
    empty system has nobody to sign in as, and demanding credentials from the
    one person running it locally would be ceremony. Adding the first user is
    what closes the door.
    """
    conn = store.connect()
    return conn.execute("SELECT COUNT(*) FROM users WHERE email != ?", (LOCAL_EMAIL,)).fetchone()[0] > 0


def local_user() -> User:
    """The stand-in identity used before anyone has been added.

    The row is created for real, so events and runs recorded in local
    development have a valid author and behave exactly as they will in a
    deployment — the code path is the same, only the name differs.

    Only while nobody has been added. On a deployment it is no one: a script
    run against the real database -- the assistant evaluation -- used to plant
    it there as an administrator, and 140 of its test conversations went into
    the team's history under it. There it is a member that exists in no table.
    """
    team = ensure_team(settings.default_team)
    if sign_in_required():
        return User(email=LOCAL_EMAIL, team_id=team, role=MEMBER)
    now = store.utcnow()
    conn = store.connect()
    conn.execute(
        """
        INSERT INTO users (email, team_id, created_at, last_seen_at, role) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(email) DO UPDATE SET last_seen_at = excluded.last_seen_at
        """,
        (LOCAL_EMAIL, team, now, now, ADMIN),
    )
    conn.commit()
    # Read the row back rather than assuming the default: an administrator can
    # move this account to another team, and reporting the team it was created
    # in would show it another team's work.
    row = conn.execute("SELECT team_id, role FROM users WHERE email = ?", (LOCAL_EMAIL,)).fetchone()
    return User(email=LOCAL_EMAIL, team_id=row["team_id"], role=row["role"])


def bootstrap() -> None:
    """Apply the environment's account settings. Runs at every startup.

    `ADMIN_EMAIL` / `ADMIN_PASSWORD` are re-applied every time by design. They
    are the break-glass account: the operator sets them once, and they are the
    way back in when a password is forgotten or the last admin is removed by
    accident. Because the environment always wins for this one account, its
    password cannot usefully be changed from the admin page — create a second
    admin for day-to-day use, which the page exists to let you do.

    `ALLOWED_EMAILS` seeds members on a first run only, so the list that was in
    `.env` before this existed still works, and removing someone on the admin
    page is not undone by the next restart.
    """
    ensure_team(settings.default_team)

    if settings.admin_email and settings.admin_password:
        add_user(
            settings.admin_email,
            team_id=settings.default_team,
            role=ADMIN,
            password=settings.admin_password,
            added_by="environment",
        )
        logger.info("Break-glass admin %s applied from the environment.", normalise(settings.admin_email))
    elif settings.admin_email:
        logger.warning("ADMIN_EMAIL is set but ADMIN_PASSWORD is empty; no admin was created.")

    seeds = settings.allowed_emails_set
    if seeds and not _seeded_before():
        for address in sorted(seeds):
            add_user(address, team_id=settings.default_team, added_by="environment")
        logger.info("Seeded %d member(s) from ALLOWED_EMAILS.", len(seeds))

    if sign_in_required():
        _remove_the_stand_in()

    if sign_in_required() and not team_has_code(settings.default_team):
        code = set_access_code(settings.default_team)
        logger.warning(
            "No access code was set for team %r, so one was generated: %s\n"
            "        Give it to the team, or replace it on the admin page.",
            settings.default_team,
            code,
        )


def _remove_the_stand_in() -> None:
    """Take the local stand-in out of a deployment where people sign in.

    Its conversations and events stay with the team: whatever was done under
    it happened, and the record is not unmade by removing the name.
    """
    conn = store.connect()
    conn.execute("DELETE FROM sessions WHERE email = ?", (LOCAL_EMAIL,))
    removed = conn.execute("DELETE FROM users WHERE email = ?", (LOCAL_EMAIL,)).rowcount
    conn.commit()
    if removed:
        logger.info("Removed the local stand-in account; people sign in here.")


def _seeded_before() -> bool:
    """Whether ALLOWED_EMAILS has already been applied.

    Seeding once rather than every start is what makes the admin page
    authoritative: someone removed there must stay removed, and a list left
    behind in `.env` should not quietly restore them on the next restart.
    """
    conn = store.connect()
    return (
        conn.execute("SELECT COUNT(*) FROM users WHERE added_by = 'environment' AND role = ?", (MEMBER,)).fetchone()[0]
        > 0
    )
