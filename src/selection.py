"""Which questions an operation applies to, when an answer counts as settled, and what is written.

Moved from `src/tools.py` (plan 023), which re-exports what its callers use:
`tools.Scope`, `tools.HAND`, `tools.APPROVED` and `tools.ready_to_write` are
the names the interface, the assistant and the tests have always used.
`length_of` and `written_text` followed in plan 029, to make room in `tools.py`,
and then `nothing_written` (`tools._nothing_written` until then).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.config import settings
from src.forms.model import DetectedForm, FormQuestion
from src.models import AnsweredQuestion, BeforeApproval
from src.verification import held_by_score

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


def held_by_the_review(answered: AnsweredQuestion, threshold: float | None = None) -> bool:
    """The review's own rule (`verification.assess`): any reason, or a score at or under the threshold.

    Never for words a person wrote: those were not the model's to review.
    """
    floor = settings.review_confidence_threshold if threshold is None else threshold
    return not written_by_a_person(answered) and (
        bool(answered.review_reasons) or held_by_score(answered.confidence, floor)
    )


def approve(answered: AnsweredQuestion, *, threshold: float | None = None) -> AnsweredQuestion:
    """Released by a person, keeping what the review said for a withdrawal (TD-053).

    What the review said is the stored flag, unless the stored state contradicts
    the review's own rule. The withdrawal before TD-053's fix left exactly that
    (the flag cleared, the reasons kept), and recording it would release the
    answer again on the next withdrawal (plan 029's review).
    """
    approved = answered.model_copy(deep=True)
    if approved.confidence_reason != APPROVED:  # approving twice keeps the first record
        approved.before_approval = BeforeApproval(
            needs_review=approved.needs_review or held_by_the_review(approved, threshold),
            confidence_reason=approved.confidence_reason,
        )
    approved.confidence_reason, approved.needs_review = APPROVED, False
    return approved


def withdraw_approval(
    answered: AnsweredQuestion, *, reworded: bool = False, threshold: float | None = None
) -> AnsweredQuestion:
    """The answer as it stood before a person approved it.

    The kept state first. An approval from before it was kept is judged again by
    the review's own rule (`verification.assess`: any reason, or a score at or under
    the threshold) unless a person wrote the words. `reworded`: the words are the
    model's now, so "written by hand" goes too. Not approved: unchanged, but for that.
    """
    withdrawn = answered.model_copy(deep=True)
    if withdrawn.confidence_reason == APPROVED:
        kept = withdrawn.before_approval
        if kept is not None:
            withdrawn.needs_review, withdrawn.confidence_reason = kept.needs_review, kept.confidence_reason
        else:
            withdrawn.needs_review = held_by_the_review(withdrawn, threshold)
            withdrawn.confidence_reason = HAND if written_by_a_person(withdrawn) else ""
    withdrawn.before_approval = None
    if reworded and withdrawn.confidence_reason == HAND:
        withdrawn.confidence_reason = ""
    return withdrawn


def ready_to_write(
    answered: AnsweredQuestion | None, edited_by: str = "", *, threshold: float | None = None
) -> tuple[bool, str]:
    """Whether an answer may go into the file, and why not when it may not.

    The reason is returned rather than logged because it is what the interface
    shows the person: "held back" with no cause is a wall, and the whole point
    of holding an answer back is that somebody should look at it.

    A score is judged by the review's own rule (`verification.held_by_score`,
    plan 030): at or under the threshold is held. This compared "under" until
    then, which differed only for an unflagged score exactly at the threshold.
    The pipeline never produces one, since the review flags every such score;
    an answer left unflagged by a withdrawn approval (TD-053) or by a threshold
    changed since it was drafted could be one, and it is held now.
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
    if held_by_score(answered.confidence, floor):
        return False, (
            f"confidence {answered.confidence:.0%}, at or under the {floor:.0%} threshold for writing without a person looking"
        )
    return True, ""


def length_of(answered: AnsweredQuestion, detail: str = "full") -> str:
    """Which length this answer is written at: its own choice, else the file's."""
    return answered.prefer or detail or "full"


def written_text(answered: AnsweredQuestion, detail: str = "full") -> str:
    """The words that go into the cell, at the length that was chosen for them.

    Falls back to the full answer when a brief one has not been derived yet, so
    switching a questionnaire to brief and filling it immediately writes the
    long answers rather than blanks. The interface derives them first; this is
    what happens when something else does not.
    """
    if length_of(answered, detail) == "brief" and answered.brief.strip():
        return answered.brief.strip()
    return answered.answer


def nothing_written(form: DetectedForm, answered: dict[str, AnsweredQuestion], held: dict[str, str]) -> str:
    """Why a fill wrote nothing. Only asked when it wrote nothing.

    Four states arrive here looking identical and are not: work not started, work
    already done by the file itself, every row struck out, and every answer held
    back by the gate (`held`: what was kept out). The message has to name which,
    because what the person should do next differs in each.
    """
    if not any(_has_answer(answered.get(q.id)) for q in form.questions):
        already = form.answered_count
        if already:
            blank = sum(1 for q in form.questions if not _settled(answered.get(q.id), q))
            return (
                f"Nothing needed writing: the {already} answer(s) this questionnaire has "
                "came with the file and are already in it."
                + (
                    f" {blank} question(s) are still blank — answer those and fill again."
                    if blank
                    else " Every question is answered."
                )
            )
        return "Nothing has been answered yet, so there was nothing to write. Answer some questions first."
    if all(q.skip for q in form.questions if _has_answer(answered.get(q.id))):
        return "Every answered question is set aside, so nothing was written for any of them."
    if held:
        return f"Nothing was written: {len(held)} answer(s) are held back until somebody edits or approves them."
    return (
        "The answers exist but none of them has a cell to go into -- check the "
        "answer column for each sheet in the reading report."
    )


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
