"""Migrations written in Python, because they need a setting. Listed by name in `src.migrations`.

Moved out of `src/migrations.py` unchanged (TD-046): the list of migrations only
grows, and the module holding it was at its size limit. `src.migrations` names
each step here as `_<name>`, which is how `src.store` finds and runs it.
"""

from __future__ import annotations

import sqlite3

from src.config import settings


def team_the_answer_memory(conn: sqlite3.Connection) -> None:
    """Migration 10, in Python because it needs to know the default team's name."""
    team = settings.default_team
    conn.executescript(
        """
        CREATE TABLE memory_entries_by_team (
            entry_id      TEXT NOT NULL,
            team_id       TEXT NOT NULL,
            question      TEXT NOT NULL,
            answer        TEXT NOT NULL,
            section       TEXT NOT NULL DEFAULT '',
            from_file     TEXT NOT NULL DEFAULT '',
            origin        TEXT NOT NULL DEFAULT 'import',
            approved_by   TEXT NOT NULL DEFAULT '',
            approved_on   TEXT NOT NULL DEFAULT '',
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL,
            scanned_at    TEXT NOT NULL DEFAULT '',
            superseded_by TEXT NOT NULL DEFAULT '',
            superseded_on TEXT NOT NULL DEFAULT '',
            because       TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (team_id, entry_id)
        );
        CREATE TABLE memory_conflicts_by_team (
            team_id     TEXT NOT NULL,
            entry_id    TEXT NOT NULL,
            other_id    TEXT NOT NULL,
            because     TEXT NOT NULL DEFAULT '',
            raised_at   TEXT NOT NULL,
            resolved_at TEXT NOT NULL DEFAULT '',
            resolved_by TEXT NOT NULL DEFAULT '',
            resolution  TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (team_id, entry_id, other_id)
        );
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO memory_entries_by_team
            (entry_id, team_id, question, answer, section, from_file, origin, approved_by,
             approved_on, created_at, updated_at, scanned_at, superseded_by, superseded_on, because)
        SELECT entry_id, CASE WHEN team_id = '' THEN ? ELSE team_id END, question, answer,
               section, from_file, origin, approved_by, approved_on, created_at, updated_at,
               scanned_at, superseded_by, superseded_on, because
          FROM memory_entries
        """,
        (team,),
    )
    # A disagreement belongs to the team whose entries it is between.
    conn.execute(
        """
        INSERT OR IGNORE INTO memory_conflicts_by_team
            (team_id, entry_id, other_id, because, raised_at, resolved_at, resolved_by, resolution)
        SELECT COALESCE(NULLIF((SELECT e.team_id FROM memory_entries e WHERE e.entry_id = c.entry_id), ''), ?),
               entry_id, other_id, because, raised_at, resolved_at, resolved_by, resolution
          FROM memory_conflicts c
        """,
        (team,),
    )
    conn.executescript(
        """
        DROP TABLE memory_entries;
        DROP TABLE memory_conflicts;
        ALTER TABLE memory_entries_by_team RENAME TO memory_entries;
        ALTER TABLE memory_conflicts_by_team RENAME TO memory_conflicts;
        CREATE INDEX memory_entries_team_updated ON memory_entries(team_id, updated_at DESC);
        CREATE INDEX memory_entries_pending ON memory_entries(scanned_at);
        CREATE INDEX memory_conflicts_open ON memory_conflicts(team_id, resolved_at);
        """
    )
