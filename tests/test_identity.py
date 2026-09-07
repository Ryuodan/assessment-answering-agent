"""Access: who is known, what they must type, and who may change that.

Two secrets meet here — a team's shared access code and an administrator's own
password — and the failure modes matter more than the happy path. A sign-in
form should not leak which addresses exist, a removed person should lose access
at once rather than when their session expires, and no administrator should be
able to lock everyone out by accident.
"""

from __future__ import annotations

import pytest

from src import credentials, identity, store
from src.config import settings

ALICE = "m.alsaif@t2.sa"
BOB = "mohammed.sa.alsaif@gmail.com"
CODE = "TEAM-CODE-FOR-TESTS"


@pytest.fixture
def team():
    """A team with a known access code, and one member on it."""
    identity.ensure_team(settings.default_team, name="Cybersecurity")
    identity.set_access_code(settings.default_team, CODE)
    identity.add_user(ALICE, team_id=settings.default_team)
    return settings.default_team


# --- the allow-list lives in the database ----------------------------------


def test_an_empty_system_has_nobody_and_needs_no_sign_in():
    assert not identity.sign_in_required()
    assert not identity.is_allowed(ALICE)


def test_adding_the_first_user_closes_the_door(team):
    assert identity.sign_in_required()
    assert identity.is_allowed(ALICE)
    assert not identity.is_allowed(BOB)


def test_the_local_user_does_not_count_as_gating():
    """Otherwise a laptop that once ran the app would start demanding a code."""
    identity.local_user()
    assert not identity.sign_in_required()


@pytest.mark.parametrize("given", [ALICE, "M.Alsaif@T2.sa", f"  {ALICE}  ", "M.ALSAIF@T2.SA"])
def test_addresses_match_regardless_of_case_or_padding(team, given):
    _, user = identity.sign_in(given, CODE)
    assert user.email == ALICE


def test_an_address_that_is_not_a_address_is_refused():
    with pytest.raises(identity.NotAllowed, match="not an email address"):
        identity.add_user("not-an-address")


def test_an_unknown_role_is_refused():
    with pytest.raises(identity.NotAllowed, match="Unknown role"):
        identity.add_user(ALICE, role="superuser")


# --- the access code -------------------------------------------------------


def test_signing_in_needs_the_code(team):
    with pytest.raises(identity.AccessDenied, match="do not match"):
        identity.sign_in(ALICE, "wrong-code")


def test_a_blank_code_is_refused(team):
    with pytest.raises(identity.AccessDenied, match="access code"):
        identity.sign_in(ALICE, "")


@pytest.mark.parametrize(
    "typed",
    ["TEAMCODEFORTESTS", "team-code-for-tests", "TEAM CODE FOR TESTS", " TEAM-CODE-FOR-TESTS "],
)
def test_the_code_survives_how_a_person_types_it(team, typed):
    """Case, spaces and dashes vary between reading aloud and pasting."""
    _, user = identity.sign_in(ALICE, typed)
    assert user.email == ALICE


def test_the_code_is_never_stored_in_the_clear(team):
    stored = store.connect().execute("SELECT access_code_hash FROM teams").fetchone()[0]
    assert CODE not in stored
    assert stored.startswith("scrypt$")


def test_rotating_the_code_breaks_the_old_one(team):
    fresh = identity.set_access_code(team)
    with pytest.raises(identity.AccessDenied):
        identity.sign_in(ALICE, CODE)
    assert identity.sign_in(ALICE, fresh)[1].email == ALICE


def test_a_generated_code_is_typeable():
    code = credentials.generate_code()
    assert len(code) == 19 and code.count("-") == 3
    assert not set(code) & set("ILOU01"), "characters that get misread are not in the alphabet"


def test_a_team_with_no_code_cannot_be_signed_in_to():
    identity.ensure_team("newteam")
    identity.add_user(BOB, team_id="newteam")
    with pytest.raises(identity.AccessDenied):
        identity.sign_in(BOB, "anything")


