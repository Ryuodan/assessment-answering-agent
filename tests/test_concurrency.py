"""What raising MAX_CONCURRENT_QUESTIONS may and may not change.

The setting is meant to buy latency and nothing else. These pin the properties
that must survive it: answers come back in the order the questions were asked,
each answer belongs to its own question, the cap is actually honoured, and one
question failing under load stays contained.

Deliberately scrambled completion order — the later a question is asked the
faster it finishes — because that is exactly the arrangement a naive
"append as they arrive" collector would get wrong while looking fine serially.
"""

from __future__ import annotations

import asyncio

import pytest

from src import service
from src.config import settings
from src.models import AnsweredQuestion, Question


def questions(n: int) -> list[Question]:
    return [Question(id=str(i), text=f"Question number {i}?") for i in range(1, n + 1)]


@pytest.fixture
def scrambled(monkeypatch):
    """Answer each question after a delay that reverses the input order."""
    in_flight = 0
    peak = 0

    async def answerer(question: Question, language, *, run_id="", **_):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        try:
            await asyncio.sleep(0.05 * (10 - int(question.id)) / 10)
            return AnsweredQuestion(
                question=question,
                answer=f"answer to {question.text}",
                confidence=0.9,
                needs_review=False,
            )
        finally:
            in_flight -= 1

    monkeypatch.setattr(service, "answer_one_question", answerer)
    return lambda: peak


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 2, 4, 8])
async def test_answers_come_back_in_the_order_asked(monkeypatch, scrambled, concurrency):
    monkeypatch.setattr(settings, "max_concurrent_questions", concurrency)
    asked = questions(8)

    answers = await service.answer_questions(asked, language="en")

    assert [a.question.id for a in answers] == [q.id for q in asked]


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 4, 8])
async def test_every_answer_belongs_to_its_own_question(monkeypatch, scrambled, concurrency):
    monkeypatch.setattr(settings, "max_concurrent_questions", concurrency)
    asked = questions(8)

    answers = await service.answer_questions(asked, language="en")

    for question, answered in zip(asked, answers):
        assert answered.question.text == question.text
        assert answered.answer == f"answer to {question.text}"


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 2, 3])
async def test_the_cap_is_actually_honoured(monkeypatch, scrambled, concurrency):
    """The cap exists so a large assessment does not fan out into a rate limit."""
    monkeypatch.setattr(settings, "max_concurrent_questions", concurrency)

    await service.answer_questions(questions(9), language="en")

    assert scrambled() <= concurrency


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 4])
async def test_one_failure_stays_contained_at_any_concurrency(monkeypatch, concurrency):
    monkeypatch.setattr(settings, "max_concurrent_questions", concurrency)

    async def flaky(question: Question, language, *, run_id="", **_):
        if question.id == "3":
            raise RuntimeError("429 rate limit")
        return AnsweredQuestion(question=question, answer="ok", confidence=0.9, needs_review=False)

    monkeypatch.setattr(service, "answer_one_question", flaky)
    answers = await service.answer_questions(questions(6), language="en")

    assert len(answers) == 6
    assert [a.question.id for a in answers] == ["1", "2", "3", "4", "5", "6"]
    failed = [a for a in answers if a.error]
    assert len(failed) == 1 and failed[0].question.id == "3"
    assert all(a.answer == "ok" for a in answers if not a.error)


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 4])
async def test_progress_counts_every_question_once(monkeypatch, scrambled, concurrency):
    from src import progress

    monkeypatch.setattr(settings, "max_concurrent_questions", concurrency)
    await service.answer_questions(questions(7), language="en", run_id=f"batch-{concurrency}")

    state = progress.snapshot(f"batch-{concurrency}")
    assert state["total"] == 7
    assert state["completed"] == 7
    assert state["stage"] == "done"


@pytest.mark.asyncio
async def test_the_document_flow_is_capped_the_same_way(monkeypatch):
    """Two entry points, one setting: the fan-out uses LangGraph's
    `max_concurrency` where the list flow uses a semaphore, and they must not
    drift apart."""
    seen = {}

    class FakeGraph:
        async def ainvoke(self, state, config=None):
            seen["max_concurrency"] = (config or {}).get("max_concurrency")
            return {"answers": [], "questions": [], "language": "en"}

    monkeypatch.setattr(settings, "max_concurrent_questions", 5)
    monkeypatch.setattr(service, "assessment_graph", lambda: FakeGraph())

    async def fake_text(path):
        return "1. A question?"

    monkeypatch.setattr(service, "extracted_document_text", fake_text)
    await service.answer_assessment("some.pdf")

    assert seen["max_concurrency"] == 5
