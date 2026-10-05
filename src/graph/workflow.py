"""Graph wiring.

    outer:  extract ──fan out (Send per question)──> answer ──> END

    inner:  plan ──> retrieve ──> rerank ──> draft ──> review ──┬─> finalize ──> END
                          ^                                     │
                          └──────────── refined query ──────────┘

The fan-out is `Send`, so questions are answered concurrently; the caller caps
that with `max_concurrency` in the runnable config.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from src import progress
from src.graph import nodes
from src.graph.state import AssessmentState, QuestionState
from src.models import AnsweredQuestion, Language, Question

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def question_graph():
    """Compile the inner graph that answers one question."""
    builder = StateGraph(QuestionState)

    builder.add_node("plan", nodes.plan)
    builder.add_node("retrieve", nodes.retrieve)
    builder.add_node("rerank", nodes.rerank_evidence)
    builder.add_node("draft", nodes.draft)
    builder.add_node("review", nodes.review)
    builder.add_node("finalize", nodes.finalize)

    builder.add_edge(START, "plan")
    builder.add_edge("plan", "retrieve")
    builder.add_edge("retrieve", "rerank")
    builder.add_edge("rerank", "draft")
    builder.add_edge("draft", "review")
    builder.add_conditional_edges("review", nodes.route_after_review, ["retrieve", "finalize"])
    builder.add_edge("finalize", END)

    return builder.compile()


def trace_config(question: Question, language: Language, run_id: str = "") -> dict:
    """Name and label one question's trace so a monitoring project is readable.

    Without this every trace is called "LangGraph" and carries nothing to filter
    on, which makes a project of a few thousand runs useless for the thing it
    exists for: finding the question that went wrong. The tags are the axes
    worth slicing by -- which batch, which language, what kind of question --
    and the question id is carried so a trace can be matched back to the answer
    a reviewer is looking at.

    Only metadata: no answer text or document content is added here beyond what
    the prompts already carry.

    `session_id` is the same value as `run_id` under the name the OpenInference
    convention reserves for it, so a Phoenix collector groups the hundred and
    eighty-three questions of one questionnaire into one session rather than a
    hundred and eighty-three unrelated traces. LangSmith reads `run_id` and
    ignores the other; Phoenix reads `session_id` and ignores the other; both
    are cheap, and neither is a place to be clever.
    """
    tags = [f"lang:{language}", f"type:{question.question_type.value}"]
    if run_id:
        tags.append(f"run:{run_id}")
    metadata = {
        "question_id": question.id,
        "question": question.text[:300],
        "language": language,
        "question_type": question.question_type.value,
        "run_id": run_id or "",
        "section": question.section or "",
    }
    if run_id:
        metadata["session_id"] = run_id
    return {
        "run_name": f"answer[{question.id}]",
        "tags": tags,
        "metadata": metadata,
    }


async def answer_one_question(
    question: Question,
    language: Language,
    *,
    run_id: str = "",
    team_id: str | None = None,
) -> AnsweredQuestion:
    """Answer a single question through the inner graph.

    The outer graph reaches the same place via `Send`; this is the door for a
    caller who already has the question and no document to extract it from.

    `run_id` is carried only so the trace can be tagged with it: without it
    every question in a batch is an unrelated trace, and the first thing anyone
    monitoring a failed run wants is the other questions from the same run.
    Keyword-only and defaulted, so a caller that does not trace need not care.
    """
    result = await question_graph().ainvoke(
        {
            "question": question,
            "language": language,
            "team_id": team_id or "",
            "search_queries": [question.text],
            "attempt": 0,
            "evidence": [],
        },
        config=trace_config(question, language, run_id),
    )
    return result["answered"]


def failed_answer(question: Question, error: BaseException) -> AnsweredQuestion:
    """The placeholder a question that could not be answered comes back as.

    Shared by both entry points, because both need the same containment: one
    question tripping over a bad response must never cost the caller the rest
    of the batch.
    """
    return AnsweredQuestion(
        question=question,
        answer="",
        rationale=f"Answering failed: {error}",
        confidence=0.0,
        needs_review=True,
        error=str(error) or error.__class__.__name__,
    )


async def _answer_question(state: QuestionState) -> dict:
    """Outer-graph node: run the inner graph and contribute one answer.

    A failure here is contained. One question that keeps tripping over a bad
    Groq response should not cost the user the other thirty-nine answers, so it
    comes back flagged for review with the error in its rationale.
    """
    question = state["question"]
    # Built before the try, and from `.get`: `language` is optional on
    # QuestionState, and reading it as a required key raised a KeyError that
    # the except below then reported *instead of* the failure it was meant to
    # contain -- an answer whose error read "'language'" rather than whatever
    # Groq actually said.
    config = trace_config(question, state.get("language", "en"), state.get("run_id", ""))
    try:
        result = await question_graph().ainvoke(state, config=config)
        return {"answers": [result["answered"]]}
    except Exception as exc:  # noqa: BLE001 - deliberately contained per question
        logger.exception("Failed to answer question %s", question.id)
        return {"answers": [failed_answer(question, exc)]}
    finally:
        # Counted whether it succeeded or failed: a run that loses one question
        # must still reach the end of its own progress bar.
        progress.advance(state.get("run_id"))


def _fan_out(state: AssessmentState) -> list[Send] | str:
    """Dispatch one inner-graph run per extracted question."""
    questions = state.get("questions") or []
    if not questions:
        logger.warning("No questions extracted from '%s'", state.get("source_name", "document"))
        return END

    progress.set_total(state.get("run_id"), len(questions))

    forced_language = state.get("language")
    return [
        Send(
            "answer",
            {
                "question": question,
                "language": forced_language or question.language,
                "run_id": state.get("run_id", ""),
                "team_id": state.get("team_id", ""),
                "search_queries": [question.text],
                "attempt": 0,
                "evidence": [],
            },
        )
        for question in questions
    ]


@lru_cache(maxsize=1)
def assessment_graph():
    """Compile the outer graph that answers a whole assessment."""
    builder = StateGraph(AssessmentState)

    builder.add_node("extract", nodes.extract)
    builder.add_node("answer", _answer_question)

    builder.add_edge(START, "extract")
    builder.add_conditional_edges("extract", _fan_out, ["answer", END])
    builder.add_edge("answer", END)

    return builder.compile()
