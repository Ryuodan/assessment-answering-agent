"""Graph nodes.

Plain async functions rather than a class: none of them hold state between
calls, and the graph already supplies the only argument they need.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter

from src import organisation
from src.config import settings
from src.extraction import extract_questions
from src.graph import product_scope
from src.graph.state import AssessmentState, QuestionState, select_evidence
from src.llm import chat_llm, structured_llm
from src.rerank import rerank
from src.formatting import strip_source_markers
from src.verification import assess, evidence_for, explain_confidence
from src.models import AnsweredQuestion, Evidence, SourceType
from src.schemas import AnswerReview, DraftedAnswer
from src.relevance import filter_evidence
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
        product=product_scope.about(state)[0],
    )


def _sources(state: QuestionState) -> list[Evidence]:
    """The evidence the drafter and reviewer both read, in one order.

    Both must see the same numbered list: the drafter cites sources by their
    [n] position and `finalize` resolves those positions, so a reviewer reading
    a differently ordered block would be checking different sources.
    """
    available = state.get("ranked") or state.get("evidence", [])
    return select_evidence(
        available,
        limit=settings.max_evidence_chunks,
        prior_cap=settings.max_prior_answer_chunks,
    )


def _sources_block(evidence: list[Evidence], product: str = "") -> str:
    return format_sources_block(evidence, product)


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
    from src.scoped_knowledge import store_for

    # The shared knowledge base, or a product's beside it (plan 023).
    store = store_for(state.get("team_id") or None, state.get("product_id", ""))
    queries = state.get("search_queries") or [state["question"].text]

    # A collection holding nothing still costs a full embedding round trip per
    # query: the query is embedded before the filter is applied, so an empty
    # prior-answers collection was spending five or six remote calls per
    # question to return nothing. Measured at 0.17s each against the same
    # endpoint that is the slowest thing in the pipeline and the one that
    # intermittently times out.
    counts = await asyncio.to_thread(store.counts_by_type)
    wanted = [
        (source_type, k)
        for source_type, k in (
            (SourceType.PRIOR_ANSWER, settings.top_k_prior_answers),
            (SourceType.GUIDELINE, settings.top_k_guidelines),
        )
        if k > 0 and counts.get(source_type.value)
    ]
    # One embedding per query rather than one per (query, source type): both
    # kinds live in the same collection behind a metadata filter, so asking for
    # each separately sent identical text to the embedding service twice.
    found = await asyncio.gather(*(store.search_types(query, wanted) for query in queries))
    results = [batch for per_query in found for batch in per_query.values()]

    # How many of this round's searches independently returned each chunk.
    # The expanded queries are written to overlap — one per thing the question
    # asks, in both languages — so a chunk several of them agree on is a
    # stronger candidate than one a single phrasing happened to surface. The
    # signal is free: it falls out of retrieval that has already run.
    agreement: Counter = Counter()
    for batch in results:
        agreement.update({item.key for item in batch})

    def collapse(batches: list[list[Evidence]]) -> list[Evidence]:
        """One entry per chunk, carrying how many searches returned it.

        A chunk six queries agree on comes back in six batches. Returning all
        six and letting the state reducer merge them counted the agreement once
        per copy: the reducer sums `query_hits`, so six copies each stamped
        with six accumulated to thirty-six. The multiplier that was meant to
        top out at 1.75 reached 6.4, and ranking was decided by how many
        phrasings found a chunk rather than by how well it matched.
        """
        best: dict[tuple, Evidence] = {}
        for batch in batches:
            for item in batch:
                key = item.key
                if key not in best or item.score > best[key].score:
                    best[key] = item
        for key, item in best.items():
            item.query_hits = agreement[key]
        return list(best.values())

    def batches_for(source_type: SourceType) -> list[list[Evidence]]:
        return [per_query[source_type] for per_query in found if source_type in per_query]

    # Split by what each search was for, not by its position: the old
    # `results[0::2]` / `[1::2]` assumed every query produced exactly one search
    # of each kind, which stops being true the moment one is skipped.
    prior_answers = collapse(batches_for(SourceType.PRIOR_ANSWER))
    guidelines = collapse(batches_for(SourceType.GUIDELINE))

    attempt = state.get("attempt", 0) + 1
    logger.debug(
        "Question %s attempt %d: %d queries, %d prior, %d guideline hits, %d chunk(s) found by more than one query",
        state["question"].id,
        attempt,
        len(queries),
        len(prior_answers),
        len(guidelines),
        sum(1 for count in agreement.values() if count > 1),
    )
    return {"evidence": prior_answers + guidelines, "attempt": attempt}


async def rerank_evidence(state: QuestionState) -> dict:
    """Put the accumulated evidence in cross-encoder order.

    A no-op when reranking is off, so the node can stay wired into the graph
    unconditionally and the setting is the only thing that changes.
    """
    evidence = state.get("evidence", [])
    if not evidence:
        return {"ranked": []}

    ranked = list(evidence)
    if settings.reranker_enabled:
        # Ranked against the question as asked, not the expanded search queries:
        # the queries were written to find material, the question is what the
        # answer has to satisfy.
        ranked = await asyncio.to_thread(rerank, state["question"].text, ranked)
        logger.debug("Question %s: reranked %d chunks", state["question"].id, len(evidence))

    # Applied after any cross-encoder pass, so the two compose: the reranker
    # orders by similarity, the grader demotes what is not on topic at all.
    ranked = await filter_evidence(state["question"].text, ranked)
    return {"ranked": ranked}


async def draft(state: QuestionState) -> dict:
    """Write the answer from the retrieved evidence."""
    language_name = LANGUAGE_NAMES[state["language"]]
    # One prompt, always. Wording instructions are honoured by rewriting a
    # finished answer instead -- measured on six questions, that follows the
    # instruction just as well, comes out shorter, and keeps every citation,
    # where drafting briefly from scratch cited a third fewer and dropped a
    # caveat the sources actually required.
    # Who we are, read fresh rather than captured at import: the profile is a
    # file somebody edits, and a correction to it should reach the next answer
    # rather than the next restart.
    profile = organisation.load()
    # A product's questionnaire names its product, and what each source's mark supports (plan 031).
    product, told = product_scope.for_the_drafter(state, profile.short_name)
    messages = [
        (
            "system",
            ANSWER_SYSTEM.format(
                language_name=language_name,
                organisation=profile.describe(),
                addressed_as=organisation.ADDRESSED_AS,
            )
            + told,
        ),
        (
            "user",
            ANSWER_USER.format(
                question_block=_question_block(state),
                sources_block=_sources_block(_sources(state), product),
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
    product, told = product_scope.for_the_reviewer(state)
    messages = [
        ("system", REVIEW_SYSTEM.format(language_name=LANGUAGE_NAMES[state["language"]]) + told),
        (
            "user",
            REVIEW_USER.format(
                question_block=_question_block(state),
                answer=state["draft"].answer,
                sources_block=_sources_block(_sources(state), product),
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
    retrieved = state.get("evidence", [])
    cited = [shown[n - 1] for n in dict.fromkeys(drafted.used_source_ids) if 1 <= n <= len(shown)]
    # Recover the sources the drafter used but did not list; see `evidence_for`.
    cited = evidence_for(drafted.answer, cited, shown or retrieved)

    # Clause-level locators for the sources that survived, in order. Several chunks of one clause are one citation;
    # remembered answers approved on one day share "Answer memory (date)", and each is still its own (plan 027).
    citations = [locator for locator, _ in dict.fromkeys((item.locator, item.entry_id) for item in cited)]

    checked = assess(
        drafted.answer,
        cited,
        min(drafted.confidence, verdict.confidence),
        retrieved=retrieved,
        grounded=verdict.grounded,
        review_threshold=settings.review_confidence_threshold,
        incomplete_cap=settings.incomplete_list_confidence_cap,
        # The retriever never completes a unit past this, so the completeness
        # check must not demand that it did.
        completable_parts=settings.max_expanded_parts,
        # A disagreement only the drafter can see: a flag for the reviewer,
        # never prose in the answer (see `assess`).
        inconsistency=drafted.contradicts_memory,
    )

    answered = AnsweredQuestion(
        question=question,
        answer=strip_source_markers(drafted.answer).strip(),
        rationale=(drafted.rationale or verdict.verdict_reason).strip(),
        confidence=checked.confidence,  # capped when held (plan 030)
        needs_review=checked.needs_review,
        review_reasons=checked.reasons,
        confidence_reason=explain_confidence(
            checked.scored,  # the rating, not the cap: why it is held is in `review_reasons`
            cited,
            grounded=verdict.grounded,
            review_threshold=settings.review_confidence_threshold,
            verdict_reason=verdict.verdict_reason,
        ),
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
        logger.info(
            "Question %s: accepting ungrounded answer after %d attempts", state["question"].id, state.get("attempt", 1)
        )
        return "finalize"
    if not verdict.refined_query.strip():
        return "finalize"

    logger.debug("Question %s: retrying with refined query", state["question"].id)
    return "retrieve"
