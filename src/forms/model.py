"""What a questionnaire looks like once we have understood it.

The shapes here are the contract between the two halves of this package: a
format module produces a `DetectedForm` by reading a file, and consumes
`{target_id: value}` to write one back. Nothing above this layer needs to know
whether a question came out of a spreadsheet cell, a table in a Word document,
or a paragraph of prose.

Three ideas do most of the work:

* A **role** says what a column or field is *for*. Detection's real output is a
  role per column; everything else follows from it.
* A **target** is one writable place. A question usually has more than one --
  a status to pick and a comment to write -- so answering is never simply
  "put this string there".
* A **finding** records why detection decided something. The person confirming
  the layout needs to see the reasoning, not just the result, because the
  failure we most want to avoid is a confident wrong guess about which column
  belongs to the assessing bank.
"""

from __future__ import annotations

import re

from enum import Enum

from pydantic import BaseModel, Field

from src.models import Language

_UNFILLED = re.compile(r"^[\s\u2610\u25a1\u25cb\u25ef_\-\u2013\u2014.,:;/\\|()\[\]]*$")
"""A cell holding only whitespace, unticked boxes (☐ □ ○ ◯) or punctuation."""


class Role(str, Enum):
    """What a column, or a field in a document, is for."""

    NUMBER = "number"
    """The printed question number. Read, never written."""

    QUESTION = "question"
    """The question text itself."""

    ANSWER = "answer"
    """Free prose we write."""

    STATUS = "status"
    """A choice from a fixed list -- 'Fully Compliant', 'Yes', 'Not Applicable'.

    Separate from ANSWER because the value has to come from the file's own
    vocabulary rather than being written freely, and because the two are
    genuinely different columns in most of these forms.
    """

    EVIDENCE = "evidence"
    """What to attach. Left blank by default; fillable on instruction."""

    THEIRS = "theirs"
    """A column belonging to whoever sent the questionnaire.

    'Compliance (To be updated by BAB)'. Writing here would be worse than
    leaving a question unanswered, so it is a role of its own rather than
    another kind of ignore.
    """

    CONTEXT = "context"
    """Domain, control id, section -- read for context, never written."""

    IGNORE = "ignore"
    """Recognised and deliberately skipped."""


WRITABLE = frozenset({Role.ANSWER, Role.STATUS, Role.EVIDENCE})
"""Roles a value may be written to. THEIRS is excluded on purpose."""

_VERDICT_WORD = re.compile(
    r"^\s*(yes|no|n/?a|not applicable|compliant|non[- ]compliant|fully compliant|"
    r"partially compliant|implemented|not implemented|نعم|لا)\b",
    re.I,
)
"""A comment that opens with a verdict of its own.

Some questionnaires have a status column the team ignored, writing the whole
answer -- verdict and all -- into the comment beside it. Joining the two there
repeats the verdict, so the comment is taken as the complete answer.
"""


class Finding(BaseModel):
    """One thing detection concluded, and why.

    Carried so the confirmation step can show its reasoning. A layout guess
    that cannot explain itself is one a person has to check from scratch.
    """

    subject: str = Field(description="What this is about: a sheet name, a column letter, a heading")
    verdict: str = Field(description="What was decided")
    because: str = Field(default="", description="The evidence for it, in plain words")
    confident: bool = True
    """False when this is the best guess available rather than a clear read.

    The interface should put the unconfident ones in front of a person first.
    """


class Target(BaseModel):
    """One writable place in the document."""

    id: str = Field(description="Stable within a document, e.g. 'Security!C9' or 'para:142'")
    role: Role
    label: str = Field(default="", description="The column heading, for showing a person")
    vocabulary: list[str] = Field(
        default_factory=list,
        description="Allowed values for a STATUS target; empty when anything goes",
    )
    existing: str = Field(default="", description="What is already there; '' when empty")

    @property
    def is_empty(self) -> bool:
        """Nothing written here -- which includes a box nobody ticked.

        A form that asks for Yes or No by ticking a box ships with "☐" in every
        answer cell, and that is a blank form, not an answered one. Read as an
        answer it was imported into the answer memory as what we said, and the
        guard against overwriting existing answers protected it from ever being
        answered. A ticked mark -- ☒, ☑, ✓ -- still counts: it is the answer.
        """
        return _UNFILLED.match(self.existing or "") is not None


