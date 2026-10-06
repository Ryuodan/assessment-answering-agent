"""Which questions an operation applies to, and when an answer counts as settled.

Moved from `src/tools.py` (plan 023), which re-exports what its callers use:
`tools.Scope`, `tools.HAND`, `tools.APPROVED` and `tools.ready_to_write` are
the names the interface, the assistant and the tests have always used.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.config import settings
from src.forms.model import DetectedForm, FormQuestion
from src.models import AnsweredQuestion

# ---------------------------------------------------------------------------
# Choosing which questions to act on
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Scope:
    """Which questions an operation applies to.

    Every field narrows; they combine with AND. The default selects everything,
    which is what "answer this questionnaire" means.
    """

    ids: tuple[str, ...] = ()
    """Specific questions. Empty means no restriction by id."""

    part: str = ""
    """A sheet name, or the section a question sits under."""

    matching: str = ""
    """Free text, matched against the question and its section."""

    unanswered_only: bool = False
    """Narrow to questions with no answer yet -- "finish the rest", "what is left".

    A way of *naming* a subset, not a safety belt: `answer` refuses to overwrite
    an existing answer whether or not this is set. It still earns its place,
    because "list what is left" and "answer what is left" are things people ask
    and the count has to come out right.

    "Already answered" means either -- an answer this system wrote, or one the
    file arrived with. Counting only our own was the whole of that intention
    missed.
    """

    def select(self, form: DetectedForm, answered: dict[str, AnsweredQuestion]) -> list[FormQuestion]:
        chosen = []
        needle = self.matching.strip().casefold()
        for question in form.questions:
            if self.ids and question.id not in self.ids:
                continue
            if self.part and self.part.casefold() not in (
                question.location.casefold() + " " + question.section.casefold()
            ):
                continue
            if needle and needle not in (question.text + " " + question.section).casefold():
                continue
            if self.unanswered_only and _settled(answered.get(question.id), question):
                continue
            if not question.writable:
                continue
            chosen.append(question)
        return chosen

    def describe(self) -> str:
        """What this scope selects, for an event log a person reads."""
        parts = []
        if self.ids:
            parts.append(f"{len(self.ids)} chosen question(s)")
        if self.part:
            parts.append(f"in {self.part!r}")
        if self.matching:
            parts.append(f"mentioning {self.matching!r}")
        if self.unanswered_only:
            parts.append("not yet answered")
        return ", ".join(parts) or "all questions"


def _has_answer(answered: AnsweredQuestion | None) -> bool:
    return bool(answered and answered.answer.strip() and not answered.error)


BLANKED = "left blank on purpose"
"""Why an answer is empty, when somebody emptied it deliberately.

Recorded rather than inferred. An empty answer and a question nobody has
answered yet look identical from the outside, and they are opposite states: one
is a decision and the other is work outstanding.
"""


HAND = "written by hand"
"""What `confidence_reason` says when a person typed the answer themselves.

The durable mark is `AnsweredQuestion.by_hand`; this is the sentence shown
beside the score, and the reading of it that answers written before that field
existed still rely on.
"""


APPROVED = "approved by a reviewer"
"""Recorded in `confidence_reason` when a person accepted an answer as it stands.

Editing an answer already marks it a person's work -- `edited_by` carries their
name. Approving is the other half of that: the answer is right as written, and
saying so should not require pretending to change it.
"""


def confirmed_by_a_person(answered: AnsweredQuestion | None, edited_by: str = "") -> bool:
    """Whether a person has put their name to this answer."""
    if answered is None:
        return False
    return bool(edited_by) or answered.by_hand or answered.confidence_reason in (APPROVED, HAND)


def written_by_a_person(answered: AnsweredQuestion | None) -> bool:
    """Whether the words are somebody's own, rather than the model's.

    A narrower question than `confirmed_by_a_person`, and the two are often
    confused: reading an answer and agreeing with it is not the same act as
    writing it, and only one of them tells us anything the system did not
    already believe.

    The `confidence_reason` reading is for answers stored before `by_hand`
    existed, which are still sitting in open batches.
    """
    if answered is None:
        return False
    return answered.by_hand or answered.confidence_reason == HAND


def ready_to_write(
    answered: AnsweredQuestion | None, edited_by: str = "", *, threshold: float | None = None
) -> tuple[bool, str]:
    """Whether an answer may go into the file, and why not when it may not.

    The reason is returned rather than logged because it is what the interface
    shows the person: "held back" with no cause is a wall, and the whole point
    of holding an answer back is that somebody should look at it.
    """
    if answered is None or not answered.answer.strip():
        return False, ""
    if confirmed_by_a_person(answered, edited_by):
        return True, ""

    floor = settings.review_confidence_threshold if threshold is None else threshold
    if answered.error:
        return False, "it could not be answered"
    if answered.needs_review:
        reasons = "; ".join(answered.review_reasons) or (answered.confidence_reason or "the reviewer flagged it")
        return False, f"flagged for review -- {reasons}"
    if answered.confidence < floor:
        return False, (
            f"confidence {answered.confidence:.0%}, below the {floor:.0%} needed to write without a person looking"
        )
    return True, ""


def _settled(answered: AnsweredQuestion | None, question: FormQuestion) -> bool:
    """Whether a question is done with, however it got that way.

    Three ways, and `unanswered_only` has to respect all of them or it offers
    work that is finished: this system answered it, the file arrived with an
    answer in it, or somebody decided it should be left blank. The last is the
    one that catches people out -- an empty answer and an unanswered question
    look identical, and they are opposite states.
    """
    if answered is not None and answered.confidence_reason == BLANKED:
        return True
    return _has_answer(answered) or question.is_answered