# --- what the form gives away ----------------------------------------------


@pytest.mark.parametrize(
    "email, secret",
    [
        ("nobody@example.com", CODE),   # unknown address, right code
        (ALICE, "wrong"),               # known address, wrong code
        ("nobody@example.com", "wrong"),
    ],
)
def test_every_failure_reads_the_same(team, email, secret):
    """Which addresses exist is not something a login form should teach."""
    with pytest.raises(identity.AccessDenied) as refused:
        identity.sign_in(email, secret)
    assert str(refused.value) == "That email and access code do not match."


def test_an_unknown_address_costs_the_same_as_a_known_one(team, monkeypatch):
    """Saying the same thing is not enough if the clock says something else.

    Measured before this was fixed: refusing a known address took 50 ms because
    it reached the hash, and an unknown one 2.7 ms because it did not. Nineteen
    times is a working way to enumerate the allow-list from outside, whatever
    the message says.

    The suite hashes far more cheaply than production, so this compares the
    number of verifications rather than wall-clock time -- timing a 0.2 ms
    operation on a busy machine would be a flaky test, and the count is the
    thing that actually has to match.
    """
    import statistics

    from src import credentials

    calls: list[str] = []
    real = credentials.verify_secret
    monkeypatch.setattr(
        credentials, "verify_secret",
        lambda secret, stored: calls.append(stored) or real(secret, stored),
    )
    monkeypatch.setattr(settings, "sign_in_max_attempts", 1000)

    for address in (ALICE, "nobody@example.com"):
        before = len(calls)
        with pytest.raises(identity.AccessDenied):
            identity.sign_in(address, "wrong")
        assert len(calls) - before == 1, f"{address} took a different number of hashes"

    assert statistics.mean(1 for _ in calls) == 1


def test_the_decoy_is_a_real_hash_that_matches_nothing(team):
    from src import credentials

    decoy = identity._decoy_hash()
    assert decoy.startswith("scrypt$")
    assert not credentials.verify_secret("", decoy)
    assert not credentials.verify_secret(CODE, decoy)
    assert identity._decoy_hash() is decoy, "computed once, not per attempt"


def test_a_suspended_user_is_refused_like_an_unknown_one(team):
    identity.update_user(ALICE, disabled=True)
    with pytest.raises(identity.AccessDenied, match="do not match"):
        identity.sign_in(ALICE, CODE)


# --- passwords, and administrators -----------------------------------------


def test_an_admin_with_a_password_uses_it_instead_of_the_team_code(team):
    identity.add_user(BOB, role=identity.ADMIN, password="a-long-admin-password")
    _, user = identity.sign_in(BOB, "a-long-admin-password")
    assert user.is_admin

    with pytest.raises(identity.AccessDenied):
        identity.sign_in(BOB, CODE), "a password holder must not fall back to the shared code"


def test_clearing_a_password_returns_someone_to_the_team_code(team):
    identity.add_user(BOB, role=identity.ADMIN, password="a-long-admin-password")
    identity.set_password(BOB, None)
    assert identity.sign_in(BOB, CODE)[1].email == BOB


def test_a_password_is_hashed_with_a_slow_kdf(team):
    identity.add_user(BOB, password="a-long-admin-password")
    stored = store.connect().execute(
        "SELECT password_hash FROM users WHERE email = ?", (BOB,)
    ).fetchone()[0]
    assert stored.startswith("scrypt$")
    assert "a-long-admin-password" not in stored


def test_role_defaults_to_member(team):
    assert not identity.find_user(ALICE).is_admin


def test_admin_count_ignores_suspended_admins(team):
    identity.add_user(BOB, role=identity.ADMIN)
    assert identity.admin_count() == 1
    identity.update_user(BOB, disabled=True)
    assert identity.admin_count() == 0


# --- throttling ------------------------------------------------------------


