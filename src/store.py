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

from src import migrations
from src.config import settings
from src.migrations import MIGRATIONS as MIGRATIONS


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
    """Bring one connection's database up to the latest migration.

    A migration is SQL, or -- when it needs a setting, such as the name of the
    default team -- the name of a function in `src.migrations` taking the connection.
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for index in range(version, len(MIGRATIONS)):
        step = MIGRATIONS[index]
        if step.startswith("_"):
            getattr(migrations, step)(conn)
        else:
            conn.executescript(step)
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
