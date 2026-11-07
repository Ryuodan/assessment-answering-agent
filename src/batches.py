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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src import store, uploads
from src.forms.model import DetectedForm
from src.identity import User
from src.logs import get_logger
from src.models import AnsweredQuestion

logger = get_logger(__name__)

SUBJECT = "batch"
"""What `events.record(subject_type=...)` should say about a batch."""

LAST_USED = (
    "MAX(b.updated_at, b.used_at, COALESCE((SELECT MAX(MAX(c.updated_at, c.used_at))"
    " FROM conversations c WHERE c.batch_id = b.batch_id), ''))"
)
"""When the questionnaire `b` was last used: changed, opened, or worked on in its chat (plan 033)."""


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
    product_id: str = ""
    """The product it is answered for, or "" for General (plan 023).

    A product's questionnaire is answered from that product's knowledge base
    and answer memory beside the shared ones, and what a person approves in it
    is remembered for that product.
    """
    used_at: str = ""
    """When it was last used, `LAST_USED`: what retention counts from (plan 033)."""

    @property
    def exists(self) -> bool:
        """Whether the uploaded file is still on disk.

        Worth asking before offering to fill it in: uploads live in a directory
        somebody may have cleared, and the answers outlive the file.
        """
        return bool(self.source_path.name) and self.source_path.exists()


