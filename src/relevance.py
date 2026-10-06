"""LLM relevance grading of retrieved chunks.

Why this exists rather than another threshold on the similarity score: on this
corpus cosine cannot separate on-target material from noise. Retrieved chunks
score between 0.51 and 0.77 — a span of 1.5x end to end — and only 17% of what
reaches the drafter sits on a clause the question asked about. Even the five
best-ranked chunks are barely a third on target. Three different ways of cutting
by that score (a relative floor, a smaller evidence budget, a smaller per-query
`top_k`) each cost two to four points of recall for every point of precision.

An embedding compares two vectors that were computed without ever seeing each
other. A grader reads the question and the excerpt together, which is the
interaction the embedding discarded, and it is the only signal available here
that is not derived from the same cosine.

Two decisions keep it safe:

* **A floor that cannot be graded away.** The top `RELEVANCE_FILTER_KEEP`
  chunks by retrieval rank survive whatever the grader says, so a false
  negative on the one chunk carrying the answer cannot strip it. Below that
  floor an off-target verdict really does remove the chunk — demoting it
  instead was measured to do nothing at all, because the evidence budget is
  rarely the binding constraint and re-ordering a list that is not being cut
  changes nothing.
* **Fail open.** A grading error returns the evidence untouched. The filter is
  an improvement to ordering, not a dependency of answering.
"""

from __future__ import annotations

import asyncio
import logging

from src.config import settings
from src.llm import structured_llm
from src.models import Evidence
from src.schemas import RelevanceVerdicts
from src.prompts import RELEVANCE_SYSTEM, RELEVANCE_USER

logger = logging.getLogger(__name__)


def _batches(evidence: list[Evidence], size: int) -> list[list[tuple[int, Evidence]]]:
    numbered = list(enumerate(evidence))
    return [numbered[start : start + size] for start in range(0, len(numbered), size)]


def _excerpt(index: int, item: Evidence, limit: int) -> str:
    snippet = " ".join(item.snippet.split())[:limit]
    return f"[{index}] {item.locator}\n{snippet}"


async def _grade_batch(question: str, batch: list[tuple[int, Evidence]]) -> dict[int, bool]:
    """Verdicts for one batch, keyed by the caller's index."""
    excerpts = "\n\n".join(_excerpt(index, item, settings.relevance_filter_snippet) for index, item in batch)
    model = settings.relevance_filter_model or None
    chain = structured_llm(RelevanceVerdicts, temperature=0.0, model=model)
    result = await chain.ainvoke(
        [
            ("system", RELEVANCE_SYSTEM),
            ("human", RELEVANCE_USER.format(question=question, excerpts=excerpts)),
        ]
    )
    return {v.id: v.relevant for v in result.verdicts}


async def filter_evidence(question: str, evidence: list[Evidence]) -> list[Evidence]:
    """Drop chunks the grader judges off-topic, below a protected floor.

    Retrieval order is preserved among the survivors, so the ranking still
    decides between chunks the grader agreed about and the parts of one split
    unit stay in document order.
    """
    if not settings.relevance_filter_enabled or len(evidence) <= settings.relevance_filter_keep:
        return evidence

    batches = _batches(evidence, settings.relevance_filter_batch)
    try:
        results = await asyncio.gather(*(_grade_batch(question, batch) for batch in batches))
    except Exception:  # noqa: BLE001 - ordering is an improvement, not a dependency
        logger.warning("Relevance grading failed; keeping retrieval order", exc_info=True)
        return evidence

    verdicts: dict[int, bool] = {}
    for chunk in results:
        verdicts.update(chunk)

    # A unit is judged as a whole: parts of one numbered series are retrieved
    # together so the drafter never sees three items of nine and calls it the
    # list, and demoting the parts the grader happened to dislike would undo
    # that. One relevant part vouches for the unit.
    def unit_of(item: Evidence) -> tuple:
        return (item.source_name, item.unit_id or f"chunk-{item.chunk}")

    relevant_units = {unit_of(item) for index, item in enumerate(evidence) if verdicts.get(index, True)}

    # Ungraded chunks keep their place rather than being demoted: a verdict the
    # model omitted is missing information, not a negative one.
    keep = settings.relevance_filter_keep

    def survives(index: int, item: Evidence) -> bool:
        return index < keep or unit_of(item) in relevant_units

    kept = [item for index, item in enumerate(evidence) if survives(index, item)]
    dropped = [item for index, item in enumerate(evidence) if not survives(index, item)]

    # Promotion, not just deletion. Relevant units rise to the front in their
    # retrieval order; protected-but-off-target chunks fall in behind them.
    # Sorting on the unit's verdict keeps a split series contiguous, because
    # every part of a unit carries the same verdict.
    if settings.relevance_filter_promote:
        order = {id(item): index for index, item in enumerate(kept)}
        kept.sort(key=lambda item: (unit_of(item) not in relevant_units, order[id(item)]))

    # Never return less than the floor, even if every verdict was negative and
    # the floor is larger than the list.
    if len(kept) < min(keep, len(evidence)):
        kept = evidence[: min(keep, len(evidence))]

    logger.debug(
        "Relevance filter: dropped %d of %d chunks in %d call(s)",
        len(dropped),
        len(evidence),
        len(batches),
    )
    return kept
