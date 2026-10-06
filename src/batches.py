"""An uploaded questionnaire, and the answers written for it so far.

A batch is the thing a person actually works on: a customer's file, the
questions found in it, and however much of it has been answered. It outlives a
single request because that is the point -- answering 183 questions takes
minutes, corrections come afterwards, and the file gets filled in and downloaded
later still.

Answers are keyed by question rather than by position, so answering the
unanswered ones merges with what is already there rather than replacing it. That
is the difference between this and `runs`, which records one finished pass.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from src import store
from src.forms.model import DetectedForm
from src.identity import User
from src.models import AnsweredQuestion

SUBJECT = "batch"
"""What `events.record(subject_type=...)` should say about a batch."""


@dataclass(frozen=True)
class Batch:
    """One uploaded questionnaire and everything known about it."""

    id: str
    team_id: str
    actor_email: str
    source_name: str
    source_path: Path
    form: DetectedForm
    created_at: str
    updated_at: str
    detail: str = "full"
    """Which length of answer this questionnaire is filled in with."""

    @property
    def exists(self) -> bool:
        """Whether the uploaded file is still on disk.

        Worth asking before offering to fill it in: uploads live in a directory
        somebody may have cleared, and the answers outlive the file.
        """
        return self.source_path.exists()


def create(user: User, source: Path, form: DetectedForm) -> Batch:
    """Record a newly uploaded questionnaire. Returns the batch."""
    batch_id = uuid.uuid4().hex[:12]
    now = store.utcnow()
    conn = store.connect()
    conn.execute(
        """
        INSERT INTO form_batches
            (batch_id, team_id, actor_email, source_name, source_path, format,
             detected, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            batch_id,
            user.team_id,
            user.email,
            form.source_name,
            str(source),
            form.format,
            form.model_dump_json(),
            now,
            now,
        ),
    )
    conn.commit()
    return Batch(
        id=batch_id,
        team_id=user.team_id,
        actor_email=user.email,
        source_name=form.source_name,
        source_path=source,
        form=form,
        created_at=now,
        updated_at=now,
    )