def create(user: User, source: Path | None, form: DetectedForm, product_id: str = "") -> Batch:
    """Record a newly uploaded questionnaire, for a product or General (""); `source` None for a typed list."""
    batch_id = uuid.uuid4().hex[:12]
    now = store.utcnow()
    conn = store.connect()
    conn.execute(
        """
        INSERT INTO form_batches
            (batch_id, team_id, actor_email, source_name, source_path, format,
             detected, created_at, updated_at, product_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            batch_id,
            user.team_id,
            user.email,
            form.source_name,
            str(source or ""),
            form.format,
            form.model_dump_json(),
            now,
            now,
            product_id,
        ),
    )
    conn.commit()
    return Batch(
        id=batch_id,
        team_id=user.team_id,
        actor_email=user.email,
        source_name=form.source_name,
        source_path=source or Path(""),
        form=form,
        created_at=now,
        updated_at=now,
        product_id=product_id,
        used_at=now,
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
        product_id=row["product_id"],
        used_at=row["last_used"],
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
    sql = f"SELECT b.*, {LAST_USED} AS last_used FROM form_batches b WHERE b.batch_id = ?"
    params: list[object] = [batch_id]
    if team_id is not None:
        sql += " AND b.team_id = ?"
        params.append(team_id)
    if actor_email is not None:
        sql += " AND b.actor_email = ?"
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
    """One person's questionnaires, most recently used first, with how far each has got.

    Used is `LAST_USED`, which every write to it or its answers moves (plan 029,
    1.1), and since plan 033 opening it too: the one somebody was working on is
    the one they look for, whenever it was uploaded. `updated_at` is still when
    it last changed; filling and downloading move neither.

    `actor_email=None` lists the team's, which nothing a person clicks asks for.
    """
    conn = store.connect()
    sql = f"""
        SELECT b.batch_id, b.source_name, b.format, b.actor_email, b.created_at,
               b.updated_at, b.product_id, COUNT(a.question_id) AS answered, {LAST_USED} AS used_at
        FROM form_batches b
        LEFT JOIN batch_answers a ON a.batch_id = b.batch_id
        WHERE b.team_id = ?
    """
    params: list[object] = [team_id]
    if actor_email is not None:
        sql += " AND b.actor_email = ?"
        params.append(actor_email)
    # rowid breaks the tie: `updated_at` is accurate to the second, and two
    # files uploaded together came back in an arbitrary order without it.
    sql += " GROUP BY b.batch_id ORDER BY used_at DESC, b.rowid DESC LIMIT ?"
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
            "used_at": row["used_at"],
            "answered": row["answered"],
            "product_id": row["product_id"],
        }
        for row in rows
    ]


def same_upload(team_id: str, actor_email: str, content: bytes) -> list[dict[str, Any]]:
    """This person's questionnaires read from a file with exactly these bytes, last changed first.

    Uploading the same file again made a second, empty questionnaire beside
    the one with the answers (plan 029, 1.2). Matched against the files still
    on disk, whatever they are called -- a browser's "vendor (1).xlsx" is the
    same file -- so nothing new is stored. A file the storage limit removed
    matches nothing, and opening it again makes a new questionnaire, as before.

    `answered` is counted as `recent` counts it, so the two agree; the server's
    path to the file is not in what is returned.

    One nothing was read from is not offered. A Word file written as prose
    makes such a questionnaire on every read, and is then read as text;
    offered, it was "0 of 0 answered", and opening it read nothing (plan 029's
    review). Reading the file again is the only way on with it.
    """
    rows = (
        store.connect()
        .execute(
            """
        SELECT b.batch_id, b.source_name, b.source_path, b.detected, b.product_id,
               b.created_at, b.updated_at, COUNT(a.question_id) AS answered
        FROM form_batches b
        LEFT JOIN batch_answers a ON a.batch_id = b.batch_id
        WHERE b.team_id = ? AND b.actor_email = ?
        GROUP BY b.batch_id ORDER BY b.updated_at DESC, b.rowid DESC
        """,
            (team_id, actor_email),
        )
        .fetchall()
    )
    found = []
    for row in rows:
        if not uploads.holds(Path(row["source_path"]), content):
            continue
        questions = len(DetectedForm.model_validate_json(row["detected"]).questions)
        if not questions:
            continue
        found.append(
            {
                "id": row["batch_id"],
                "source_name": row["source_name"],
                "product_id": row["product_id"],
                "answered": row["answered"],
                "questions": questions,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
    return found


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


def saver(batch_id: str) -> Callable[[AnsweredQuestion], None]:
    """Save one answer of a run the moment it is drafted (plan 029).

    A run's answers were saved only when the whole run ended, so a large
    questionnaire cut short -- a restart, a crash -- lost every answer it had
    paid for. A failure here is logged and nothing more: the run's own last
    save stores the answer again.
    """

    def save(answer: AnsweredQuestion) -> None:
        try:
            save_answers(batch_id, [answer])
        except Exception:  # noqa: BLE001 - the run's last save stores it again
            logger.exception("batches.save_failed", batch_id=batch_id, question_id=answer.question.id)

    return save


def answers(batch_id: str) -> dict[str, AnsweredQuestion]:
    """Everything answered so far, by question id."""
    conn = store.connect()
    rows = conn.execute("SELECT question_id, payload FROM batch_answers WHERE batch_id = ?", (batch_id,)).fetchall()
    return {row["question_id"]: AnsweredQuestion.model_validate_json(row["payload"]) for row in rows}


def saved_at(batch_id: str) -> dict[str, str]:
    """When each answer was last saved, by question id (`store.utcnow`, comparable as text)."""
    conn = store.connect()
    rows = conn.execute("SELECT question_id, answered_at FROM batch_answers WHERE batch_id = ?", (batch_id,)).fetchall()
    return {row["question_id"]: row["answered_at"] for row in rows}


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


def touch(batch_id: str) -> None:
    """Record that a questionnaire was opened: opening is using it (plan 033). Nothing else changes."""
    conn = store.connect()
    with conn:
        conn.execute("UPDATE form_batches SET used_at = ? WHERE batch_id = ?", (store.utcnow(), batch_id))


def delete(batch_id: str) -> None:
    """Forget a batch and its answers; its chat keeps its messages. The files are `retention`'s."""
    conn = store.connect()
    conn.execute("DELETE FROM form_batches WHERE batch_id = ?", (batch_id,))
    conn.commit()
