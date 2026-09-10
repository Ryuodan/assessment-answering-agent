"""Domain models shared by ingestion, retrieval, the graph and the API.

Two families live here:

* *Domain* models (`Question`, `AnsweredQuestion`, `AssessmentResult`) — what the
  system stores and returns.
* *LLM output* schemas (`ExtractedQuestions`, `DraftedAnswer`, `AnswerReview`) —
  what a structured Groq call is asked to produce. They are deliberately flat and
  small: Groq's tool-calling structured output degrades on deep nesting.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, computed_field

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
    """Cosine similarity to the query, 0-1. What is ranked and what is shown."""

    raw_score: float = 0.0
    """The vector store's own relevance figure, before conversion to cosine.

    Kept because it is what LangChain and Chroma would report if queried
    directly, so a number seen in a debugger or a log can be reconciled with a
    number seen in the interface. Never displayed and never ranked on — see
    `knowledge.cosine_from_relevance` for why the two differ.
    """

    is_lexical: bool = False
    """True when this hit came from the keyword index rather than the vectors.

    The search tool offers both, and `score` cannot distinguish them: a BM25
    rank normalised to the best hit and a cosine similarity are different
    things wearing the same units.
    """

    query_hits: int = 1
    """How many of the question's searches independently returned this chunk.

    Query expansion issues several searches per question, deliberately phrased
    to overlap. A chunk that three of them agree on is a stronger candidate
    than one a single search found, and that agreement is free — it falls out
    of retrieval that has already happened. See `graph.state.order_evidence`.
    """

    authority: str = "ours"
    """Whether this is our own document or an external requirement.

    "ours" for anything this organisation wrote and is bound by; "external" for
    law, regulation and other people's frameworks. Defaults to "ours" because
    that is what the corpus was before the distinction existed, and because the
    failure it guards against is quoting a regulation as our own control -- a
    document wrongly marked ours is the state we were already in.
    """

    # Locator, parsed at ingest. Carried so answers can cite a clause.
    doc_id: str = ""
    clause: str = ""
    heading: str = ""
    page: int = -1
    page_end: int = -1
    """Last page the chunk covers; equal to `page` unless it spans a break.

    A chunk running over a page boundary is ordinary — a table continues, a
    clause carries on — and citing only the page the text starts on sends a
    reader to the wrong half of it.
    """

    chunk: int = -1

    # Unit bookkeeping, used by expansion and by coverage-aware confidence.
    kind: str = "prose"
    unit_id: str = ""
    part: int = 1
    parts: int = 1

    # Prior-answer provenance (Step 6).
    questionnaire: str = ""
    answered_date: str = ""

    entry_id: str = ""
    """Which answer-memory entry this is, for a prior answer. "" for a policy.

    The same string names the row in `memory_entries` and the document in the
    index, so a retrieved answer can be traced to who approved it and what it
    replaced — and so a superseded one can be recognised and dropped.
    """

    clause_start: str = ""
    clause_end: str = ""
    section_clause: str = ""
    item_count: int = 0

    @computed_field
    @property
    def locator(self) -> str:
        """Human-readable citation, e.g. 'MDS-CS-STD-003 §7.2.1'.

        A computed field rather than a plain property so it is serialised: the
        web interface and the exports show the clause, and rebuilding it in
        JavaScript would be a second implementation to keep in step.
        """
        if self.source_type is SourceType.PRIOR_ANSWER:
            parts = [self.questionnaire or self.source_name]
            if self.answered_date:
                parts.append(f"({self.answered_date})")
            return " ".join(parts)

        # The file name leads. A citation is something a person has to go and
        # check, and the internal document code alone cannot be looked up in a
        # folder: the Arabic password policy carries "T2--PRO-PMP-2024-00" in
        # its header, so answers cited "PRO-PMP-2024 \u00a74.1-4.5" and gave the
        # reader no way to tell which of eighty files that was. The code is
        # kept alongside, because assessors do ask for it.
        base = self.source_name or self.doc_id
        if self.doc_id and self.doc_id not in base:
            base = f"{base} [{self.doc_id}]"

        start = self.clause_start or self.clause
        end = self.clause_end or start
        clause = ""
        if start:
            clause = (
                f" \u00a7{start}\u2013{end}" if end and end != start else f" \u00a7{start}"
            )

        # The page is shown *alongside* the clause rather than only when there
        # is no clause. A clause number says what to look for; the page says
        # where to open the file, and on a 161-page standard that is the
        # difference between a citation someone can check and one that merely
        # identifies the text.
        return f"{base}{clause}{self.page_label}"

    @property
    def page_label(self) -> str:
        """`' (Page: 4)'`, `' (Pages: 4-5)'`, or empty when no page is known.

        Spelled out rather than abbreviated: the locator is read by someone
        about to open the document and find the clause, and "p." next to a
        clause number full of dots and dashes is one more thing to decode.

        Empty rather than a guess: documents extracted before page markers
        existed carry no page, and inventing one would make a citation look
        checkable when it is not.
        """
        if self.page < 0:
            return ""
        if self.page_end > self.page:
            return f" (Pages: {self.page}\u2013{self.page_end})"
        return f" (Page: {self.page})"

    def covers_clause(self, clause: str) -> bool:
        """Whether `clause` falls inside this chunk's span."""
        if not clause or not self.clause_start:
            return False

        def key(value: str) -> tuple[int, ...]:
            # Dots for T2's clauses, dashes for NCA and SDAIA control ids.
            return tuple(int(p) for p in re.split(r"[.\-٫]", value) if p.isdigit())

        try:
            return key(self.clause_start) <= key(clause) <= key(self.clause_end or self.clause_start)
        except ValueError:
            return False

    @property
    def is_fragment(self) -> bool:
        """True when this chunk is one part of a unit that was split."""
        return self.parts > 1