def _row_to_batch(row) -> Batch:
    return Batch(
        id=row["batch_id"],
        team_id=row["team_id"],
        actor_email=row["actor_email"],
        source_name=row["source_name"],
        source_path=Path(row["source_path"]),
        form=DetectedForm.model_validate_json(row["detected"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        detail=(row["detail"] if "detail" in row.keys() else "full") or "full",
    )


def load(
    batch_id: str,
    *,
    team_id: str | None = None,
    actor_email: str | None = None,
) -> Batch | None:
    """One batch, or None.

    A questionnaire belongs to the person who uploaded it, and its answers with
    it: the file came from another company and is theirs to work on. One that
    is somebody else's -- or another team's -- reads as absent rather than
    forbidden, since which ids exist is not something a caller has business
    learning. `actor_email=None` skips the owner check, for housekeeping.
    """
    conn = store.connect()
    sql = "SELECT * FROM form_batches WHERE batch_id = ?"
    params: list[object] = [batch_id]
    if team_id is not None:
        sql += " AND team_id = ?"
        params.append(team_id)
    if actor_email is not None:
        sql += " AND actor_email = ?"
        params.append(actor_email)
    row = conn.execute(sql, params).fetchone()
    return _row_to_batch(row) if row else None


def claimed_sources(team_id: str) -> dict[str, str]:
    """Which uploaded file names in this team are somebody's questionnaire, and whose.

    The earliest batch wins. `save_upload` gives byte-identical content one
    name, so two people can end up reading one file, and it belongs to whoever
    got there first rather than to both.
    """
    rows = (
        store.connect()
        .execute(
            """
        SELECT source_path, actor_email FROM form_batches
         WHERE team_id = ? ORDER BY created_at, rowid
        """,
            (team_id,),
        )
        .fetchall()
    )
    claimed: dict[str, str] = {}
    for row in rows:
        claimed.setdefault(Path(row["source_path"]).name, row["actor_email"])
    return claimed


def recent(team_id: str, *, actor_email: str | None = None, limit: int = 25) -> list[dict]:
    """One person's questionnaires, newest first, with how far each has got.

    `actor_email=None` lists the team's, which nothing a person clicks asks for.
    """
    conn = store.connect()
    sql = """
        SELECT b.batch_id, b.source_name, b.format, b.actor_email, b.created_at,
               b.updated_at, COUNT(a.question_id) AS answered
        FROM form_batches b
        LEFT JOIN batch_answers a ON a.batch_id = b.batch_id
        WHERE b.team_id = ?
    """
    params: list[object] = [team_id]
    if actor_email is not None:
        sql += " AND b.actor_email = ?"
        params.append(actor_email)
    # rowid breaks the tie: `created_at` is accurate to the second, and two
    # files uploaded together came back in an arbitrary order without it.
    sql += " GROUP BY b.batch_id ORDER BY b.created_at DESC, b.rowid DESC LIMIT ?"
    params.append(max(1, limit))
    rows = conn.execute(sql, params).fetchall()
    return [
        {
            "id": row["batch_id"],
            "source_name": row["source_name"],
            "format": row["format"],
            "actor_email": row["actor_email"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "answered": row["answered"],
        }
        for row in rows
    ]


def save_answers(batch_id: str, answers: list[AnsweredQuestion], *, edited_by: str = "") -> None:
    """Store answers, merging with whatever is already there.

    Upsert rather than replace: a person answers the unanswered ones, then
    corrects three by hand, then answers a sheet that was skipped. Each of those
    is a write, and none of them should discard the others.
    """
    if not answers:
        return
    now = store.utcnow()
    conn = store.connect()
    with conn:
        conn.executemany(
            """
            INSERT INTO batch_answers (batch_id, question_id, answered_at, edited_by, payload)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(batch_id, question_id) DO UPDATE SET
                answered_at = excluded.answered_at,
                edited_by   = excluded.edited_by,
                payload     = excluded.payload
            """,
            [(batch_id, answer.question.id, now, edited_by, answer.model_dump_json()) for answer in answers],
        )
        conn.execute("UPDATE form_batches SET updated_at = ? WHERE batch_id = ?", (now, batch_id))


def answers(batch_id: str) -> dict[str, AnsweredQuestion]:
    """Everything answered so far, by question id."""
    conn = store.connect()
    rows = conn.execute("SELECT question_id, payload FROM batch_answers WHERE batch_id = ?", (batch_id,)).fetchall()
    return {row["question_id"]: AnsweredQuestion.model_validate_json(row["payload"]) for row in rows}


def edited_by(batch_id: str) -> dict[str, str]:
    """Which answers a person changed by hand, and who."""
    conn = store.connect()
    rows = conn.execute(
        "SELECT question_id, edited_by FROM batch_answers WHERE batch_id = ? AND edited_by != ''",
        (batch_id,),
    ).fetchall()
    return {row["question_id"]: row["edited_by"] for row in rows}


DETAIL_LEVELS = ("full", "brief")
"""How long the answers in a questionnaire should be.

Per questionnaire rather than per person, because the reason anybody wants
short answers is the size of the file in front of them: 183 rows due on
Thursday is a different job from twenty rows for a bank that will read every
word, and the same person wants both in different weeks.
"""


def set_detail(batch_id: str, detail: str) -> None:
    if detail not in DETAIL_LEVELS:
        raise ValueError(f"detail must be one of {DETAIL_LEVELS}, not {detail!r}")
    conn = store.connect()
    with conn:
        conn.execute(
            "UPDATE form_batches SET detail = ?, updated_at = ? WHERE batch_id = ?",
            (detail, store.utcnow(), batch_id),
        )


def forget_answer(batch_id: str, question_id: str) -> None:
    """Drop one stored answer, leaving the question as if it had never been answered.

    Not the same as storing an empty one: an empty answer is a decision to
    write nothing into the cell, and this is the undo of that decision. What
    the file itself arrived with is untouched either way -- it lives in the
    detected form, not in this table.
    """
    conn = store.connect()
    with conn:
        conn.execute(
            "DELETE FROM batch_answers WHERE batch_id = ? AND question_id = ?",
            (batch_id, question_id),
        )
        conn.execute(
            "UPDATE form_batches SET updated_at = ? WHERE batch_id = ?",
            (store.utcnow(), batch_id),
        )


def delete(batch_id: str) -> None:
    """Forget a batch and its answers. The uploaded file is left alone."""
    conn = store.connect()
    conn.execute("DELETE FROM form_batches WHERE batch_id = ?", (batch_id,))
    conn.commit()
