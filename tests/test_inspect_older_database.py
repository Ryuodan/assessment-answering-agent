"""The read-only `inspect` commands never upgrade an older database (plan 035).

They read through the app's own connection, which brings a database up to the
latest schema first. Run against an installation not yet started on new code,
`inspect retention` or `inspect fills` would have changed its schema: a
"read-only" command writing. They now ask the version on a read-only connection,
as `doctor` does, and refuse with a FIX when the database is older.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src import cli, migrations, store
from src.config import settings


def older_database(path: Path, version: int) -> None:
    conn = sqlite3.connect(path)
    for index, step in enumerate(store.MIGRATIONS[:version]):
        getattr(migrations, step)(conn) if step.startswith("_") else conn.executescript(step)
        conn.execute(f"PRAGMA user_version = {index + 1}")
    conn.commit()
    conn.close()


def version_of(path: Path) -> int:
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


@pytest.mark.parametrize("command", [["inspect", "retention"], ["inspect", "fills"]])
def test_an_older_database_is_left_as_it_is_and_said_so(command, tmp_path, monkeypatch, capsys) -> None:
    older = tmp_path / "older.db"
    older_database(older, 14)
    monkeypatch.setattr(settings, "db_path", older)
    store.reset_connection()

    assert cli.main(command) == 1
    assert version_of(older) == 14, "nothing was changed"
    said = capsys.readouterr().err
    assert "schema version 14" in said and "start the app once" in said


@pytest.mark.parametrize("command", [["inspect", "retention"], ["inspect", "fills"]])
def test_a_current_database_is_read_as_before(command) -> None:
    store.connect()  # the suite's own, at the latest schema
    assert cli.main(command) == 0
