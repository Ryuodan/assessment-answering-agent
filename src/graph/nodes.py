"""Graph nodes.

Plain async functions rather than a class: none of them hold state between
calls, and the graph already supplies the only argument they need.
"""

from __future__ import annotations

import asyncio
import logging
import re

from src.config import settings
from src.extraction import extract_questions
from src.graph.state import AssessmentState, QuestionState
from src.llm import chat_llm, structured_llm
from src.rerank import rerank
from src.verification import assess
from src.models import (
    AnsweredQuestion,
    AnswerReview,
    DraftedAnswer,
    Evidence,
    QueryPlan,
    SourceType,
)
from src.prompts import (
    ANSWER_SYSTEM,
    ANSWER_USER,
    LANGUAGE_NAMES,
    QUERY_PLAN_SYSTEM,
    QUERY_PLAN_USER,
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


def _sources(state: QuestionState) -> list[Evidence]:
    """The evidence the drafter and reviewer both read, in one order.

    Both must see the same numbered list: the drafter cites sources by their
    [n] position and `finalize` resolves those positions, so a reviewer reading
    a differently ordered block would be checking different sources.
    """
    ranked = state.get("ranked")
    if ranked:
        return ranked[: settings.max_evidence_chunks]
    return state.get("evidence", [])[: settings.max_evidence_chunks]


def _sources_block(evidence: list[Evidence]) -> str:
    return format_sources_block(evidence)


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


def _parse_queries(content) -> list[str]:
    """Pull search queries out of a plain-text plan, one per line.

    Tolerant of the shapes a model reaches for unprompted: numbered lists,
    bullets, quotes, and a reasoning model's `<think>` preamble.
    """
    if isinstance(content, list):  # some providers return content blocks
        content = " ".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)

    text = re.sub(r"<think>.*?</think>", " ", str(content), flags=re.DOTALL | re.IGNORECASE)

    queries = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip().strip('"“”')
        # A plan is a list of short search strings; anything long is commentary.
        if 3 <= len(line) <= 160 and not line.endswith(":"):
            queries.append(line)
    return queries


async def plan(state: QuestionState) -> dict:
    """Widen one question into the several searches it actually needs.

    A question that asks two things — "how quickly is access revoked, and how
    are we notified" — embeds as a blend of both and ranks the clause for
    neither first. Splitting it up front is what separates the two retrievals.

    Failure here is not fatal: the question's own text is always searched, so a
    bad or missing plan degrades to the previous single-query behaviour.
    """
    question = state["question"]
    queries = [question.text]

    if settings.query_expansion:
        try:
            # Plain text, one query per line, rather than a structured call.
            # The output is a list of short strings, which needs no schema, and
            # asking for one through tool-calling made this the most fragile
            # step in the graph: gpt-oss-120b returns the queries as prose and
            # the provider rejects the turn with `tool_use_failed`, silently
            # costing query expansion on the questions it happens to.
            response = await chat_llm(temperature=0.0).ainvoke(
                [
                    ("system", QUERY_PLAN_SYSTEM),
                    ("user", QUERY_PLAN_USER.format(question_block=_question_block(state))),
                ]
            )
            queries.extend(_parse_queries(response.content))
        except Exception:  # noqa: BLE001 - retrieval must survive a bad plan
            logger.exception("Query planning failed for question %s; using the question alone", question.id)

    # Order-preserving de-duplication, capped: past a handful of queries the
    # extra searches return what the earlier ones already found.
    unique = list(dict.fromkeys(queries))[: settings.max_search_queries]
    logger.debug("Question %s: searching %d queries", question.id, len(unique))
    return {"search_queries": unique}


async def retrieve(state: QuestionState) -> dict:
    """Fetch prior answers and guidelines for every query in the current round.

    All searches run concurrently, and prior answers are placed first: they are
    the strongest signal for how this organisation words its response, and the
    drafting prompt reads sources in order. The merge is left to the state
    reducer, which already de-duplicates by chunk and keeps the best score.
    """
    from src.knowledge import get_store

    store = get_store()
    queries = state.get("search_queries") or [state["question"].text]

    searches = [
        store.search(query, source_type, k)
        for query in queries
        for source_type, k in (
            (SourceType.PRIOR_ANSWER, settings.top_k_prior_answers),
            (SourceType.GUIDELINE, settings.top_k_guidelines),
        )
    ]
    results = await asyncio.gather(*searches)

    prior_answers = [item for batch in results[0::2] for item in batch]
    guidelines = [item for batch in results[1::2] for item in batch]

    attempt = state.get("attempt", 0) + 1
    logger.debug(
        "Question %s attempt %d: %d queries, %d prior, %d guideline hits",
        state["question"].id, attempt, len(queries), len(prior_answers), len(guidelines),
    )
    return {"evidence": prior_answers + guidelines, "attempt": attempt}


async def rerank_evidence(state: QuestionState) -> dict:
    """Put the accumulated evidence in cross-encoder order.

    A no-op when reranking is off, so the node can stay wired into the graph
    unconditionally and the setting is the only thing that changes.
    """
    evidence = state.get("evidence", [])
    if not settings.reranker_enabled or not evidence:
        return {"ranked": list(evidence)}

    # Ranked against the question as asked, not the expanded search queries:
    # the queries were written to find material, the question is what the
    # answer has to satisfy.
    ranked = await asyncio.to_thread(rerank, state["question"].text, evidence)
    logger.debug("Question %s: reranked %d chunks", state["question"].id, len(evidence))
    return {"ranked": ranked}


async def draft(state: QuestionState) -> dict:
    """Write the answer from the retrieved evidence."""
    language_name = LANGUAGE_NAMES[state["language"]]
    messages = [
        ("system", ANSWER_SYSTEM.format(language_name=language_name)),
        (
            "user",
            ANSWER_USER.format(
                question_block=_question_block(state),
                sources_block=_sources_block(_sources(state)),
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
                sources_block=_sources_block(_sources(state)),
            ),
        ),
    ]
    verdict = await structured_llm(AnswerReview, temperature=0.0).ainvoke(messages)

    update: dict = {"review": verdict}
    if not verdict.grounded and verdict.refined_query.strip():
        update["search_queries"] = [verdict.refined_query.strip()]
    return update


async def finalize(state: QuestionState) -> dict:
    """Assemble the answer the user sees, with only the evidence that was used."""
    question = state["question"]
    drafted: DraftedAnswer = state["draft"]
    verdict: AnswerReview = state["review"]

    # Keep only the chunks the drafter actually cited. Sources are cited by their
    # [n] position, not by file name, because one uploaded file contributes many
    # chunks and name-matching would keep all of them every time.
    shown = _sources(state)
    cited = [shown[n - 1] for n in dict.fromkeys(drafted.used_source_ids) if 1 <= n <= len(shown)]

    # Clause-level locators for the sources that survived. Order-preserving and
    # de-duplicated, because several chunks of one clause collapse to one citation.
    citations = list(dict.fromkeys(item.locator for item in cited))

    confidence, needs_review, review_reasons = assess(
        drafted.answer,
        cited,
        min(drafted.confidence, verdict.confidence),
        retrieved=state.get("evidence", []),
        grounded=verdict.grounded,
        review_threshold=settings.review_confidence_threshold,
        incomplete_cap=settings.incomplete_list_confidence_cap,
    )

    answered = AnsweredQuestion(
        question=question,
        answer=drafted.answer.strip(),
        rationale=(drafted.rationale or verdict.verdict_reason).strip(),
        confidence=confidence,
        needs_review=needs_review,
        review_reasons=review_reasons,
        evidence=cited,
        citations=citations,
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
