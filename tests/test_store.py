"""The SQLite layer: schema application, connection reuse, and JSON payloads.

These are the guarantees everything else in Phase 0 assumes. A migration that
runs twice, or a connection cached across a database swap, would produce
failures a long way from the cause.
"""

from __future__ import annotations

import sqlite3
import threading

import pytest

from src import store
from src.config import settings


# --- schema ----------------------------------------------------------------


def test_connect_creates_the_schema():
    conn = store.connect()
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"teams", "users", "sessions", "events", "runs", "run_answers"} <= tables


def test_schema_version_matches_the_migration_count():
    conn = store.connect()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(store.MIGRATIONS)


def test_reapplying_the_schema_is_a_no_op():
    """A second process opening the same file must not re-run migration 1."""
    store.connect()
    store.reset_connection()
    conn = store.connect()  # would raise "table teams already exists" if re-run
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(store.MIGRATIONS)


def test_existing_data_survives_a_reopen():
    store.connect().execute(
        "INSERT INTO teams (id, created_at) VALUES ('cyber', '2026-01-01T00:00:00+00:00')"
    )
    store.connect().commit()
    store.reset_connection()
    assert store.connect().execute("SELECT COUNT(*) FROM teams").fetchone()[0] == 1


def test_a_version_1_database_upgrades_without_losing_anything():
    """Migration 2 lands on databases that already hold real work.

    Built by applying only migration 1, which is what a deployment installed
    before the admin page existed actually has on disk.
    """
    conn = store.connect()
    # Derived rather than listed. A hard-coded list is a second place to
    # remember every new table, and it silently stopped dropping the two that
    # migration 3 added.
    tables = [
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript("".join(f"DROP TABLE IF EXISTS {name};" for name in tables))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(store.MIGRATIONS[0])
    conn.execute("PRAGMA user_version = 1")
    conn.execute("INSERT INTO teams (id, created_at) VALUES ('cybersecurity', '2026-01-01T00:00:00+00:00')")
    conn.execute(
        "INSERT INTO users (email, team_id, created_at, last_seen_at) "
        "VALUES ('m.alsaif@t2.sa', 'cybersecurity', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO events (created_at, team_id, actor_email, kind) "
        "VALUES ('2026-01-01T00:00:00+00:00', 'cybersecurity', 'm.alsaif@t2.sa', 'signed_in')"
    )
    conn.commit()
    store.reset_connection()

    upgraded = store.connect()
    assert upgraded.execute("PRAGMA user_version").fetchone()[0] == len(store.MIGRATIONS)

    row = upgraded.execute("SELECT email, role, disabled FROM users").fetchone()
    assert row["email"] == "m.alsaif@t2.sa"
    assert row["role"] == "member", "an existing user must not silently become an admin"
    assert row["disabled"] == 0, "an upgrade must not lock existing people out"
    assert upgraded.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_an_upgraded_database_gets_an_access_code_rather_than_locking_everyone_out():
    """The hazard the upgrade creates, and the safety net for it.

    After migration 2 an existing deployment has users — so sign-in is required
    — but no team access code, which would mean nobody can get in. `bootstrap`
    notices and issues one.
    """
    from src import identity

    identity.add_user("m.alsaif@t2.sa")
    store.connect().execute("UPDATE teams SET access_code_hash = ''")
    store.connect().commit()
    assert identity.sign_in_required() and not identity.team_has_code(settings.default_team)

    identity.bootstrap()
    assert identity.team_has_code(settings.default_team)


def test_foreign_keys_are_enforced():
    """Without the pragma SQLite ignores REFERENCES entirely, silently."""
    conn = store.connect()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO users (email, team_id, created_at, last_seen_at) "
            "VALUES ('a@b.c', 'no-such-team', '2026-01-01', '2026-01-01')"
        )


# --- connections -----------------------------------------------------------


def test_the_same_thread_reuses_one_connection():
    assert store.connect() is store.connect()


def test_pointing_at_a_new_database_opens_a_new_connection(tmp_path, monkeypatch):
    """The temp_database fixture swaps db_path per test; caching must notice."""
    first = store.connect()
    monkeypatch.setattr(settings, "db_path", tmp_path / "other.db")
    second = store.connect()
    assert first is not second
    assert second.execute("SELECT COUNT(*) FROM teams").fetchone()[0] == 0


def test_each_thread_gets_its_own_connection():
    """A SQLite connection shared across threads is undefined behaviour."""
    main = store.connect()
    seen: list[sqlite3.Connection] = []
    thread = threading.Thread(target=lambda: seen.append(store.connect()))
    thread.start()
    thread.join()
    assert seen and seen[0] is not main


def test_concurrent_writers_do_not_collide():
    """busy_timeout plus WAL should absorb contention rather than raise."""
    store.connect()  # create the schema before the threads race for it
    errors: list[Exception] = []

    def write(n: int) -> None:
        try:
            conn = store.connect()
            for i in range(20):
                conn.execute(
                    "INSERT INTO teams (id, created_at) VALUES (?, ?)",
                    (f"team-{n}-{i}", store.utcnow()),
                )
                conn.commit()
        except Exception as error:  # pragma: no cover - only on failure
            errors.append(error)

    threads = [threading.Thread(target=write, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, errors
    assert store.connect().execute("SELECT COUNT(*) FROM teams").fetchone()[0] == 80


# --- payloads --------------------------------------------------------------


def test_json_round_trip_keeps_arabic_readable():
    encoded = store.dumps({"answer": "نعم، لدينا سياسة معتمدة"})
    assert "نعم" in encoded, "ensure_ascii would make this unreadable in the file"
    assert store.loads(encoded)["answer"] == "نعم، لدينا سياسة معتمدة"


@pytest.mark.parametrize("value", ["", None, "not json at all", "{broken"])
def test_loads_tolerates_unreadable_payloads(value):
    """A row written by an older version should not take down a history page."""
    assert store.loads(value) == {}


def test_utcnow_is_sortable_and_timezone_aware():
    assert store.utcnow() < "9999"
    assert store.utcnow().endswith("+00:00")


def test_database_size_is_zero_before_anything_is_written():
    assert store.database_size() == 0
    store.connect()
    assert store.database_size() > 0
