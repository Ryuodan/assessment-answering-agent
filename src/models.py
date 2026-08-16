"""Domain models shared by ingestion, retrieval, the graph and the API.

Two families live here:

* *Domain* models (`Question`, `AnsweredQuestion`, `AssessmentResult`) — what the
  system stores and returns.
* *LLM output* schemas (`ExtractedQuestions`, `DraftedAnswer`, `AnswerReview`) —
  what a structured Groq call is asked to produce. They are deliberately flat and
  small: Groq's tool-calling structured output degrades on deep nesting.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

Language = Literal["ar", "en"]


class SourceType(str, Enum):
    """Which knowledge collection a chunk belongs to."""

    GUIDELINE = "guideline"
    PRIOR_ANSWER = "prior_answer"


class QuestionType(str, Enum):
    FREE_TEXT = "free_text"
    YES_NO = "yes_no"
    SINGLE_CHOICE = "single_choice"
    MULTI_CHOICE = "multi_choice"


# ---------------------------------------------------------------------------
# Domain
# ---------------------------------------------------------------------------


class Question(BaseModel):
    """One question lifted out of an assessment document."""

    id: str = Field(description="Stable identifier, e.g. 'q1' or the number printed on the form")
    text: str
    section: str | None = Field(default=None, description="Heading the question sits under, if any")
    question_type: QuestionType = QuestionType.FREE_TEXT
    options: list[str] = Field(default_factory=list, description="Allowed choices for choice questions")
    language: Language = "en"


class Evidence(BaseModel):
    """A retrieved chunk that supported (or could support) an answer."""

    source_type: SourceType
    source_name: str
    snippet: str
    score: float = 0.0


class AnsweredQuestion(BaseModel):
    """A question plus the agent's answer and its supporting evidence."""

    question: Question
    answer: str
    rationale: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    needs_review: bool = True
    evidence: list[Evidence] = Field(default_factory=list)
    attempts: int = 1


class AssessmentResult(BaseModel):
    """Everything produced by one run over a submitted assessment."""

    run_id: str
    source_name: str
    language: Language
    questions_found: int
    answers: list[AnsweredQuestion] = Field(default_factory=list)

    @property
    def needs_review_count(self) -> int:
        return sum(1 for a in self.answers if a.needs_review)


class IngestResult(BaseModel):
    """Summary of ingesting one uploaded file into the knowledge base."""

    source_name: str
    source_type: SourceType
    chunks_indexed: int
    qa_pairs_found: int = 0
    error: str | None = None


# ---------------------------------------------------------------------------
# Structured LLM outputs
# ---------------------------------------------------------------------------


class ExtractedQuestion(BaseModel):
    """A question as the extraction model reports it."""

    number: str = Field(description="Question number or label as printed in the document; '' if unnumbered")
    text: str = Field(description="The question, verbatim, in its original language")
    section: str = Field(default="", description="Section or heading it belongs to; '' if none")
    question_type: QuestionType = QuestionType.FREE_TEXT
    options: list[str] = Field(default_factory=list)


class ExtractedQuestions(BaseModel):
    """Result of scanning one window of an assessment document."""

    language: Language = Field(default="en", description="Dominant language of this window")
    questions: list[ExtractedQuestion] = Field(default_factory=list)


class ExtractedQAPair(BaseModel):
    """A question/answer pair recovered from a previously answered assessment."""

    question: str
    answer: str
    section: str = ""


class ExtractedQAPairs(BaseModel):
    pairs: list[ExtractedQAPair] = Field(default_factory=list)


class DraftedAnswer(BaseModel):
    """The model's proposed answer to a single question."""

    answer: str = Field(description="The answer to write into the assessment, in the required language")
    rationale: str = Field(default="", description="Short note on which sources were used and why")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    used_source_ids: list[int] = Field(
        default_factory=list,
        description="The [n] numbers of the sources that actually support the answer",
    )


class AnswerReview(BaseModel):
    """Verdict from the grounding review pass."""

    grounded: bool = Field(description="True when every claim in the answer is supported by the provided sources")
    verdict_reason: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    refined_query: str = Field(
        default="",
        description="A better search query to retry with when the answer is not grounded; '' to accept as is",
    )
