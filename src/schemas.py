"""What a structured model call is asked to produce.

Deliberately flat and small: Groq's tool-calling structured output degrades on
deep nesting. Moved from `src/models.py` (plan 023), which keeps the domain
models -- what the system stores and returns.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.models import Language, QuestionType

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
    contradicts_memory: str = Field(
        default="",
        description=(
            "Set only when a PREVIOUS ANSWER disagrees with OUR POLICY on this question: "
            "one sentence saying what each says. Empty otherwise. Never put this in `answer`."
        ),
    )
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


class SameQuestions(BaseModel):
    """Which of several remembered questions ask the same thing as a new one.

    A list of numbers rather than a verdict per pair: the candidates are a
    handful of near neighbours from one search, and asking about them together
    costs one call instead of five and lets the model see them side by side,
    which is how the difference between "the same question reworded" and "the
    next control along" actually shows up.
    """

    same: list[int] = Field(
        default_factory=list,
        description="Numbers of the candidates that ask for the same thing; empty when none do",
    )
    because: str = Field(default="", description="One short sentence on the closest call")


class RelevanceVerdict(BaseModel):
    """Whether one retrieved excerpt is worth showing the drafter."""

    id: int = Field(description="The excerpt's number, exactly as given")
    relevant: bool = Field(description="True when it would help answer the question")


class RelevanceVerdicts(BaseModel):
    """Verdicts for one batch of excerpts."""

    verdicts: list[RelevanceVerdict] = Field(default_factory=list)
