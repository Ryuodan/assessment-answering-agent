"""An append-only record of what people and the system did.

Every action worth explaining later lands here: who signed in, which runs were
started and how they ended, which answers a person changed. Nothing updates or
deletes a row — a correction is a new event, so the history stays the history.

This is the substrate the feedback loop and the "why does the file say that?"
question are built on, and it is cheap enough to write on every action that
there is no reason to be selective. What it is *not* is a log: logs are for
debugging and get rotated away, and this has to still be here in a year.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src import store
from src.identity import User

# The kinds in use today. Plain strings rather than an enum because a new kind
# should not need a schema change or a migration — but naming the known ones in
# one place stops "answer_edit" and "answer_edited" both appearing.
SIGNED_IN = "signed_in"
SIGNED_OUT = "signed_out"
RUN_STARTED = "run_started"
RUN_FINISHED = "run_finished"
RUN_FAILED = "run_failed"
ANSWER_EDITED = "answer_edited"
FEEDBACK_LEFT = "feedback_left"
FILE_FILLED = "file_filled"
DOCUMENT_INDEXED = "document_indexed"
SOURCE_REMOVED = "source_removed"
# Administration. Who can reach the system, and who changed that.
USER_ADDED = "user_added"
USER_UPDATED = "user_updated"
USER_REMOVED = "user_removed"
PASSWORD_SET = "password_set"
TEAM_ADDED = "team_added"
TEAM_REMOVED = "team_removed"
CODE_ROTATED = "access_code_rotated"
PRODUCT_ADDED = "product_added"
PRODUCT_UPDATED = "product_updated"
PRODUCT_DELETED = "product_deleted"
PRODUCT_CHOSEN = "product_chosen"  # for a questionnaire or a chat (plan 023)
# Questionnaires: a file opened, answered, revised, and written back.
FORM_OPENED = "form_opened"
BATCH_ANSWERED = "batch_answered"
BATCH_REVISED = "batch_revised"
ROLES_CORRECTED = "roles_corrected"
QUESTIONS_CORRECTED = "questions_corrected"

# The answer memory: what we have said before, and who decided it still holds.
MEMORY_ADDED = "memory_added"
MEMORY_EDITED = "memory_edited"
MEMORY_REMOVED = "memory_removed"
MEMORY_RESOLVED = "memory_conflict_resolved"

# How one person wants answers worded: their house style, and their skills.
PREFERENCES_CHANGED = "preferences_changed"
SKILL_ADDED = "skill_added"
SKILL_EDITED = "skill_edited"
SKILL_REMOVED = "skill_removed"
SKILL_APPLIED = "skill_applied"

ASSISTANT_STARTED = "assistant_started"
ASSISTANT_TURN = "assistant_turn"

# Housekeeping: files removed because a team went over its storage limit.
FILES_REMOVED = "files_removed"


@dataclass(frozen=True)
class Event:
    """One recorded action."""

    id: int
    created_at: str
    team_id: str
    actor_email: str
    kind: str
    subject_type: str
    subject_id: str
    payload: dict[str, Any]


def record(
    user: User,
    kind: str,
    *,
    subject_type: str = "",
    subject_id: str = "",
    **payload: Any,
) -> int:
    """Append one event. Returns its id.

    `subject_type` / `subject_id` say what the event is *about* — a run, an
    answer, a document — so the history of one thing can be pulled out without
    scanning every event the team ever generated.
    """
    if not kind:
        raise ValueError("An event needs a kind.")
    conn = store.connect()
    cursor = conn.execute(
        """
        INSERT INTO events (created_at, team_id, actor_email, kind, subject_type, subject_id, payload)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            store.utcnow(),
            user.team_id,
            user.email,
            kind,
            subject_type,
            subject_id,
            store.dumps(payload),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def _row_to_event(row) -> Event:
    return Event(
        id=row["id"],
        created_at=row["created_at"],
        team_id=row["team_id"],
        actor_email=row["actor_email"],
        kind=row["kind"],
        subject_type=row["subject_type"],
        subject_id=row["subject_id"],
        payload=store.loads(row["payload"]),
    )


def recent(team_id: str, *, limit: int = 50, kind: str | None = None) -> list[Event]:
    """The team's latest events, newest first.

    Ordered by id rather than timestamp: `utcnow()` is only accurate to the
    second, so several events within the same second would otherwise come back
    in an arbitrary order — and the order they happened in is usually the
    point.
    """
    conn = store.connect()
    sql = "SELECT * FROM events WHERE team_id = ?"
    params: list[Any] = [team_id]
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, limit))
    return [_row_to_event(row) for row in conn.execute(sql, params).fetchall()]


def for_subject(subject_type: str, subject_id: str) -> list[Event]:
    """Everything recorded about one thing, oldest first.

    Oldest first because this reads as a story — created, answered, edited,
    filled — rather than a feed.
    """
    conn = store.connect()
    rows = conn.execute(
        "SELECT * FROM events WHERE subject_type = ? AND subject_id = ? ORDER BY id",
        (subject_type, subject_id),
    ).fetchall()
    return [_row_to_event(row) for row in rows]