class AnsweredQuestion(BaseModel):
    """A question plus the agent's answer and its supporting evidence."""

    question: Question
    answer: str
    rationale: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    needs_review: bool = True
    evidence: list[Evidence] = Field(default_factory=list)
    attempts: int = 1
    brief: str = Field(
        default="",
        description="The same answer, condensed. Empty until somebody asks for it.",
    )

    prefer: str = Field(
        default="",
        description="'full' or 'brief' for this answer alone; '' follows the questionnaire",
    )
    """Which length this one answer is written at, overriding the questionnaire.

    Empty means "whatever the file is set to", which is what almost every
    answer says. The override exists because one question in a file is usually
    the one the assessor will actually read, and it should be allowed to run
    long while the other 182 stay short.
    """
    """A shorter rendering of `answer`, derived from it and never drafted alone.

    Empty on a fresh answer: it costs a model call and most questionnaires are
    never filled in briefly. Filled on request, and kept afterwards, so the
    choice between lengths is instant once it has been made once.
    """

    by_hand: bool = Field(
        default=False,
        description="Whether a person typed these words, rather than agreeing with them",
    )
    """The one fact about an answer the model cannot supply.

    Kept as a field of its own rather than read off `confidence_reason`, which
    already carries a different question -- why the score is what it is -- and
    which approving overwrites. The answer memory turns on this and nothing
    else: agreeing with a draft teaches it nothing, and writing one teaches it
    what we actually say.
    """

    citations: list[str] = Field(default_factory=list, description="Clause-level locators for the sources actually used")
    review_reasons: list[str] = Field(
        default_factory=list,
        description="Why this answer was flagged: unsupported citations, partial series, ungrounded",
    )
    confidence_reason: str = Field(
        default="",
        description="Plain-English cause of a low confidence score; '' when the answer scored well",
    )
    error: str = Field(
        default="",
        description="Why answering this question failed; '' when it produced an answer",
    )
    """Set when the question never produced an answer at all.

    Distinct from a low-confidence or flagged answer, which are judgements
    about content that exists. A rate limit, a withdrawn model or a network
    fault leaves nothing to judge, and the only useful action is to try again —
    which the interface can only offer if it can tell the two apart without
    parsing an error message out of prose.
    """


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
    warning: str | None = Field(
        default=None,
        description="Indexed, but something about the file suggests it was filed as the wrong type",
    )
    duplicate_of: str | None = Field(
        default=None,
        description="Name of an already-indexed file with identical content; set when this upload was skipped",
    )


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


class QueryPlan(BaseModel):
    """Searches to run for one question, before any answer exists."""

    queries: list[str] = Field(
        default_factory=list,
        description="2-4 short search queries, one per distinct thing the question asks",
    )


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
