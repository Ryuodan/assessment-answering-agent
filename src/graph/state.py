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
    Evidence,
    Language,
    Question,
)


class QuestionState(TypedDict, total=False):
    """State of the inner graph: retrieve -> draft -> review -> finalize."""

    question: Question
    language: Language
    """Language the answer must be written in — may differ from the question's own."""

    search_query: str
    """Current retrieval query. Starts as the question text; the reviewer may refine it."""

    attempt: int
    """Retrieval rounds completed. Bounded by settings.max_answer_attempts."""

    evidence: list[Evidence]
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
