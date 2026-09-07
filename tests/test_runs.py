"""Saving and reloading an answered run.

The contract is that what comes back is what went in — including the evidence,
which is the whole reason to keep a run rather than a summary of one. An answer
whose supporting chunks were dropped on the way to disk cannot be audited, and
auditing is most of why anyone reopens a run.
"""

from __future__ import annotations

import pytest

from src import identity, runs, store
from src.identity import User
from src.models import (
    AnsweredQuestion,
    AssessmentResult,
    Evidence,
    Question,
    SourceType,
)

ALICE = User(email="m.alsaif@t2.sa", team_id="cybersecurity")
BOB = User(email="mohammed.sa.alsaif@gmail.com", team_id="cybersecurity")
OTHER_TEAM = User(email="someone@t2.sa", team_id="privacy")


@pytest.fixture(autouse=True)
def _people():
    conn = store.connect()
    for user in (ALICE, BOB, OTHER_TEAM):
        identity.ensure_team(user.team_id)
        conn.execute(
            "INSERT INTO users (email, team_id, created_at, last_seen_at) VALUES (?, ?, ?, ?)",
            (user.email, user.team_id, store.utcnow(), store.utcnow()),
        )
    conn.commit()


def _evidence() -> Evidence:
    return Evidence(
        source_type=SourceType.GUIDELINE,
        source_name="T2 - Cryptography Policy.pdf",
        snippet="Data at rest shall be encrypted using AES-256.",
        score=0.81,
        doc_id="PRO-CRY-2024-00",
        clause="3.5.1",
        clause_start="3.5.1",
        page=12,
    )


def _answer(index: int, *, needs_review: bool = False, error: str = "") -> AnsweredQuestion:
    return AnsweredQuestion(
        question=Question(id=str(index), text=f"Question {index}?", language="en"),
        answer=f"Answer {index}.",
        rationale="From the cryptography policy.",
        confidence=0.9,
        needs_review=needs_review,
        evidence=[_evidence()],
        attempts=1,
        citations=["T2 - Cryptography Policy.pdf §3.5.1 (Page: 12)"],
        error=error,
    )


def _result(run_id: str = "r1", *, answers: list[AnsweredQuestion] | None = None) -> AssessmentResult:
    answers = [_answer(1), _answer(2)] if answers is None else answers
    return AssessmentResult(
        run_id=run_id,
        source_name="PSAT Questionnaire v2.1.xlsx",
        language="en",
        questions_found=len(answers),
        answers=answers,
    )


# --- round trip ------------------------------------------------------------


def test_a_saved_run_reloads_intact():
    runs.save(ALICE, _result())
    stored = runs.load("r1")

    assert stored is not None
    assert stored.summary.source_name == "PSAT Questionnaire v2.1.xlsx"
    assert stored.summary.actor_email == ALICE.email
    assert stored.summary.team_id == ALICE.team_id
    assert [answer.answer for answer in stored.answers] == ["Answer 1.", "Answer 2."]


def test_the_evidence_survives():
    """The expensive half of the payload, and the one that makes it auditable."""
    runs.save(ALICE, _result())
    [evidence] = runs.load("r1").answers[0].evidence
    assert evidence.snippet == "Data at rest shall be encrypted using AES-256."
    assert evidence.locator == "T2 - Cryptography Policy.pdf [PRO-CRY-2024-00] §3.5.1 (Page: 12)"


def test_answers_keep_their_order():
    answers = [_answer(index) for index in range(12)]
    runs.save(ALICE, _result(answers=answers))
    assert [a.question.id for a in runs.load("r1").answers] == [str(i) for i in range(12)]


def test_arabic_answers_round_trip():
    answer = _answer(1)
    answer.answer = "نعم، جميع البيانات مشفرة وفق معيار AES-256."
    runs.save(ALICE, _result(answers=[answer]))
    assert runs.load("r1").answers[0].answer == "نعم، جميع البيانات مشفرة وفق معيار AES-256."


def test_a_run_with_no_answers_is_still_a_run():
    runs.save(ALICE, _result(answers=[]))
    stored = runs.load("r1")
    assert stored is not None and stored.answers == []
    assert stored.summary.answer_count == 0


def test_a_run_survives_a_reconnect():
    runs.save(ALICE, _result())
    store.reset_connection()
    assert runs.load("r1") is not None


# --- counts ----------------------------------------------------------------


def test_the_summary_counts_reviews_and_errors():
    runs.save(ALICE, _result(answers=[
        _answer(1),
        _answer(2, needs_review=True),
        _answer(3, needs_review=True),
        _answer(4, error="Groq rate limit"),
    ]))
    summary = runs.load("r1").summary
    assert summary.answer_count == 4
    assert summary.needs_review_count == 2
    assert summary.error_count == 1


# --- replacing -------------------------------------------------------------


def test_saving_the_same_id_replaces_the_earlier_attempt():
    runs.save(ALICE, _result(answers=[_answer(i) for i in range(5)]))
    runs.save(ALICE, _result(answers=[_answer(1)]))

    stored = runs.load("r1")
    assert stored.summary.answer_count == 1, "a retry must not leave the old answers behind"
    assert store.connect().execute("SELECT COUNT(*) FROM run_answers").fetchone()[0] == 1


def test_replacing_does_not_duplicate_the_run_row():
    runs.save(ALICE, _result())
    runs.save(BOB, _result())
    assert store.connect().execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
    assert runs.load("r1").summary.actor_email == BOB.email


# --- listing ---------------------------------------------------------------


def test_recent_is_newest_first():
    for index in range(3):
        runs.save(ALICE, _result(run_id=f"r{index}"))
    assert [summary.run_id for summary in runs.recent(ALICE.team_id)] == ["r2", "r1", "r0"]


def test_recent_honours_the_limit():
    for index in range(6):
        runs.save(ALICE, _result(run_id=f"r{index}"))
    assert len(runs.recent(ALICE.team_id, limit=2)) == 2


def test_recent_shows_a_teammates_run():
    """One team shares a knowledge base, so it shares its submissions too."""
    runs.save(ALICE, _result(run_id="mine"))
    runs.save(BOB, _result(run_id="theirs"))
    assert {summary.run_id for summary in runs.recent("cybersecurity")} == {"mine", "theirs"}


def test_recent_does_not_cross_teams():
    runs.save(ALICE, _result(run_id="ours"))
    runs.save(OTHER_TEAM, _result(run_id="theirs"))
    assert [s.run_id for s in runs.recent("cybersecurity")] == ["ours"]
    assert [s.run_id for s in runs.recent("privacy")] == ["theirs"]


# --- lookups ---------------------------------------------------------------


def test_an_unknown_run_is_none():
    assert runs.load("never-existed") is None


def test_another_teams_run_reads_as_absent():
    """Not 403: which ids exist is not something a caller should learn."""
    runs.save(OTHER_TEAM, _result(run_id="secret"))
    assert runs.load("secret", team_id="cybersecurity") is None
    assert runs.load("secret", team_id="privacy") is not None


def test_load_without_a_team_finds_any_run():
    runs.save(OTHER_TEAM, _result(run_id="secret"))
    assert runs.load("secret") is not None
