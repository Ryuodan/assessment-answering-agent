"""Rewording answers that have no questionnaire behind them.

The batch route rewords a file's answers, keyed to the cells they belong in.
Questions typed by hand have no cells, and the wording box beside the answer
button is offered on both paths -- so this route exists to make the two behave
the same. The answers come in and go straight back out; the caller keeps them,
exactly as it does for `/answer-questions`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import rewrite
from src.api import app


@pytest.fixture
def client():
    return TestClient(app)


def _answer(text: str = "Yes. Access is reviewed quarterly.", id: str = "1") -> dict:
    return {
        "question": {"id": id, "text": "Are access rights reviewed?",
                     "question_type": "free_text", "options": [], "language": "en"},
        "answer": text,
        "rationale": "From the access control policy.",
        "confidence": 0.9,
        "needs_review": False,
        "review_reasons": [],
        "confidence_reason": "",
        "evidence": [],
        "attempts": 1,
        "citations": ["T2 - Access Control Policy.pdf §4.2"],
    }


@pytest.fixture
def shortens(monkeypatch):
    """Stand in for the rewriter, recording what it was asked."""
    seen: dict = {}

    async def fake(answered, instruction, language=None):
        seen.setdefault("instructions", []).append(instruction)
        seen["language"] = language
        revised = answered.model_copy(deep=True)
        revised.answer = "Short: " + answered.question.id
        return revised

    monkeypatch.setattr(rewrite, "rewrite", fake)
    return seen


def test_the_answers_come_back_reworded(client, shortens):
    body = client.post("/api/assessments/revise", json={
        "answers": [_answer(id="1"), _answer(id="2")],
        "instruction": "Keep it to one sentence.",
    }).json()

    assert [a["answer"] for a in body["answers"]] == ["Short: 1", "Short: 2"]
    assert shortens["instructions"] == ["Keep it to one sentence."] * 2


def test_the_order_is_the_order_it_was_given(client, shortens):
    """The caller ties each answer back to the row it came from by position,
    the same contract `/answer-questions` keeps."""
    body = client.post("/api/assessments/revise", json={
        "answers": [_answer(id="a"), _answer(id="b"), _answer(id="c")],
        "instruction": "Shorter.",
    }).json()
    assert [a["question"]["id"] for a in body["answers"]] == ["a", "b", "c"]


def test_the_citations_come_through(client, shortens):
    """Nothing was retrieved again, so nothing about the sources changed."""
    body = client.post("/api/assessments/revise", json={
        "answers": [_answer()], "instruction": "Shorter.",
    }).json()
    assert body["answers"][0]["citations"] == ["T2 - Access Control Policy.pdf §4.2"]


def test_a_requested_language_is_passed_on(client, shortens):
    client.post("/api/assessments/revise", json={
        "answers": [_answer()], "instruction": "Shorter.", "language": "ar",
    })
    assert shortens["language"] == "ar"


def test_it_can_be_watched_while_it_runs(client, shortens):
    """A hundred answers is a minute of work, and the page shows a bar for it."""
    body = client.post("/api/assessments/revise", json={
        "answers": [_answer()], "instruction": "Shorter.", "run_id": "watch-me",
    }).json()
    assert body["run_id"] == "watch-me"


def test_an_empty_instruction_is_refused(client):
    assert client.post("/api/assessments/revise", json={
        "answers": [_answer()], "instruction": "",
    }).status_code == 422


def test_no_answers_is_refused(client):
    assert client.post("/api/assessments/revise", json={
        "answers": [], "instruction": "Shorter.",
    }).status_code == 422


def test_a_failed_rewrite_costs_the_wording_not_the_answer(client, monkeypatch):
    """`rewrite` returns the original when the model fails, and the route does
    not turn that into an error: the answer had already passed review."""
    async def fails(answered, instruction, language=None):
        return answered

    monkeypatch.setattr(rewrite, "rewrite", fails)
    body = client.post("/api/assessments/revise", json={
        "answers": [_answer()], "instruction": "Shorter.",
    }).json()
    assert body["answers"][0]["answer"] == "Yes. Access is reviewed quarterly."


def test_signing_in_is_required(client, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings, "allowed_emails", "someone@else.com")
    with TestClient(app) as fresh:
        fresh.cookies.clear()
        response = fresh.post("/api/assessments/revise", json={
            "answers": [_answer()], "instruction": "Shorter.",
        })
    assert response.status_code in (401, 403)
