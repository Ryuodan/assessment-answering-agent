"""Graph state schemas.

Two schemas, because there are two graphs: an inner one that answers a single
question and an outer one that fans out over every question in a document.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from src.config import settings
from src.models import (
    AnsweredQuestion,
    AnswerReview,
    DraftedAnswer,
    Language,
    Question,
    Evidence, 
    SourceType
)



def merge_evidence(left: list[Evidence], right: list[Evidence]) -> list[Evidence]:
    """Union of two retrieval rounds, de-duplicated, best score wins.

    Retrieval rounds are additive rather than replacing: a refined query is meant
    to find material the first query missed, not to discard what it found.
    """
    merged: list[Evidence] = list(left or [])
    index = {(item.source_name, item.chunk): position for position, item in enumerate(merged)}

    for item in right or []:
        key = (item.source_name, item.chunk)
        position = index.get(key)
        if position is None:
            index[key] = len(merged)
            merged.append(item)
            continue

        # Agreement accumulates across rounds as well as within one: a chunk
        # two queries found in round one and the reviewer's refined query
        # found again in round two has been arrived at three separate ways.
        # Carried before any replacement, or a better-scoring copy would drop
        # the history that made it interesting.
        hits = merged[position].query_hits + item.query_hits
        if item.score > merged[position].score:
            merged[position] = item
        merged[position].query_hits = hits

    return order_evidence(merged)


def agreement_bonus(query_hits: int) -> float:
    """How much to lift a chunk that several independent searches agreed on.

    Query expansion issues one search per thing the question asks, plus an
    Arabic phrasing of the key concept, and those searches are meant to
    converge. When three of four return the same clause, that convergence is
    evidence about the clause rather than about any one phrasing of the query
    — and unlike a cross-encoder it costs nothing, because the searches have
    already run.

    Applied as a proportional lift rather than a fixed addition, so it can
    reorder chunks that are already close without letting a widely-agreed but
    weakly-matching chunk overtake a strong one. `QUERY_AGREEMENT_WEIGHT=0`
    turns it off; with query expansion off every chunk has one hit and the
    multiplier is 1 regardless.
    """
    return 1.0 + settings.query_agreement_weight * max(query_hits - 1, 0)


def order_evidence(evidence: list[Evidence]) -> list[Evidence]:
    """Prior answers first, then by unit, contiguous within a unit.

    Units are ranked by their best-scoring member so a series is not scattered
    through the prompt; parts stay in document order so the drafter reads
    7.2.1 before 7.2.2.
    """
    best: dict[tuple, float] = {}
    for item in evidence:
        group = (item.source_name, item.unit_id or f"chunk-{item.chunk}")
        # Seeded from the item rather than from 0.0: a genuinely poor match can
        # score below zero on some metrics, and a floor of zero would collapse
        # every such group into a tie broken by file name.
        weighted = item.score * agreement_bonus(item.query_hits)
        best[group] = max(best[group], weighted) if group in best else weighted

    def sort_key(item: Evidence):
        group = (item.source_name, item.unit_id or f"chunk-{item.chunk}")
        return (
            item.source_type is not SourceType.PRIOR_ANSWER,
            -best[group],
            item.source_name,
            item.part,
            item.chunk,
        )

    return sorted(evidence, key=sort_key)


def prune_weak_units(
    evidence: list[Evidence], floor: float, minimum: int
) -> list[Evidence]:
    """Drop material scoring far below the best hit for this question.

    A fixed evidence budget spends the same forty chunks on "what is your
    retention period" as on a six-part synthesis, and the surplus is not
    harmless: measured on this corpus only 16% of the chunks reaching the
    drafter sit on a clause the question asked about, and raising the budget
    from 38 to 48 improved recall while making answers worse. A relative floor
    lets the question decide how much it needs.

    Two details matter. The comparison uses the agreement-weighted score, so a
    clause that several independent searches converged on survives a floor its
    raw cosine would not. And a whole *unit* is kept or dropped together: parts
    of one numbered series are retrieved as a set precisely so the drafter
    never sees three items of nine and calls it the list, and pruning by chunk
    would undo that.

    Prior answers are exempt. They are capped separately by
    `max_prior_answer_chunks` and scored on a different scale, so letting them
    set or fail the bar would compare unlike things.
    """
    if floor <= 0.0 or not evidence:
        return evidence

    def group_of(item: Evidence) -> tuple:
        return (item.source_name, item.unit_id or f"chunk-{item.chunk}")

    guidelines = [item for item in evidence if item.source_type is not SourceType.PRIOR_ANSWER]
    if not guidelines:
        return evidence

    # Compared on raw similarity, not the agreement-weighted score used for
    # ordering. Cosines on policy prose span only about 1.5x end to end, and the
    # agreement multiplier spans 1.75x, so weighting the comparison let the
    # number of query phrasings that found a chunk decide whether it cleared a
    # *similarity* bar: at floor 0.80 that cost 21.7 points of document recall
    # to buy 9 of precision.
    best_in_group: dict[tuple, float] = {}
    hits_in_group: dict[tuple, int] = {}
    for item in guidelines:
        group = group_of(item)
        best_in_group[group] = max(best_in_group.get(group, item.score), item.score)
        hits_in_group[group] = max(hits_in_group.get(group, 0), item.query_hits)

    best = max(best_in_group.values())
    if best <= 0:
        return evidence

    # Agreement rescues rather than scores: a unit that most of the question's
    # searches independently converged on is kept even below the bar, which is
    # what the signal is actually evidence of.
    rescue = max(hits_in_group.values())
    keep = {
        group for group, score in best_in_group.items()
        if score >= floor * best or (rescue > 1 and hits_in_group[group] >= rescue)
    }
    kept = [
        item for item in evidence
        if item.source_type is SourceType.PRIOR_ANSWER or group_of(item) in keep
    ]

    # A weak best hit would otherwise leave almost nothing. Restore the highest
    # scoring units, whole, until the floor on count is met.
    if sum(1 for item in kept if item.source_type is not SourceType.PRIOR_ANSWER) < minimum:
        for group, _ in sorted(best_in_group.items(), key=lambda row: -row[1]):
            if group in keep:
                continue
            keep.add(group)
            kept = [
                item for item in evidence
                if item.source_type is SourceType.PRIOR_ANSWER or group_of(item) in keep
            ]
            if sum(1 for i in kept if i.source_type is not SourceType.PRIOR_ANSWER) >= minimum:
                break

    return kept


def select_evidence(evidence: list[Evidence], limit: int, prior_cap: int) -> list[Evidence]:
    """The chunks that fit in the drafting prompt: the best of each kind.

    Ordering and selection were the same operation, and that was a bug. Prior
    answers sort ahead of guidelines because the drafter should read them
    first — they carry the organisation's own wording. But the prompt is then
    filled from the top of that same list, so a prior answer scoring 0.20
    displaced a policy clause scoring 0.60, and enough of them displaced every
    policy clause there was.

    Observed on the client-data retention question: 12 prior answers and 2
    guidelines reached the first draft, and when the reviewer asked for another
    retrieval round three more prior answers arrived and pushed the guideline
    count to zero. The clause stating the 60-day return and 90-day deletion had
    been retrieved — it was sitting at rank 13 of 30 — and the drafter never saw
    it, so the answer became "the documentation does not state a period". The
    same question answered correctly whenever no retry happened, which is what
    made it look like run-to-run randomness.

    So prior answers keep their place at the front and lose their claim on the
    whole budget. Whatever they do not use goes to guidelines, and vice versa:
    a question with no useful policy material still fills up with prior answers.
    """
    if limit <= 0:
        return []

    evidence = prune_weak_units(
        evidence, settings.evidence_score_floor, settings.min_evidence_chunks
    )

    def is_prior(item: Evidence) -> bool:
        return item.source_type is SourceType.PRIOR_ANSWER

    prior_positions = [index for index, item in enumerate(evidence) if is_prior(item)]
    ranked_positions = sorted(prior_positions, key=lambda index: -evidence[index].score)
    keep = set(ranked_positions[: max(prior_cap, 0)])
    spare = ranked_positions[max(prior_cap, 0):]

    selected = [
        index for index, item in enumerate(evidence)
        if not is_prior(item) or index in keep
    ][:limit]

    # Guidelines ran out before the budget did — give the room back.
    if len(selected) < limit and spare:
        selected = sorted(selected + spare[: limit - len(selected)])

    return [evidence[index] for index in selected]


class QuestionState(TypedDict, total=False):
    """State of the inner graph: retrieve -> draft -> review -> finalize."""

    question: Question

    language: Language
    """Language the answer must be written in — may differ from the question's own."""

    run_id: str
    """Which run this question belongs to, so progress can be reported."""

    search_queries: list[str]
    """Queries for the current retrieval round.

    Starts as the question text alone, is widened by the `plan` node when query
    expansion is on, and is replaced wholesale by the reviewer's refined query
    on a retry. Replaced rather than appended because evidence accumulates
    across rounds anyway — see `merge_evidence` — so a retry should spend its
    searches on the angle that was missed, not repeat the ones that failed.
    """

    attempt: int
    """Retrieval rounds completed. Bounded by settings.max_answer_attempts."""

    evidence: Annotated[list[Evidence], merge_evidence]

    ranked: list[Evidence]
    """Evidence in the order the drafter should read it, best first.

    Written by the rerank node and replaced outright on each retrieval round,
    unlike `evidence`, which accumulates. Kept separate so reranking never has
    to fight the accumulating reducer for control of the ordering.
    """

    draft: DraftedAnswer | None
    review: AnswerReview | None
    answered: AnsweredQuestion | None


class AssessmentState(TypedDict, total=False):
    """State of the outer graph: extract -> fan out over questions -> collect."""

    source_name: str
    document_text: str

    run_id: str
    """Identifier the caller can poll for progress while the run is in flight."""


    language: Language | None
    """Caller's forced output language. None means each answer follows its own question.

    Deliberately never written by a node — only the caller sets it. `extract`
    reports what it detected in `document_language` instead, because overwriting
    this field would silently turn detection into a global override and answer
    every Arabic question in the document's dominant language.
    """

    document_language: Language | None
    """Dominant language detected in the submitted document. Reporting only."""

    questions: list[Question]

    answers: Annotated[list[AnsweredQuestion], operator.add]
    """Appended to concurrently by the fanned-out question runs, hence the reducer."""