def test_too_many_wrong_codes_locks_the_address(team, monkeypatch):
    monkeypatch.setattr(settings, "sign_in_max_attempts", 3)
    for _ in range(3):
        with pytest.raises(identity.AccessDenied, match="do not match"):
            identity.sign_in(ALICE, "wrong")

    with pytest.raises(identity.AccessDenied, match="Too many attempts"):
        identity.sign_in(ALICE, CODE), "even the correct code waits out the lockout"


def test_a_lockout_does_not_spread_to_other_people(team, monkeypatch):
    monkeypatch.setattr(settings, "sign_in_max_attempts", 2)
    identity.add_user(BOB)
    for _ in range(2):
        with pytest.raises(identity.AccessDenied):
            identity.sign_in(ALICE, "wrong")
    assert identity.sign_in(BOB, CODE)[1].email == BOB


def test_a_correct_sign_in_clears_earlier_failures(team, monkeypatch):
    """A typo an hour ago must not lock someone out later."""
    monkeypatch.setattr(settings, "sign_in_max_attempts", 3)
    for _ in range(2):
        with pytest.raises(identity.AccessDenied):
            identity.sign_in(ALICE, "wrong")
    identity.sign_in(ALICE, CODE)

    for _ in range(2):
        with pytest.raises(identity.AccessDenied, match="do not match"):
            identity.sign_in(ALICE, "wrong")


def test_old_attempts_are_purged(team):
    with pytest.raises(identity.AccessDenied):
        identity.sign_in(ALICE, "wrong")
    conn = store.connect()
    conn.execute("UPDATE sign_in_attempts SET created_at = '2000-01-01T00:00:00+00:00'")
    conn.commit()
    assert identity.purge_old_attempts() == 1


# --- sessions --------------------------------------------------------------


def test_sign_in_then_resolve_returns_the_same_person(team):
    token, user = identity.sign_in(ALICE, CODE)
    assert identity.resolve(token) == user


def test_the_raw_token_is_never_stored(team):
    token, _ = identity.sign_in(ALICE, CODE)
    stored = store.connect().execute("SELECT token_hash FROM sessions").fetchone()[0]
    assert token not in stored and len(stored) == 64


@pytest.mark.parametrize("token", [None, "", "not-a-real-token"])
def test_a_bad_token_resolves_to_nobody(team, token):
    assert identity.resolve(token) is None


def test_two_sign_ins_produce_independent_sessions(team):
    first, _ = identity.sign_in(ALICE, CODE)
    second, _ = identity.sign_in(ALICE, CODE)
    identity.sign_out(first)
    assert identity.resolve(first) is None
    assert identity.resolve(second) is not None


def test_an_expired_session_stops_resolving(team):
    token, _ = identity.sign_in(ALICE, CODE)
    conn = store.connect()
    conn.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00+00:00'")
    conn.commit()
    assert identity.resolve(token) is None


def test_suspending_someone_ends_their_sessions_at_once(team):
    token, _ = identity.sign_in(ALICE, CODE)
    identity.update_user(ALICE, disabled=True)
    assert identity.resolve(token) is None


def test_removing_someone_ends_their_sessions_at_once(team):
    token, _ = identity.sign_in(ALICE, CODE)
    identity.remove_user(ALICE)
    assert identity.resolve(token) is None


def test_a_promotion_reaches_a_live_session(team):
    """The role is read per request, not frozen into the session."""
    token, user = identity.sign_in(ALICE, CODE)
    assert not user.is_admin
    identity.update_user(ALICE, role=identity.ADMIN)
    assert identity.resolve(token).is_admin


def test_purge_removes_only_expired_sessions(team):
    identity.add_user(BOB)
    live, _ = identity.sign_in(ALICE, CODE)
    stale, _ = identity.sign_in(BOB, CODE)
    conn = store.connect()
    conn.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00+00:00' WHERE email = ?", (BOB,))
    conn.commit()

    assert identity.purge_expired_sessions() == 1
    assert identity.resolve(live) is not None
    assert identity.resolve(stale) is None


# --- teams -----------------------------------------------------------------


