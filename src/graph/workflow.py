"""Graph wiring.

    outer:  extract ──fan out (Send per question)──> answer ──> END

    inner:  retrieve ──> draft ──> review ──┬─> finalize ──> END
                 ^                          │
                 └──── refined query ───────┘

The fan-out is `Send`, so questions are answered concurrently; the caller caps
that with `max_concurrency` in the runnable config.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from src.graph import nodes
from src.graph.state import AssessmentState, QuestionState

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def question_graph():
    """Compile the inner graph that answers one question."""
    builder = StateGraph(QuestionState)

    builder.add_node("retrieve", nodes.retrieve)
    builder.add_node("draft", nodes.draft)
    builder.add_node("review", nodes.review)
    builder.add_node("finalize", nodes.finalize)

    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "draft")
    builder.add_edge("draft", "review")
    builder.add_conditional_edges("review", nodes.route_after_review, ["retrieve", "finalize"])
    builder.add_edge("finalize", END)

    return builder.compile()


async def _answer_question(state: QuestionState) -> dict:
    """Outer-graph node: run the inner graph and contribute one answer.

    A failure here is contained. One question that keeps tripping over a bad
    Groq response should not cost the user the other thirty-nine answers, so it
    comes back flagged for review with the error in its rationale.
    """
    question = state["question"]
    try:
        result = await question_graph().ainvoke(state)
        return {"answers": [result["answered"]]}
    except Exception as exc:  # noqa: BLE001 - deliberately contained per question
        logger.exception("Failed to answer question %s", question.id)
        from src.models import AnsweredQuestion

        return {
            "answers": [
                AnsweredQuestion(
                    question=question,
                    answer="",
                    rationale=f"Answering failed: {exc}",
                    confidence=0.0,
                    needs_review=True,
                )
            ]
        }


def _fan_out(state: AssessmentState) -> list[Send] | str:
    """Dispatch one inner-graph run per extracted question."""
    questions = state.get("questions") or []
    if not questions:
        logger.warning("No questions extracted from '%s'", state.get("source_name", "document"))
        return END

    forced_language = state.get("language")
    return [
        Send(
            "answer",
            {
                "question": question,
                "language": forced_language or question.language,
                "search_query": question.text,
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
