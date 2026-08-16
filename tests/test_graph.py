"""Graph tests: routing, fan-out and per-question failure containment.

The LLM nodes are stubbed, so these run offline and exercise the wiring rather
than the model's judgement.
"""

from __future__ import annotations

import pytest

from src.config import settings
from src.graph import nodes
from src.graph.workflow import _answer_question, _fan_out
from src.models import AnswerReview, DraftedAnswer, Evidence, Question, SourceType


def _state(**overrides):
    base = {
        "question": Question(id="1", text="Are you certified?", language="en"),
        "language": "en",
        "search_query": "Are you certified?",
        "attempt": 1,
        "evidence": [],
        "draft": DraftedAnswer(answer="Yes.", confidence=0.9, used_source_ids=[1]),
        "review": AnswerReview(grounded=True, confidence=0.9),
    }
    return {**base, **overrides}


# --- routing ---------------------------------------------------------------


def test_grounded_answer_is_accepted():
    assert nodes.route_after_review(_state()) == "finalize"


def test_ungrounded_answer_retries_with_a_refined_query():
    state = _state(
        attempt=1,
        review=AnswerReview(grounded=False, refined_query="ISO 27001 certification status"),
    )
    assert nodes.route_after_review(state) == "retrieve"


def test_retry_stops_at_the_attempt_budget():
    """Without this the loop would hammer Groq forever on an unanswerable question."""
    state = _state(
        attempt=settings.max_answer_attempts,
        review=AnswerReview(grounded=False, refined_query="another try"),
    )
    assert nodes.route_after_review(state) == "finalize"


def test_no_retry_when_the_reviewer_offers_no_better_query():
    state = _state(attempt=1, review=AnswerReview(grounded=False, refined_query=""))
    assert nodes.route_after_review(state) == "finalize"


# --- finalize --------------------------------------------------------------


async def test_finalize_keeps_only_cited_evidence():
    """Citations are by index — several chunks share one file name."""
    evidence = [
        Evidence(source_type=SourceType.PRIOR_ANSWER, source_name="a.docx", snippet="one"),
        Evidence(source_type=SourceType.PRIOR_ANSWER, source_name="a.docx", snippet="two"),
        Evidence(source_type=SourceType.GUIDELINE, source_name="b.docx", snippet="three"),
    ]
    state = _state(
        evidence=evidence,
        draft=DraftedAnswer(answer="Yes.", confidence=0.9, used_source_ids=[1, 3]),
    )
    result = await nodes.finalize(state)
    assert [e.snippet for e in result["answered"].evidence] == ["one", "three"]


async def test_finalize_ignores_out_of_range_and_duplicate_citations():
    evidence = [Evidence(source_type=SourceType.GUIDELINE, source_name="b.docx", snippet="only")]
    state = _state(
        evidence=evidence,
        draft=DraftedAnswer(answer="Yes.", confidence=0.9, used_source_ids=[1, 1, 7, 0, -2]),
    )
    result = await nodes.finalize(state)
    assert [e.snippet for e in result["answered"].evidence] == ["only"]


async def test_finalize_takes_the_lower_of_the_two_confidences():
    state = _state(
        draft=DraftedAnswer(answer="Yes.", confidence=0.95, used_source_ids=[]),
        review=AnswerReview(grounded=True, confidence=0.4),
    )
    result = await nodes.finalize(state)
    answered = result["answered"]
    assert answered.confidence == pytest.approx(0.4)
    # Grounded but low confidence still goes to a human.
    assert answered.needs_review is True


async def test_ungrounded_answer_is_flagged_even_when_confident():
    state = _state(review=AnswerReview(grounded=False, confidence=0.95))
    result = await nodes.finalize(state)
    assert result["answered"].needs_review is True


# --- fan-out ---------------------------------------------------------------


def test_fan_out_sends_one_task_per_question():
    questions = [Question(id="1", text="a", language="en"), Question(id="2", text="b", language="ar")]
    sends = _fan_out({"questions": questions, "language": None})

    assert [send.node for send in sends] == ["answer", "answer"]
    # With no override, each question is answered in its own language.
    assert [send.arg["language"] for send in sends] == ["en", "ar"]


def test_fan_out_honours_a_forced_language():
    questions = [Question(id="1", text="a", language="en"), Question(id="2", text="b", language="ar")]
    sends = _fan_out({"questions": questions, "language": "ar"})
    assert [send.arg["language"] for send in sends] == ["ar", "ar"]


def test_fan_out_ends_cleanly_when_nothing_was_extracted():
    assert _fan_out({"questions": [], "language": None}) == "__end__"


# --- failure containment ---------------------------------------------------


async def test_one_failing_question_does_not_sink_the_run(monkeypatch):
    """A single bad Groq response must cost one answer, not the whole assessment."""

    class Exploding:
        async def ainvoke(self, *_args, **_kwargs):
            raise RuntimeError("groq exploded")

    monkeypatch.setattr("src.graph.workflow.question_graph", lambda: Exploding())

    result = await _answer_question({"question": Question(id="7", text="Why?", language="en")})
    answered = result["answers"][0]

    assert answered.question.id == "7"
    assert answered.answer == ""
    assert answered.needs_review is True
    assert "groq exploded" in answered.rationale