def test_moving_someone_changes_which_history_they_see(team):
    identity.ensure_team("privacy")
    identity.update_user(ALICE, team_id="privacy")
    assert identity.find_user(ALICE).team_id == "privacy"


def test_a_team_with_members_cannot_be_deleted(team):
    with pytest.raises(identity.NotAllowed, match="still has 1 member"):
        identity.delete_team(team)


def test_an_empty_team_can_be_deleted():
    identity.ensure_team("spare")
    identity.delete_team("spare")
    assert not any(t["id"] == "spare" for t in identity.list_teams())


def test_list_teams_reports_membership_and_whether_a_code_is_set(team):
    [listed] = [t for t in identity.list_teams() if t["id"] == team]
    assert listed["members"] == 1 and listed["has_code"] is True
    assert listed["name"] == "Cybersecurity"


def test_list_users_never_returns_a_hash(team):
    identity.add_user(BOB, password="a-long-admin-password")
    for user in identity.list_users():
        assert "password_hash" not in user and "hash" not in str(user).lower()
    assert [u["has_password"] for u in identity.list_users() if u["email"] == BOB] == [True]


def test_removing_a_user_keeps_their_history(team):
    """Someone leaving does not unmake the answers they wrote."""
    from src import events

    events.record(identity.find_user(ALICE), events.SIGNED_IN)
    identity.remove_user(ALICE)
    assert len(events.recent(team)) == 1


# --- bootstrap -------------------------------------------------------------


def test_bootstrap_creates_the_break_glass_admin(monkeypatch):
    monkeypatch.setattr(settings, "admin_email", "Boss@T2.sa")
    monkeypatch.setattr(settings, "admin_password", "a-long-admin-password")
    identity.bootstrap()

    admin = identity.find_user("boss@t2.sa")
    assert admin is not None and admin.is_admin
    assert identity.sign_in("boss@t2.sa", "a-long-admin-password")[1].is_admin


def test_bootstrap_reapplies_the_break_glass_password(monkeypatch):
    """The way back in after a forgotten password: reset it and restart."""
    monkeypatch.setattr(settings, "admin_email", "boss@t2.sa")
    monkeypatch.setattr(settings, "admin_password", "first-password-here")
    identity.bootstrap()
    monkeypatch.setattr(settings, "admin_password", "second-password-here")
    identity.bootstrap()

    assert identity.sign_in("boss@t2.sa", "second-password-here")[1].is_admin


def test_an_admin_email_without_a_password_creates_nobody(monkeypatch, caplog):
    monkeypatch.setattr(settings, "admin_email", "boss@t2.sa")
    monkeypatch.setattr(settings, "admin_password", "")
    identity.bootstrap()
    assert identity.find_user("boss@t2.sa") is None
    assert "ADMIN_PASSWORD is empty" in caplog.text


def test_allowed_emails_seeds_members_once(monkeypatch):
    monkeypatch.setattr(settings, "allowed_emails", f"{ALICE},{BOB}")
    identity.bootstrap()
    assert {u["email"] for u in identity.list_users()} == {ALICE, BOB}

    # Someone removed on the admin page must stay removed across a restart,
    # or the file in .env quietly overrules the person administering the system.
    identity.remove_user(BOB)
    identity.bootstrap()
    assert {u["email"] for u in identity.list_users()} == {ALICE}


def test_bootstrap_generates_a_code_when_gating_begins(monkeypatch, caplog):
    monkeypatch.setattr(settings, "allowed_emails", ALICE)
    identity.bootstrap()
    assert identity.team_has_code(settings.default_team)
    assert "an access code" not in caplog.text.lower() or "generated" in caplog.text.lower()


def test_bootstrap_leaves_an_existing_code_alone(monkeypatch, team):
    monkeypatch.setattr(settings, "allowed_emails", BOB)
    identity.bootstrap()
    assert identity.sign_in(ALICE, CODE)[1].email == ALICE, "rotating here would lock the team out"
