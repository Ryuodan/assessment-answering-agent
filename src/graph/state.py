"""Graph state schemas.

Two schemas, because there are two graphs: an inner one that answers a single
question and an outer one that fans out over every question in a document.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

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
        elif item.score > merged[position].score:
            merged[position] = item

    return order_evidence(merged)


def order_evidence(evidence: list[Evidence]) -> list[Evidence]:
    """Prior answers first, then by unit, contiguous within a unit.

    Units are ranked by their best-scoring member so a series is not scattered
    through the prompt; parts stay in document order so the drafter reads
    7.2.1 before 7.2.2.
    """
    best: dict[tuple, float] = {}
    for item in evidence:
        group = (item.source_name, item.unit_id or f"chunk-{item.chunk}")
        best[group] = max(best.get(group, 0.0), item.score)

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


class QuestionState(TypedDict, total=False):
    """State of the inner graph: retrieve -> draft -> review -> finalize."""

    question: Question
    language: Language
    """Language the answer must be written in — may differ from the question's own."""

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