class FormQuestion(BaseModel):
    """One question found in a document, and where its answers go."""

    id: str = Field(description="Stable within this form")
    number: str = Field(default="", description="As printed in the document")
    text: str
    section: str = ""
    language: Language = "en"
    targets: dict[Role, Target] = Field(default_factory=dict)
    location: str = Field(default="", description="Where it was found, for a person to check")

    skip: bool = False
    """Set aside by a person. Never answered, never written.

    Kept rather than deleted: detection over-reports on purpose, and the row a
    person unticks is still a row they may want back when they see what the
    sheet looks like filled in.
    """

    @property
    def writable(self) -> list[Target]:
        if self.skip:
            return []
        return [target for role, target in self.targets.items() if role in WRITABLE]

    @property
    def existing_answer(self) -> str:
        """What the file already had in it for this question, if anything.

        Both cells, joined, because both are the answer. A questionnaire that
        has a status column and a comment column beside it is answered in the
        pair -- "Yes" in one and "T2 enforces multi-factor authentication" in
        the other -- and returning whichever came first threw half of it away.
        Measured over seventeen real questionnaires, 208 of 982 answers were
        being truncated that way, and which half survived depended on which
        column the reader happened to label.

        Joined in the order a person says them, which is also the order the
        security team writes them in: the verdict, then the sentence.
        """
        status = self.targets.get(Role.STATUS)
        prose = self.targets.get(Role.ANSWER)
        verdict = status.existing.strip() if status is not None and not status.is_empty else ""
        sentence = prose.existing.strip() if prose is not None and not prose.is_empty else ""

        if not (verdict and sentence):
            return sentence or verdict

        # The comment already carries a verdict of its own on the files where
        # the team wrote the whole answer into one cell. Joining there produces
        # "Fully Compliant, Yes we encrypt", which is nobody's answer.
        if sentence.casefold().startswith(verdict.casefold()) or _VERDICT_WORD.match(sentence):
            return sentence

        # Punctuation follows the comment's own capitalisation, and the text is
        # never altered. A comment beginning lower case continues the verdict --
        # "Yes" + "we enforce MFA" -- and one beginning upper case is its own
        # sentence, where a comma would be wrong and lower-casing it would ruin
        # a name: "T2 has documented policies" must not become "t2".
        joiner = ", " if sentence[:1].islower() else ". "
        return f"{verdict}{joiner}{sentence}"

    @property
    def is_answered(self) -> bool:
        """Whether an answer is already present.

        Only the ANSWER and STATUS targets count: an evidence column left blank
        is the normal state of an answered question, not an unanswered one.
        """
        return any(not target.is_empty for role, target in self.targets.items() if role in (Role.ANSWER, Role.STATUS))


class Part(BaseModel):
    """A sheet, or a section of a document, and what was made of it."""

    name: str
    kind: str = Field(description="'questions' when it holds any, otherwise why it was skipped")
    questions: int = 0
    findings: list[Finding] = Field(default_factory=list)

    @property
    def used(self) -> bool:
        return self.kind == "questions"


class DetectedForm(BaseModel):
    """Everything understood about one uploaded questionnaire."""

    source_name: str
    format: str = Field(description="'xlsx' or 'docx'")
    questions: list[FormQuestion] = Field(default_factory=list)
    parts: list[Part] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def answered_count(self) -> int:
        return sum(1 for question in self.questions if question.is_answered)

    def target(self, target_id: str) -> Target | None:
        for question in self.questions:
            for candidate in question.targets.values():
                if candidate.id == target_id:
                    return candidate
        return None


class WriteReport(BaseModel):
    """What a write-back actually did."""

    path: str
    created: list[str] = Field(default_factory=list, description="Targets that did not exist")
    replaced: list[str] = Field(default_factory=list, description="Targets that held something")
    skipped: dict[str, str] = Field(default_factory=dict, description="Target id -> why nothing was written")
    parts_before: int = 0
    parts_after: int = 0

    @property
    def written(self) -> int:
        return len(self.created) + len(self.replaced)

    @property
    def intact(self) -> bool:
        """Whether the package came out with everything it went in with.

        The single check that matters for the deliverable: openpyxl round-trips
        lose drawings, comments and conditional formatting, and this is the
        assertion that says we did not.
        """
        return self.parts_before == self.parts_after
