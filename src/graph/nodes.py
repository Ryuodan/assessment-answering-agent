"""Graph nodes.

Plain async functions rather than a class: none of them hold state between
calls, and the graph already supplies the only argument they need.
"""

from __future__ import annotations

import asyncio
import logging

from src.config import settings
from src.extraction import extract_questions
from src.graph.state import AssessmentState, QuestionState
from src.llm import structured_llm
from src.models import (
    AnsweredQuestion,
    AnswerReview,
    DraftedAnswer,
    Evidence,
    SourceType,
)
from src.prompts import (
    ANSWER_SYSTEM,
    ANSWER_USER,
    LANGUAGE_NAMES,
    REVIEW_SYSTEM,
    REVIEW_USER,
    format_question_block,
    format_sources_block,
)

logger = logging.getLogger(__name__)


def _question_block(state: QuestionState) -> str:
    question = state["question"]
    return format_question_block(
        text=question.text,
        section=question.section,
        question_type=question.question_type.value,
        options=question.options,
    )


def _sources_block(evidence: list[Evidence]) -> str:
    return format_sources_block([(e.source_type.value, e.source_name, e.snippet) for e in evidence])


# ---------------------------------------------------------------------------
# Outer graph
# ---------------------------------------------------------------------------


async def extract(state: AssessmentState) -> dict:
    """Pull the questions out of the submitted document.

    Note this reports the detected language separately and never touches
    `language` — see `AssessmentState.language`.
    """
    language, questions = await extract_questions(state["document_text"])
    return {"questions": questions, "document_language": language}


# ---------------------------------------------------------------------------
# Inner graph
# ---------------------------------------------------------------------------


async def retrieve(state: QuestionState) -> dict:
    """Fetch prior answers and guidelines relevant to the current search query.

    Both collections are queried concurrently, and prior answers are placed
    first: they are the strongest signal for how this organisation words its
    response, and the drafting prompt reads sources in order.
    """
    from src.knowledge import get_store

    store = get_store()
    query = state["search_query"]

    prior_answers, guidelines = await asyncio.gather(
        store.search(query, SourceType.PRIOR_ANSWER, settings.top_k_prior_answers),
        store.search(query, SourceType.GUIDELINE, settings.top_k_guidelines),
    )

    attempt = state.get("attempt", 0) + 1
    logger.debug("Question %s attempt %d: %d prior, %d guideline hits",
                 state["question"].id, attempt, len(prior_answers), len(guidelines))
    return {"evidence": prior_answers + guidelines, "attempt": attempt}


async def draft(state: QuestionState) -> dict:
    """Write the answer from the retrieved evidence."""
    language_name = LANGUAGE_NAMES[state["language"]]
    messages = [
        ("system", ANSWER_SYSTEM.format(language_name=language_name)),
        (
            "user",
            ANSWER_USER.format(
                question_block=_question_block(state),
                sources_block=_sources_block(state.get("evidence", [])),
                language_name=language_name,
            ),
        ),
    ]
    # A little warmth here produces better prose than temperature 0, which tends
    # to parrot a retrieved chunk verbatim even when the question differs.
    drafted = await structured_llm(DraftedAnswer, temperature=0.2).ainvoke(messages)
    return {"draft": drafted}


async def review(state: QuestionState) -> dict:
    """Check the draft is grounded, and propose a better query when it is not."""
    messages = [
        ("system", REVIEW_SYSTEM.format(language_name=LANGUAGE_NAMES[state["language"]])),
        (
            "user",
            REVIEW_USER.format(
                question_block=_question_block(state),
                answer=state["draft"].answer,
                sources_block=_sources_block(state.get("evidence", [])),
            ),
        ),
    ]
    verdict = await structured_llm(AnswerReview, temperature=0.0).ainvoke(messages)

    update: dict = {"review": verdict}
    if not verdict.grounded and verdict.refined_query.strip():
        update["search_query"] = verdict.refined_query.strip()
    return update


async def finalize(state: QuestionState) -> dict:
    """Assemble the answer the user sees, with only the evidence that was used."""
    question = state["question"]
    drafted: DraftedAnswer = state["draft"]
    verdict: AnswerReview = state["review"]

    # Keep only the chunks the drafter actually cited. Sources are cited by their
    # [n] position, not by file name, because one uploaded file contributes many
    # chunks and name-matching would keep all of them every time.
    retrieved = state.get("evidence", [])
    cited = [retrieved[n - 1] for n in dict.fromkeys(drafted.used_source_ids) if 1 <= n <= len(retrieved)]

    # Two independent confidence estimates; trust the lower one.
    confidence = min(drafted.confidence, verdict.confidence)

    answered = AnsweredQuestion(
        question=question,
        answer=drafted.answer.strip(),
        rationale=(drafted.rationale or verdict.verdict_reason).strip(),
        confidence=confidence,
        needs_review=not verdict.grounded or confidence < settings.review_confidence_threshold,
        evidence=cited,
        attempts=state.get("attempt", 1),
    )
    return {"answered": answered}


def route_after_review(state: QuestionState) -> str:
    """Retry retrieval with a better query, or accept the answer.

    Three ways to stop: the answer is grounded, the attempt budget is spent, or
    the reviewer says no rewording would help. Without the budget check an
    ungrounded question could loop against Groq indefinitely.
    """
    verdict: AnswerReview = state["review"]

    if verdict.grounded:
        return "finalize"
    if state.get("attempt", 1) >= settings.max_answer_attempts:
        logger.info("Question %s: accepting ungrounded answer after %d attempts",
                    state["question"].id, state.get("attempt", 1))
        return "finalize"
    if not verdict.refined_query.strip():
        return "finalize"

    logger.debug("Question %s: retrying with refined query", state["question"].id)
    return "retrieve"
