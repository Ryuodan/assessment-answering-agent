"""Answered runs, kept so they can be looked at again.

A run is one pass over a questionnaire: the questions, the answers, and the
evidence behind each. Today this backs the history list — "what did we send to
Bank Albilad last month?" — and it is the substrate the later phases need, since
revising answer 12 requires answer 12 to still exist somewhere.

The full `AnsweredQuestion` goes into `payload`, evidence included, and the
fields worth filtering on are lifted into columns beside it. Storing the
evidence is the expensive choice — a large run is a few megabytes — and it is
the right one: an answer whose supporting chunks have been thrown away cannot be
audited, which is most of why anyone would come back to it.
"""

from __future__ import annotations

from dataclasses import dataclass

from src import store
from src.identity import User
from src.models import AnsweredQuestion, AssessmentResult, Language

SUBJECT = "run"
"""What `events.record(subject_type=...)` should say about a run."""


@dataclass(frozen=True)
class RunSummary:
    """One row of the history list — enough to show it without loading answers."""

    run_id: str
    team_id: str
    actor_email: str
    source_name: str
    language: Language
    questions_found: int
    created_at: str
    answer_count: int
    needs_review_count: int
    error_count: int


@dataclass(frozen=True)
class StoredRun:
    """A summary plus the answers themselves."""

    summary: RunSummary
    answers: list[AnsweredQuestion]


def save(user: User, result: AssessmentResult) -> None:
    """Write one finished run. Replaces any earlier attempt with the same id.

    Replacing rather than refusing because a re-run under the same id is a
    retry, and a half-written run from a crash should not block it. The delete
    cascades to `run_answers`, so a retry that produced fewer answers cannot
    leave the extras behind.
    """
    conn = store.connect()
    with conn:  # one transaction: a run and its answers arrive together or not at all
        conn.execute("DELETE FROM runs WHERE run_id = ?", (result.run_id,))
        conn.execute(
            """
            INSERT INTO runs
                (run_id, team_id, actor_email, source_name, language, questions_found, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.run_id,
                user.team_id,
                user.email,
                result.source_name,
                result.language,
                result.questions_found,
                store.utcnow(),
            ),
        )
        conn.executemany(
            """
            INSERT INTO run_answers
                (run_id, ordinal, question_id, question, answer, confidence,
                 needs_review, attempts, error, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    result.run_id,
                    ordinal,
                    answered.question.id,
                    answered.question.text,
                    answered.answer,
                    answered.confidence,
                    int(answered.needs_review),
                    answered.attempts,
                    answered.error,
                    answered.model_dump_json(),
                )
                for ordinal, answered in enumerate(result.answers)
            ],
        )


_SUMMARY_SQL = """
    SELECT r.*,
           COUNT(a.ordinal)                             AS answer_count,
           COALESCE(SUM(a.needs_review), 0)             AS needs_review_count,
           COALESCE(SUM(a.error != ''), 0)              AS error_count
    FROM runs r
    LEFT JOIN run_answers a ON a.run_id = r.run_id
"""


def _row_to_summary(row) -> RunSummary:
    return RunSummary(
        run_id=row["run_id"],
        team_id=row["team_id"],
        actor_email=row["actor_email"],
        source_name=row["source_name"],
        language=row["language"],
        questions_found=row["questions_found"],
        created_at=row["created_at"],
        answer_count=row["answer_count"],
        needs_review_count=row["needs_review_count"],
        error_count=row["error_count"],
    )


def recent(team_id: str, *, actor_email: str | None = None, limit: int = 25) -> list[RunSummary]:
    """One person's runs, newest first.

    These were the team's, on the reasoning that a colleague's submission to the
    same bank is what somebody needs before writing a new one. What it meant in
    practice is that everyone's history held everyone's questionnaires, which
    arrive from other companies under an NDA. What the team shares is its
    policies and its remembered answers -- both of which a new run draws on
    whoever did the last one.
    """
    conn = store.connect()
    sql = _SUMMARY_SQL + " WHERE r.team_id = ?"
    params: list[object] = [team_id]
    if actor_email is not None:
        sql += " AND r.actor_email = ?"
        params.append(actor_email)
    sql += " GROUP BY r.run_id ORDER BY r.created_at DESC, r.rowid DESC LIMIT ?"
    params.append(max(1, limit))
    return [_row_to_summary(row) for row in conn.execute(sql, params).fetchall()]


def load(
    run_id: str,
    *,
    team_id: str | None = None,
    actor_email: str | None = None,
) -> StoredRun | None:
    """One run with its answers, or None.

    Scoped like everything else a person does: another team's run, or a
    colleague's, reads as "not found" rather than "forbidden", since which ids
    exist is itself something the caller has no business learning.
    """
    conn = store.connect()
    sql = _SUMMARY_SQL + " WHERE r.run_id = ?"
    params: list[object] = [run_id]
    if team_id is not None:
        sql += " AND r.team_id = ?"
        params.append(team_id)
    if actor_email is not None:
        sql += " AND r.actor_email = ?"
        params.append(actor_email)
    row = conn.execute(sql + " GROUP BY r.run_id", params).fetchone()
    if row is None or row["run_id"] is None:
        return None

    answers = [
        AnsweredQuestion.model_validate_json(record["payload"])
        for record in conn.execute(
            "SELECT payload FROM run_answers WHERE run_id = ? ORDER BY ordinal", (run_id,)
        ).fetchall()
    ]
    return StoredRun(summary=_row_to_summary(row), answers=answers)
