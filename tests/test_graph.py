"""Graph tests: routing, fan-out and per-question failure containment.

The LLM nodes are stubbed, so these run offline and exercise the wiring rather
than the model's judgement.
"""

from __future__ import annotations

import pytest

from src.config import settings
from src.graph import nodes
from src.graph.workflow import _answer_question, _fan_out
from src.models import AnsweredQuestion, AnswerReview, DraftedAnswer, Evidence, Question, SourceType


def _state(**overrides):
    base = {
        "question": Question(id="1", text="Are you certified?", language="en"),
        "language": "en",
        "search_queries": ["Are you certified?"],
        "attempt": 1,
        "evidence": [],
        "draft": DraftedAnswer(answer="Yes.", confidence=0.9, used_source_ids=[1]),
        "review": AnswerReview(grounded=True, confidence=0.9),
    }
    return {**base, **overrides}


# --- query planning --------------------------------------------------------


async def test_plan_keeps_the_question_itself_and_adds_the_variants(monkeypatch):
    monkeypatch.setattr(settings, "query_expansion", True)
    _stub_plan(monkeypatch, ["access revoked on termination", "إلغاء صلاحيات الوصول"])

    result = await nodes.plan(_state())

    assert result["search_queries"][0] == "Are you certified?"
    assert "access revoked on termination" in result["search_queries"]


async def test_plan_is_a_single_query_when_expansion_is_off(monkeypatch):
    monkeypatch.setattr(settings, "query_expansion", False)
    assert (await nodes.plan(_state()))["search_queries"] == ["Are you certified?"]


async def test_plan_falls_back_to_the_question_when_planning_fails(monkeypatch):
    """A planning failure must cost recall, never the answer."""
    monkeypatch.setattr(settings, "query_expansion", True)

    def explode(*args, **kwargs):
        raise RuntimeError("groq is down")

    monkeypatch.setattr(nodes, "chat_llm", explode)
    assert (await nodes.plan(_state()))["search_queries"] == ["Are you certified?"]


async def test_plan_deduplicates_and_caps(monkeypatch):
    monkeypatch.setattr(settings, "query_expansion", True)
    monkeypatch.setattr(settings, "max_search_queries", 3)
    _stub_plan(monkeypatch, ["Are you certified?", "iso 27001 scope", "certification body", "audit date", "surveillance"])

    queries = (await nodes.plan(_state()))["search_queries"]

    assert queries == ["Are you certified?", "iso 27001 scope", "certification body"]


def _stub_plan(monkeypatch, queries):
    """The plan node reads plain text, one query per line."""
    class _Response:
        content = chr(10).join(queries)

    class _Runnable:
        async def ainvoke(self, _messages):
            return _Response()

    monkeypatch.setattr(nodes, "chat_llm", lambda *args, **kwargs: _Runnable())


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


def test_query_parsing_survives_the_shapes_models_actually_emit():
    """Numbered lists, bullets, quotes and a reasoning preamble."""
    parsed = nodes._parse_queries(
        "<think>splitting this up</think>\n"
        "1. access revocation on termination\n"
        "- exit clearance form requirement\n"
        '"notification of affected subscribers"\n'
        "Here are the queries:\n"
    )
    assert parsed == [
        "access revocation on termination",
        "exit clearance form requirement",
        "notification of affected subscribers",
    ]


def test_query_parsing_drops_commentary_and_blank_lines():
    parsed = nodes._parse_queries(
        "short one\n\n" + ("a very long sentence of commentary " * 8) + "\n"
    )
    assert parsed == ["short one"]


def test_query_parsing_handles_content_blocks():
    assert nodes._parse_queries([{"text": "first query\nsecond query"}]) == ["first query", "second query"]


async def test_a_failing_question_does_not_discard_the_whole_batch(monkeypatch):
    """A transient upstream error cost a nearly-finished 42-question run."""
    from src import service

    async def flaky(question, language, *, run_id=""):
        if question.id == "2":
            raise RuntimeError("model is not available in the specified region")
        return AnsweredQuestion(question=question, answer="fine", confidence=0.8, needs_review=False)

    monkeypatch.setattr(service, "answer_one_question", flaky)

    answers = await service.answer_questions(
        [Question(id=str(n), text=f"q{n}", language="en") for n in (1, 2, 3)]
    )

    assert [a.question.id for a in answers] == ["1", "2", "3"]
    assert answers[0].answer == "fine" and answers[2].answer == "fine"
    assert answers[1].answer == "" and answers[1].needs_review
    assert "not available" in answers[1].rationale


# --- the two entry points must answer identically --------------------------


async def test_the_document_flow_and_the_batch_flow_run_the_same_pipeline(monkeypatch):
    """The web interface answers a document; the harness answers a list.

    Both must put each question through the same inner graph, or the numbers
    the evaluation reports describe a system the interface does not run.
    """
    from src import service
    from src.graph import workflow

    seen: list[tuple[str, tuple]] = []

    async def spy(state):
        seen.append((state["question"].id, tuple(state.get("search_queries") or ())))
        return {
            "answered": AnsweredQuestion(
                question=state["question"], answer="ok", confidence=0.9, needs_review=False
            )
        }

    class _Graph:
        async def ainvoke(self, state, config=None):
            return await spy(state)

    monkeypatch.setattr(workflow, "question_graph", lambda: _Graph())

    questions = [Question(id="1", text="First question?", language="en")]

    # The batch entry point, as the evaluation harness uses it.
    await service.answer_questions(questions)
    via_batch = list(seen)

    # The document entry point, with extraction stubbed to yield the same question.
    seen.clear()

    async def fake_extract(state):
        return {"questions": questions, "document_language": "en"}

    monkeypatch.setattr(nodes, "extract", fake_extract)
    workflow.assessment_graph.cache_clear()
    state = await workflow.assessment_graph().ainvoke(
        {"source_name": "a.pdf", "document_text": "irrelevant", "language": None,
         "questions": [], "answers": []}
    )
    via_document = list(seen)
    workflow.assessment_graph.cache_clear()

    assert via_batch == via_document
    assert [a.question.id for a in state["answers"]] == ["1"]


# --- progress reporting ----------------------------------------------------


async def test_progress_reaches_the_end_of_its_own_bar(monkeypatch):
    """The bar must close at total/total, including when a question fails."""
    from src import progress, service
    from src.graph import workflow

    questions = [Question(id=str(n), text=f"q{n}", language="en") for n in (1, 2, 3)]

    async def fake_extract(state):
        return {"questions": questions, "document_language": "en"}

    class _Graph:
        async def ainvoke(self, state, config=None):
            if state["question"].id == "2":
                raise RuntimeError("upstream hiccup")
            return {
                "answered": AnsweredQuestion(
                    question=state["question"], answer="ok", confidence=0.9, needs_review=False
                )
            }

    monkeypatch.setattr(nodes, "extract", fake_extract)
    monkeypatch.setattr(workflow, "question_graph", lambda: _Graph())
    monkeypatch.setattr(service, "extracted_document_text", lambda path: _text_stub())

    async def _text_stub():
        return "irrelevant"

    workflow.assessment_graph.cache_clear()
    result = await service.answer_assessment("assessment.pdf", run_id="progress-run")
    workflow.assessment_graph.cache_clear()

    state = progress.snapshot("progress-run")
    assert state["total"] == 3
    assert state["completed"] == 3, "a failed question must still be counted"
    assert state["remaining"] == 0
    assert state["percent"] == 100
    assert state["stage"] == "done"
    assert len(result.answers) == 3
