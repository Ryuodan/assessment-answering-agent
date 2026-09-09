"""SQLite storage for identity, the event log, and answered runs.

Everything the system needs to remember between requests lives in one file.
Chroma still owns the policy corpus; this owns *who did what, when, and what
came out* — the half that has to survive a restart and be attributable to a
person.

Why SQLite: the store must always be available, and a second process to start
is a second thing to be down. One file is also one thing to back up, and
`sqlite3` is in the standard library, so this adds no dependency.

Connections are per-thread because FastAPI runs synchronous endpoints in a
worker pool and a SQLite connection is not safe to share across threads. The
schema is applied once per process under a lock, so two threads arriving at an
empty database at the same moment cannot both try to create it.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import settings

# Ordered, append-only. Each entry moves the schema forward exactly one step and
# `PRAGMA user_version` records how far a file has got. Never edit a migration
# that has shipped — add another.
MIGRATIONS: list[str] = [
    # 1 — identity, sessions, the event log, and answered runs.
    """
    CREATE TABLE teams (
        id          TEXT PRIMARY KEY,
        created_at  TEXT NOT NULL
    );

    CREATE TABLE users (
        email       TEXT PRIMARY KEY,
        team_id     TEXT NOT NULL REFERENCES teams(id),
        created_at  TEXT NOT NULL,
        last_seen_at TEXT NOT NULL
    );

    CREATE TABLE sessions (
        token_hash  TEXT PRIMARY KEY,
        email       TEXT NOT NULL REFERENCES users(email),
        created_at  TEXT NOT NULL,
        expires_at  TEXT NOT NULL
    );
    CREATE INDEX sessions_email ON sessions(email);

    CREATE TABLE events (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at   TEXT NOT NULL,
        team_id      TEXT NOT NULL,
        actor_email  TEXT NOT NULL,
        kind         TEXT NOT NULL,
        subject_type TEXT NOT NULL DEFAULT '',
        subject_id   TEXT NOT NULL DEFAULT '',
        payload      TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX events_team_time ON events(team_id, id DESC);
    CREATE INDEX events_subject ON events(subject_type, subject_id);

    CREATE TABLE runs (
        run_id          TEXT PRIMARY KEY,
        team_id         TEXT NOT NULL,
        actor_email     TEXT NOT NULL,
        source_name     TEXT NOT NULL,
        language        TEXT NOT NULL,
        questions_found INTEGER NOT NULL,
        created_at      TEXT NOT NULL
    );
    CREATE INDEX runs_team_time ON runs(team_id, created_at DESC);

    CREATE TABLE run_answers (
        run_id        TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
        ordinal       INTEGER NOT NULL,
        question_id   TEXT NOT NULL,
        question      TEXT NOT NULL,
        answer        TEXT NOT NULL,
        confidence    REAL NOT NULL,
        needs_review  INTEGER NOT NULL,
        attempts      INTEGER NOT NULL,
        error         TEXT NOT NULL DEFAULT '',
        payload       TEXT NOT NULL,
        PRIMARY KEY (run_id, ordinal)
    );
    """,
    # 2 — access is administered from inside the application rather than from
    # the environment. Whoever runs this system may not be whoever decides who
    # uses it, and an allow-list in `.env` can only be changed by the former.
    # A `users` row now *is* the allow-list; `ALLOWED_EMAILS` seeds it once.
    """
    ALTER TABLE teams ADD COLUMN name TEXT NOT NULL DEFAULT '';
    ALTER TABLE teams ADD COLUMN access_code_hash TEXT NOT NULL DEFAULT '';
    ALTER TABLE teams ADD COLUMN code_set_at TEXT NOT NULL DEFAULT '';

    ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'member';
    ALTER TABLE users ADD COLUMN password_hash TEXT NOT NULL DEFAULT '';
    ALTER TABLE users ADD COLUMN disabled INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE users ADD COLUMN added_by TEXT NOT NULL DEFAULT '';

    -- A shared code is only as strong as the number of guesses allowed against
    -- it, so the guesses are counted.
    CREATE TABLE sign_in_attempts (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        email      TEXT NOT NULL,
        created_at TEXT NOT NULL,
        succeeded  INTEGER NOT NULL
    );
    CREATE INDEX sign_in_attempts_email_time ON sign_in_attempts(email, created_at);
    """,
    # 3 -- a questionnaire someone uploaded, and the answers written for it.
    #
    # Separate from `runs` because it is a different thing. A run is one pass
    # over a list of questions and is finished when it returns. A batch is a
    # document somebody comes back to: answered in parts, corrected by hand,
    # filled in and downloaded, then perhaps answered again where it was left
    # blank. So its answers are keyed by question rather than by position, and
    # writing one twice merges rather than replaces.
    """
    CREATE TABLE form_batches (
        batch_id    TEXT PRIMARY KEY,
        team_id     TEXT NOT NULL,
        actor_email TEXT NOT NULL,
        source_name TEXT NOT NULL,
        source_path TEXT NOT NULL,
        format      TEXT NOT NULL,
        detected    TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    CREATE INDEX form_batches_team_time ON form_batches(team_id, created_at DESC);

    CREATE TABLE batch_answers (
        batch_id    TEXT NOT NULL REFERENCES form_batches(batch_id) ON DELETE CASCADE,
        question_id TEXT NOT NULL,
        answered_at TEXT NOT NULL,
        edited_by   TEXT NOT NULL DEFAULT '',
        payload     TEXT NOT NULL,
        PRIMARY KEY (batch_id, question_id)
    );
    """,
    # 4 -- a conversation with the assistant.
    #
    # Kept for the same reason a batch is: the work outlives the request. A
    # person says "read this file", waits four minutes for 183 answers, comes
    # back after lunch and says "now make the governance ones shorter" -- and
    # the second sentence only means anything if the first is still there.
    #
    # Messages are stored as LangChain serialised them, tool calls included,
    # rather than as a tidy transcript. The agent has to *resume*, and it can
    # only do that from what it actually said and saw; a display transcript
    # would lose which tool returned what, which is exactly the part a
    # follow-up instruction depends on.
    """
    CREATE TABLE conversations (
        conversation_id TEXT PRIMARY KEY,
        team_id         TEXT NOT NULL,
        actor_email     TEXT NOT NULL,
        title           TEXT NOT NULL DEFAULT '',
        batch_id        TEXT REFERENCES form_batches(batch_id) ON DELETE SET NULL,
        messages        TEXT NOT NULL DEFAULT '[]',
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL
    );
    CREATE INDEX conversations_team_time ON conversations(team_id, updated_at DESC);
    """,
    # 5 -- take the plumbing back out of the titles it leaked into.
    #
    # A message with a file attached carries a note telling the agent the file
    # is there. It belongs in the stored message, because that history is what
    # the agent re-reads -- but it was also going into the conversation's
    # title, so a person's own history read as a list of
    # "Read this file. [A file has been uploaded to this conversation: HR…"
    # rather than a list of what they had asked for.
    #
    # Fixed at the source, and repaired here for the conversations that already
    # have it: those titles are display text and nothing reads them back, so
    # trimming is safe. The note is truncated to three different lengths by the
    # title's own length limit, and every one of them starts the same way.
    """
    UPDATE conversations
       SET title = RTRIM(SUBSTR(title, 1, INSTR(title, '[A file has been') - 1))
     WHERE INSTR(title, '[A file has been') > 0;
    """,
    # 6 -- how long the answers in this questionnaire should be.
    #
    # Per questionnaire rather than per user or per team, because the reason
    # anybody wants short answers is the size of the file in front of them: 183
    # rows due on Thursday is a different job from twenty rows for a bank that
    # will read every word. The same person wants both, in different weeks.
    """
    ALTER TABLE form_batches ADD COLUMN detail TEXT NOT NULL DEFAULT 'full';
    """,
]

_local = threading.local()
_schema_lock = threading.Lock()
_schema_ready: set[str] = set()


def utcnow() -> str:
    """An ISO-8601 UTC timestamp, to the second.

    Text rather than a SQLite numeric date so a row is readable in any
    inspection tool, and sortable as a string because the format is fixed-width.
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _apply_schema(conn: sqlite3.Connection) -> None:
    """Bring one connection's database up to the latest migration."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for index in range(version, len(MIGRATIONS)):
        conn.executescript(MIGRATIONS[index])
        # No parameter binding for PRAGMA; the value is a loop index, not input.
        conn.execute(f"PRAGMA user_version = {index + 1}")
        conn.commit()


def connect() -> sqlite3.Connection:
    """This thread's connection, with the schema applied.

    Cached per thread and per database path, so pointing `settings.db_path` at a
    temporary file mid-process — which every test does — opens a fresh
    connection rather than silently reusing the previous database.
    """
    path = str(settings.db_path)
    cached = getattr(_local, "conn", None)
    if cached is not None and getattr(_local, "path", None) == path:
        return cached

    if cached is not None:
        cached.close()

    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # WAL lets readers run while a writer holds the file, which matters as soon
    # as a batch is writing answers while someone loads their history.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # Wait rather than raise when another thread holds the write lock. Without
    # it, two concurrent writes surface as "database is locked" 500s.
    conn.execute("PRAGMA busy_timeout=5000")

    with _schema_lock:
        if path not in _schema_ready:
            _apply_schema(conn)
            _schema_ready.add(path)

    _local.conn = conn
    _local.path = path
    return conn


def reset_connection() -> None:
    """Drop this thread's cached connection and forget any applied schema.

    For tests, which point `db_path` at a fresh temporary file between cases.
    """
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
    _local.conn = None
    _local.path = None
    with _schema_lock:
        _schema_ready.clear()


def dumps(value: Any) -> str:
    """JSON for a payload column, safe for Arabic."""
    return json.dumps(value, ensure_ascii=False, default=str)


def loads(value: str | None) -> Any:
    """Read a payload column, tolerating a row written before a field existed."""
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def database_size() -> int:
    """Bytes on disk, or 0 before anything has been written."""
    path = Path(settings.db_path)
    return path.stat().st_size if path.exists() else 0
