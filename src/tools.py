"""The operations the interface performs, and the chat assistant calls.

Everything a person can do to a questionnaire is one of these, and each is a
plain function taking a user and returning data -- no request, no response, no
HTML. That is deliberate: the assistant chooses *which* of these to call and
with what arguments, and the less it can do beyond calling them, the less there
is to go wrong; and they are tested with fixed inputs.

    open_form   a file becomes a batch of questions
    inspect     what is in a batch and how far it has got
    answer      write answers for a selection of its questions
    revise      rewrite answers that already exist, under an instruction
    set_answer  a person overrules the system
    fill        put the answers into the original file
    search      look something up in the policies, without touching a batch

**Scope** is what makes a selection expressible: "all of them", "the ones still
blank", "the sheet called Data Privacy", "anything mentioning encryption". The
agent's whole job is turning a sentence into a `Scope` and an instruction, so it
lives beside the operations rather than in the agent: in `src/selection.py`,
re-exported here.
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import asyncio

from src.config import settings
from src import answer_memory, batches, busy, events, preferences, products, progress, rewrite, service, store
from src.formatting import to_cell_text
from src.batches import Batch
from src.forms import status as status_map
from src.forms.model import WRITABLE, DetectedForm, Finding, FormQuestion, Role, Target
from src.identity import User
from src.models import AnsweredQuestion, Language, Question
from src.errors import ToolError as ToolError
from src.questionnaire import inspect as inspect, memory_id as _memory_id, require as _require
from src.styling import in_house_style as in_house_style
from src.selection import (
    APPROVED as APPROVED,
    BLANKED as BLANKED,
    HAND as HAND,
    Scope as Scope,
    _has_answer,
    _settled,
    approve,
    confirmed_by_a_person as confirmed_by_a_person,
    length_of,
    nothing_written,
    ready_to_write as ready_to_write,
    written_by_a_person as written_by_a_person,
    withdraw_approval,
    written_text as written_text,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class Outcome:
    """What an answering operation did."""

    batch_id: str
    attempted: int = 0
    answered: int = 0
    failed: int = 0
    needs_review: int = 0
    scope: str = ""

    protected: int = 0
    """Questions the scope selected that already had an answer, and were left alone.

    Not a failure and not "nothing matched": the scope did match them, and the
    operation deliberately declined to overwrite work that already exists.
    Counted separately so the caller can say so, because "answered 0" and
    "answered 0, left 9 alone" mean opposite things to the person reading it.
    """

    styled: int = 0
    """Answers reworded to the person's preferences after they were drafted.

    Reported so whoever relays the outcome can say so: an answer that reads
    unlike the last run's for a reason nobody mentioned looks like a fault.
    """

    @property
    def nothing_matched(self) -> bool:
        return self.attempted == 0 and not self.protected


@dataclass
class Filled:
    """A questionnaire written back to a file."""

    path: Path
    written: int = 0
    created: int = 0
    replaced: int = 0
    skipped: dict[str, str] = field(default_factory=dict)
    blank: dict[str, str] = field(default_factory=dict)
    """Targets deliberately left empty, and why. Evidence columns, mostly."""

    held_back: dict[str, str] = field(default_factory=dict)
    """Questions whose answers nobody has confirmed, and why each was held.

    Keyed by question rather than by target, because this is something a person
    acts on: they open the answer, read it, and either fix it or approve it.
    Distinct from `blank`, which is a decision already made, and from
    `skipped`, which is the file refusing a value.
    """

    written_anyway: list[str] = field(default_factory=list)
    """Held answers written all the same, because a person said so ("Write them in anyway")."""

    intact: bool = True

    because: str = ""
    """Why nothing was written, when nothing was. Empty on a normal fill.

    "Wrote 0 value(s) into the file -- every other part of it is untouched" is
    a true sentence that reads like success, and a person who has just watched
    a run finish will read it as one. Zero has causes, and they are different
    problems: nothing has been answered yet, or everything was answered by the
    file itself and there is genuinely nothing to add.
    """


# ---------------------------------------------------------------------------
# The operations
# ---------------------------------------------------------------------------


def open_form(user: User, path: Path, *, strategy: str | None = None, product_id: str = "") -> Batch:
    """Read an uploaded questionnaire and record it as a batch.

    `strategy` is one of `forms.reading.STRATEGIES` and decides how hard to
    work at understanding the file -- the rules alone, the rules plus a model
    call for each sheet they could not read, or an agent that explores it. It
    defaults to the configured one, and the choice is a cost decision rather
    than a correctness one: see `src.forms.reading`.

    Detection failures reach the caller as `forms.FormatError`, which already
    carries a message safe to show whoever uploaded the file.

    `product_id` is the product it is answered for, "" for General (plan 023);
    another team's is `product_not_found`, before the file is read.
    """
    from src.forms import reading

    product_id = products.chosen(user.team_id, product_id)

    chosen = strategy or settings.detection_strategy
    result = reading.read(path, chosen)
    form = result.form
    batch = batches.create(user, path, form, product_id)
    # Whoever opens it decides how long its answers start out. Only the opening
    # default: a teammate who picks the file up later sees the length it already
    # has, because changing it under somebody else's work is not a preference.
    wanted = preferences.load(user.email).default_length
    if wanted != batch.detail:
        batches.set_detail(batch.id, wanted)
        batch = batches.load(batch.id, team_id=user.team_id, actor_email=user.email) or batch
    events.record(
        user,
        events.FORM_OPENED,
        subject_type=batches.SUBJECT,
        subject_id=batch.id,
        source_name=form.source_name,
        questions=len(form.questions),
        already_answered=form.answered_count,
        strategy=chosen,
        seconds=round(result.seconds, 2),
        tokens=result.tokens,
        detail=batch.detail,
        **({"product_id": product_id} if product_id else {}),
    )
    return batch


def set_product(user: User, batch_id: str, product_id: str) -> Batch:
    """Refused unless it is the questionnaire's own product: it is fixed when the file is opened (TD-040).

    Another team's product, or a deleted one, is still `product_not_found`; the
    questionnaire's own product is accepted, and changes nothing.
    """
    batch = _require(user, batch_id)
    products.refuse_change(
        user.team_id,
        batch.product_id,
        product_id,
        "A questionnaire's product is fixed when it is opened. To answer this file for another product, "
        "close it and open the file again with that product chosen.",
    )
    return batch


async def answer(
    user: User,
    batch_id: str,
    scope: Scope | None = None,
    *,
    run_id: str = "",
    replace_existing: bool = False,
) -> Outcome:
    """Answer a selection of a batch's questions.

    Always the same prompt. How an answer should be worded is `revise`'s job,
    over an answer that already exists -- see the note on the drafting node for
    what measuring the two ways showed.

    Each question is answered in its own language: the samples mix an Arabic
    question into an English form, and the question's own language is the one
    the assessor asked in.

    An answer that already exists is never overwritten unless the caller says
    `replace_existing`. This is a guard and not a convenience: an answer in the
    file was written by the security team who own the subject, and one written
    here was reviewed by somebody. Either is worth more than a fresh draft, and
    both used to be lost silently -- a broad scope over last year's submission
    replaced every reviewed word in it. Naming the questions does not lift the
    guard; only asking to replace them does.
    """
    batch = _require(user, batch_id)
    scope = scope or Scope()
    existing = batches.answers(batch.id)
    chosen = scope.select(batch.form, existing)

    protected = 0
    if not replace_existing:
        keeping = [q for q in chosen if not _settled(existing.get(q.id), q)]
        protected = len(chosen) - len(keeping)
        chosen = keeping

    outcome = Outcome(
        batch_id=batch.id,
        attempted=len(chosen),
        scope=scope.describe(),
        protected=protected,
    )
    if not chosen:
        return outcome

    # One run at a time, and nothing else changes it meanwhile (plan 029). No
    # await since `_require` looked, so no other run can have started since.
    with busy.hold(batch.id, run_id or batch.id):
        # The questionnaire's product, from its knowledge base beside the shared one.
        scope_of_answers: dict[str, Any] = {"product_id": batch.product_id} if batch.product_id else {}
        results = await service.answer_questions(
            [_as_question(question) for question in chosen],
            run_id=run_id or batch.id,
            team_id=user.team_id,
            on_answer=batches.saver(batch.id),  # each saved as it finishes: a run cut short keeps them
            **scope_of_answers,
        )
        # Preferences are applied here, after drafting and review, and never
        # handed to `service`: see `src.preferences` for why the drafter must not
        # see them. Here rather than in each interface so the workbench and the
        # assistant cannot disagree about whether it happened.
        results = await in_house_style(user, results, run_id=run_id or batch.id)
        outcome.styled = sum(1 for result in results if result.drafted)
        batches.save_answers(batch.id, results)
        # A questionnaire being filled in briefly needs the brief form of what was
        # just answered. It used to get it only at the moment somebody switched the
        # file to brief, so anything answered afterwards showed -- and was written
        # -- at full length under a "Brief" label.
        if batch.detail == "brief":
            fresh = tuple(result.question.id for result in results if _has_answer(result))
            if fresh:
                await make_brief(user, batch.id, Scope(ids=fresh), run_id=run_id)

        outcome.answered = sum(1 for r in results if not r.error)
        outcome.failed = sum(1 for r in results if r.error)
        outcome.needs_review = sum(1 for r in results if r.needs_review and not r.error)
        events.record(
            user,
            events.BATCH_ANSWERED,
            subject_type=batches.SUBJECT,
            subject_id=batch.id,
            scope=outcome.scope,
            attempted=outcome.attempted,
            answered=outcome.answered,
            failed=outcome.failed,
        )
        return outcome


def restore_draft(user: User, batch_id: str, question_id: str) -> None:
    """Put back the answer as it was drafted, before a style, a skill or a rewording changed it."""
    batch = _require(user, batch_id)
    existing = batches.answers(batch.id).get(question_id)
    if existing is None or not existing.drafted.strip():
        raise ToolError("That answer has not been reworded since it was drafted, so there is nothing to put back.")
    restored = existing.model_copy(deep=True)
    restored.answer = existing.drafted
    restored.drafted = ""
    restored.brief = ""
    restored.by_hand = False
    if restored.confidence_reason in (APPROVED, HAND):
        restored.confidence_reason = ""
    batches.save_answers(batch.id, [restored])
    events.record(
        user,
        events.BATCH_REVISED,
        subject_type=batches.SUBJECT,
        subject_id=batch.id,
        question_id=question_id,
        restored_draft=True,
    )


async def revise(
    user: User,
    batch_id: str,
    instruction: str,
    scope: Scope | None = None,
    *,
    run_id: str = "",
    note: str = "",
    include_written: bool = False,
    language: Language | None = None,
) -> Outcome:
    """Rewrite answers that already exist, under an instruction.

    Not the answering pipeline: one call per answer over the answer itself and
    the sources it was built from, so "shorter" or "more formal" changes the
    wording and nothing else -- the facts, the evidence and the citations come
    through untouched. See `src.rewrite` for why, and for what measuring the
    alternative showed. Only questions that already have an answer are touched:
    revising a blank one is answering it, and the caller should say so.

    Progress is reported under the batch id, so a long rewording can be watched
    the same way a long run can.

    An answer a person wrote is left alone unless `include_written` says
    otherwise, and counted in `protected`. "Make them all more formal" is about
    the drafts; rewording a reviewer's own sentence under it would put the
    model's words where theirs were, and they would find out by reading the
    file. The same rule `answer` keeps for existing answers, for the same reason.

    A reworded answer has to be read again. Its approval was for different
    words, so the approval does not carry over -- and nor does the mark that a
    person wrote it, which is what keeps model text out of the answer memory.
    Answers the rewrite could not reword are not written back at all.
    """
    if not instruction.strip():
        raise ToolError("Say how the answers should change.")

    batch = _require(user, batch_id)
    existing = batches.answers(batch.id)
    scope = scope or Scope()
    candidates = [question for question in scope.select(batch.form, existing) if _has_answer(existing.get(question.id))]
    chosen = (
        candidates
        if include_written
        else [question for question in candidates if not written_by_a_person(existing[question.id])]
    )

    outcome = Outcome(
        batch_id=batch.id,
        attempted=len(chosen),
        scope=scope.describe(),
        protected=len(candidates) - len(chosen),
    )
    if not chosen:
        return outcome

    with busy.hold(batch.id, run_id or batch.id):  # nothing else changes it meanwhile (plan 029)
        # Reworded, not re-answered. Running the pipeline again with the instruction
        # as a style would re-retrieve and re-review, so "make it shorter" could come
        # back saying something different -- which is not what revise means. One call
        # over the answer and the sources it already used keeps the facts, the
        # citations and the clause a reader would go and check.
        progress.start(run_id or batch.id, stage="rewriting")
        progress.set_total(run_id or batch.id, len(chosen))
        try:

            async def one(question: FormQuestion) -> AnsweredQuestion:
                original = existing[question.id]
                try:
                    revised = await rewrite.rewrite(
                        original,
                        instruction,
                        **({"language": language} if language else {}),
                        **({"note": note} if note else {}),
                    )
                finally:
                    progress.advance(run_id or batch.id)
                if revised is not original:
                    # The first rewording keeps the draft, so any of them can be
                    # undone. Not a person's words, though: "put the draft back"
                    # would then restore them marked as the model's.
                    if not revised.drafted and not written_by_a_person(original):
                        revised.drafted = original.answer
                    revised.by_hand = False
                    # The brief form was condensed from the words just replaced.
                    # Kept, it went on being what a brief questionnaire showed and
                    # wrote, so the rewording appeared to do nothing at all.
                    revised.brief = ""
                    revised = withdraw_approval(revised, reworded=True)  # held again if it was before approval
                return revised

            results = list(await asyncio.gather(*(one(q) for q in chosen)))
        finally:
            progress.finish(run_id or batch.id)

        changed = [r for r in results if r is not existing[r.question.id]]
        batches.save_answers(batch.id, changed)
        # Derived again only where somebody is going to read the brief form.
        shown_brief = tuple(r.question.id for r in changed if length_of(r, batch.detail) == "brief")
        if shown_brief:
            await make_brief(user, batch.id, Scope(ids=shown_brief), run_id=run_id)

        outcome.answered = len(changed)
        outcome.failed = len(results) - len(changed)
        outcome.needs_review = sum(1 for r in changed if r.needs_review and not r.error)
        events.record(
            user,
            events.BATCH_REVISED,
            subject_type=batches.SUBJECT,
            subject_id=batch.id,
            scope=outcome.scope,
            instruction=instruction[:400],
            attempted=outcome.attempted,
            protected=outcome.protected,
        )
        return outcome


async def apply_skill(
    user: User,
    batch_id: str,
    skill_id: str,
    scope: Scope | None = None,
    *,
    run_id: str = "",
    include_written: bool = False,
) -> tuple[preferences.Skill, Outcome]:
    """Reword a selection of answers with one of this person's skills.

    A skill is a saved instruction for `revise`, and nothing more: the same
    rewrite path, the same protection for answers a person wrote, the same rule
    that the sources outrank the instruction. Naming it is the whole of what it
    adds, which is exactly what makes it safe to keep and reuse.
    """
    skill = preferences.get_skill(user.email, skill_id)
    if skill is None:
        raise ToolError("You have no skill like that. Your skills are on the preferences page.")
    outcome = await revise(
        user,
        batch_id,
        skill.instruction,
        scope,
        run_id=run_id,
        note=f"Reworded with the skill \u201c{skill.name}\u201d.",
        include_written=include_written,
    )
    events.record(
        user,
        events.SKILL_APPLIED,
        subject_type=batches.SUBJECT,
        subject_id=batch_id,
        skill=skill.name,
        reworded=outcome.answered,
        protected=outcome.protected,
    )
    return skill, outcome


def set_answer(user: User, batch_id: str, question_id: str, text: str, *, which: str = "answer") -> None:
    """Replace one answer with words a person wrote.

    Recorded as an edit with their name on it. This is one of only three ways
    answer text is ever written -- the other two are `answer` and `revise`.

    `which` says which of the two lengths is being edited. Editing the full
    answer throws the brief one away rather than keeping it: the brief was
    condensed from the words that were just replaced, so keeping it would leave
    the questionnaire holding two answers that no longer say the same thing,
    and which one went into the file would depend on a toggle.
    """
    batch = _require(user, batch_id)
    question = next((q for q in batch.form.questions if q.id == question_id), None)
    if question is None:
        raise ToolError(f"No question {question_id!r} in this questionnaire.")
    if which not in ("answer", "brief"):
        raise ToolError("An answer is either the full one or the brief one.")

    existing = batches.answers(batch.id).get(question_id)
    previous = (getattr(existing, which) if existing else "") or ""

    # Emptying the answer is clearing it, not writing an empty one. Stored as
    # an empty answer "written by hand", it was neither blank on purpose nor
    # unanswered: nothing was written, and the card said no answer had been
    # produced. Cleared, the question is simply unanswered, and the file keeps
    # whatever its cell already held -- empty stays empty, and an answer the
    # file arrived with stays. Leaving a cell empty over the file's own answer
    # is "Leave blank", which is a decision rather than a deletion. An empty brief
    # released the model's full answer as a person's (plan 029), so it is refused.
    if which == "brief" and not text.strip():
        raise ToolError("A brief answer cannot be empty. To write nothing for this question, use Leave blank.")
    if which == "answer" and not text.strip():
        if existing is not None:
            batches.forget_answer(batch.id, question_id)
            events.record(
                user,
                events.ANSWER_EDITED,
                subject_type=batches.SUBJECT,
                subject_id=batch.id,
                question_id=question_id,
                was=previous[:400],
                cleared=True,
            )
        return

    answered = _working_copy(existing, question)
    if which == "brief":
        answered.brief = text
    else:
        answered.answer = text
        answered.brief = ""
    answered.needs_review = False
    answered.error = ""
    answered.confidence = 1.0
    answered.by_hand = True
    # Their words now, so neither the draft the style reworded nor anything
    # derived from it is a version of this answer any more.
    if which == "answer":
        answered.drafted = ""
    answered.confidence_reason = HAND

    batches.save_answers(batch.id, [answered], edited_by=user.email)
    events.record(
        user,
        events.ANSWER_EDITED,
        subject_type=batches.SUBJECT,
        subject_id=batch.id,
        question_id=question_id,
        was=previous[:400],
        now=text[:400],
    )


def blank_answer(user: User, batch_id: str, question_id: str, *, blank: bool = True) -> None:
    """Leave a question deliberately blank, keeping it out of the work still to do.

    The cell is still written -- with nothing in it -- because the file may
    already hold last year's answer, and "leave this blank" has to be able to
    clear it.

    `blank=False` is the undo, and it undoes rather than reverses: the stored
    answer is forgotten entirely, so the question goes back to being one nobody
    has answered. Storing something in its place would only be a different
    decision made on the person's behalf.
    """
    batch = _require(user, batch_id)
    question = next((q for q in batch.form.questions if q.id == question_id), None)
    if question is None:
        raise ToolError(f"No question {question_id!r} in this questionnaire.")

    if not blank:
        batches.forget_answer(batch.id, question_id)
        events.record(
            user,
            events.ANSWER_EDITED,
            subject_type=batches.SUBJECT,
            subject_id=batch.id,
            question_id=question_id,
            blanked=False,
        )
        return

    existing = batches.answers(batch.id).get(question_id)
    answered = _working_copy(existing, question)
    answered.answer = ""
    answered.needs_review = False
    answered.error = ""
    answered.confidence = 1.0
    answered.confidence_reason = BLANKED
    batches.save_answers(batch.id, [answered], edited_by=user.email)
    events.record(
        user,
        events.ANSWER_EDITED,
        subject_type=batches.SUBJECT,
        subject_id=batch.id,
        question_id=question_id,
        blanked=True,
    )


def prefer_length(user: User, batch_id: str, question_id: str, prefer: str) -> None:
    """Choose the length for one answer, overriding the questionnaire's default.

    `prefer=""` gives the answer back to the default, which is different from
    pinning it to the value the default happens to have now -- a file switched
    to brief afterwards should carry this answer with it unless somebody said
    otherwise about this answer specifically.
    """
    batch = _require(user, batch_id)
    if prefer not in ("", "full", "brief"):
        raise ToolError("An answer is written full, brief, or however the file is set.")
    existing = batches.answers(batch.id).get(question_id)
    if existing is None:
        raise ToolError(f"No answer for {question_id!r} yet.")

    answered = existing.model_copy(deep=True)
    answered.prefer = prefer
    batches.save_answers(batch.id, [answered], edited_by=batches.edited_by(batch.id).get(question_id, ""))


async def make_brief(user: User, batch_id: str, scope: Scope | None = None, run_id: str = "") -> Outcome:
    """Derive the brief form of every answer in scope that does not have one.

    Not a re-answer and not a general rewording: one fixed instruction through
    the rewrite path, which keeps the facts and the citations because it never
    re-retrieves. Skips answers that already have a brief, so switching back and
    forth costs nothing after the first time.
    """
    batch = _require(user, batch_id)
    existing = batches.answers(batch.id)
    scope = scope or Scope()
    chosen = [
        question
        for question in scope.select(batch.form, existing)
        if _has_answer(existing.get(question.id)) and not existing[question.id].brief.strip()
    ]

    outcome = Outcome(batch_id=batch.id, attempted=len(chosen), scope=scope.describe())
    if not chosen:
        return outcome

    with busy.hold(batch.id, run_id or batch.id):  # nothing else changes it meanwhile (plan 029)
        progress.start(run_id or batch.id, stage="shortening")
        progress.set_total(run_id or batch.id, len(chosen))
        try:

            async def one(question: FormQuestion) -> AnsweredQuestion:
                answered = existing[question.id].model_copy(deep=True)
                try:
                    answered.brief = await rewrite.shorten(answered)
                except Exception:  # noqa: BLE001 - one failure is one long answer, not a failed run
                    logger.exception("Could not shorten %s", question.id)
                finally:
                    progress.advance(run_id or batch.id)
                return answered

            results = list(await asyncio.gather(*(one(q) for q in chosen)))
        finally:
            progress.finish(run_id or batch.id)

        # Saved under whoever had put their name to each answer. One save for all of
        # them recorded every answer as edited by nobody, which erased the name of
        # the person who had approved or corrected it.
        edits = batches.edited_by(batch.id)
        for who in {edits.get(r.question.id, "") for r in results}:
            batches.save_answers(
                batch.id,
                [r for r in results if edits.get(r.question.id, "") == who],
                edited_by=who,
            )
        outcome.answered = sum(1 for r in results if r.brief.strip())
        outcome.failed = outcome.attempted - outcome.answered
        return outcome


def set_detail(user: User, batch_id: str, detail: str) -> None:
    """Choose whether this questionnaire is filled in full or briefly."""
    batch = _require(user, batch_id)
    if detail not in batches.DETAIL_LEVELS:
        raise ToolError(f"Answer length must be one of {', '.join(batches.DETAIL_LEVELS)}.")
    batches.set_detail(batch.id, detail)
    events.record(
        user,
        events.BATCH_ANSWERED,
        subject_type=batches.SUBJECT,
        subject_id=batch.id,
        detail=detail,
    )


def approve_answer(user: User, batch_id: str, question_id: str, *, approved: bool = True) -> str:
    """Accept an answer as it stands, so `fill` will write it.

    The reviewer's name is recorded exactly as an edit records it, because from
    the file's point of view the two are the same act: a person read this and
    put their name to it. Approving does not change a word of the answer, and
    the confidence score is left alone -- overwriting it would destroy the
    signal that made the answer worth reading in the first place.

    It teaches the answer memory only when the words are a person's own, and
    returns the entry id it wrote -- "" when it wrote nothing. An answer the
    model drafted and a reviewer waved through carries no information this
    system did not already have: remembering it feeds the drafter its own
    output, and the next questionnaire is then answered from a prior answer
    that was itself a draft, at a confidence the loop manufactured rather than
    earned. What a person *wrote* is the opposite -- it is the one thing in the
    exchange that came from outside the model -- and that is what the memory is
    for.

    So approving does two things and they are separate: the answer goes into
    the file either way, and it goes into the memory when somebody wrote it.
    Taking an approval back removes what it taught, because an answer somebody
    withdrew should not be quoted back at them next month.

    There is no way to approve one *without* teaching it when it was written by
    hand, deliberately. An answer that is right for this customer and not a
    general position does happen, and the place to deal with it is the memory
    page, where the entry can be read, corrected or forgotten -- rather than a
    second switch beside every approve button, which is a decision asked of
    everybody to serve the rare case.
    """
    batch = _require(user, batch_id)
    if not any(q.id == question_id for q in batch.form.questions):
        raise ToolError(f"No question {question_id!r} in this questionnaire.")

    existing = batches.answers(batch.id).get(question_id)
    if existing is None or not existing.answer.strip():
        raise ToolError("There is no answer to approve for that question yet.")
    if existing.confidence_reason == BLANKED:
        raise ToolError("That answer is deliberately blank. Write one before approving it.")

    by_hand = written_by_a_person(existing)

    answered = approve(existing) if approved else withdraw_approval(existing)  # puts back the review's flag (TD-053)
    batches.save_answers(batch.id, [answered], edited_by=user.email if approved else "")
    events.record(
        user,
        events.ANSWER_EDITED,
        subject_type=batches.SUBJECT,
        subject_id=batch.id,
        question_id=question_id,
        approved=approved,
    )

    entry_id = _memory_id(batch.id, question_id)
    if not approved:
        answer_memory.remove(entry_id, user.team_id)
        return ""
    if not by_hand:
        return ""

    question = next(q for q in batch.form.questions if q.id == question_id)
    # Remembered in the questionnaire's memory: its product's, or the shared one
    # for General (plan 023). That product is fixed (TD-040), so an entry is in
    # another memory only after a Move on the memory page; approved again, it comes back.
    previous = answer_memory.get(entry_id, user.team_id)
    if previous is not None and previous.product_id != batch.product_id:
        answer_memory.remove(entry_id, user.team_id)
    answer_memory.record(
        question.text,
        # What went into the cell, not the longest thing on the record. A
        # questionnaire filled in briefly is answered with the brief text, and
        # somebody who shortens one by hand has written *that* -- remembering
        # the untouched full draft instead put the model's own words in the
        # memory under a person's name, which is the whole thing this gate
        # exists to prevent.
        written_text(answered, batch.detail),
        entry_id=entry_id,
        section=question.section,
        from_file=batch.source_name,
        origin="approved",
        approved_by=user.email,
        team_id=user.team_id,
        product_id=batch.product_id,
    )
    events.record(
        user,
        events.MEMORY_ADDED,
        subject_type=SUBJECT_MEMORY,
        subject_id=entry_id,
        question=question.text[:200],
        batch_id=batch.id,
    )
    return entry_id


SUBJECT_MEMORY = "memory_entry"


def fill(
    user: User,
    batch_id: str,
    destination: Path | None = None,
    *,
    include_unreviewed: bool = False,
    unreviewed_ids: Collection[str] | None = None,
) -> Filled:
    """Write the answers into a copy of the original questionnaire.

    Status columns are answered from the file's own dropdown, matched to what
    the answer says. Evidence columns are left blank, which is the default the
    cyber-team asked for; an instruction can fill them, and that is a later
    tool rather than a hidden setting here.

    `include_unreviewed` writes the answers the gate holds as well; `unreviewed_ids` narrows
    that to the ones a person was shown and agreed to ("Write them in anyway"), so an answer
    held since then stays out rather than going in under a count that did not include it.
    """
    from src import forms

    batch = _require(user, batch_id, reading=True)  # the customer's file only: a deleted product's too
    if not batch.exists:
        raise ToolError(
            f"The uploaded file for {batch.source_name!r} is no longer on the server. Upload it again to fill it in."
        )

    answered = batches.answers(batch.id)
    edits = batches.edited_by(batch.id)
    values: dict[str, str] = {}
    blank: dict[str, str] = {}
    held: dict[str, str] = {}
    anyway: list[str] = []  # held, and written all the same

    for question in batch.form.questions:
        result = answered.get(question.id)
        # A question deliberately left blank is written -- with nothing in it.
        # The file may already hold last year's answer, and "leave this blank"
        # has to be able to clear it; skipping the question would leave the old
        # words in place, which is the opposite of what was asked.
        if result is not None and result.confidence_reason == BLANKED:
            for target in question.writable:
                if target.role is not Role.EVIDENCE:
                    values[target.id] = ""
            continue
        if not _has_answer(result):
            continue
        # Confidence is a gate, not a decoration. Every answer that
        # contradicted the security team scored at or below 0.50 and was
        # flagged; none of them should reach a customer unread.
        allowed, because = ready_to_write(result, edits.get(question.id, ""))
        if not allowed:
            held[question.id] = because
            if not include_unreviewed or (unreviewed_ids is not None and question.id not in unreviewed_ids):
                continue
            anyway.append(question.id)
        for target in question.writable:
            if target.role is Role.EVIDENCE:
                blank[target.id] = "evidence columns are left blank by default"
                continue
            if target.role is Role.STATUS:
                # The verdict is read off the full answer whatever length is
                # being written: a condensed answer can lose the sentence the
                # status was picked from, and the dropdown must not change
                # because somebody chose shorter prose.
                choice = status_map.choose(result.answer, target.vocabulary)
                if choice.chosen:
                    values[target.id] = choice.value
                else:
                    blank[target.id] = choice.because
                continue
            # As text a cell can show: the drafter's Markdown went into the
            # customer's file as literal asterisks.
            values[target.id] = to_cell_text(written_text(result, batch.detail))

    destination = destination or _filled_path(batch)
    destination.parent.mkdir(parents=True, exist_ok=True)
    report = forms.write(batch.source_path, destination, values)
    kept_out = {question_id: why for question_id, why in held.items() if question_id not in anyway}
    events.record(
        user,
        events.FILE_FILLED,
        subject_type=batches.SUBJECT,
        subject_id=batch.id,
        written=report.written,
        created=len(report.created),
        replaced=len(report.replaced),
        left_blank=len(blank),
        # What the gate held, and which went in anyway ("Write them in anyway", TD-052).
        held_back=len(held),
        include_unreviewed=include_unreviewed,
        written_anyway=anyway,  # question ids, for `inspect fills`
    )
    return Filled(
        path=destination,
        written=report.written,
        created=len(report.created),
        replaced=len(report.replaced),
        skipped=report.skipped,
        blank=blank,
        held_back=kept_out,
        written_anyway=anyway,
        intact=report.intact,
        because=nothing_written(batch.form, answered, kept_out) if not report.written else "",
    )


def _filled_path(batch: Batch) -> Path:
    """Where a filled copy goes: under this batch, never over the original.

    The original is what a person compares against and what a re-run starts
    from, so answering never consumes it.

    A directory per batch rather than a sibling file, because a batch is what
    the answers belong to and two of them can share one source: a teammate who
    opens the same questionnaire gets their own batch, and both filling into
    `<name> - answered.xlsx` beside the upload meant the second one to press the
    button silently replaced the first one's file, which is then what both of
    them download. The name inside the directory stays the plain one, so the
    download is still `<name> - answered.xlsx`.
    """
    source = batch.source_path
    return settings.filled_dir / batch.id / f"{source.stem} - answered{source.suffix}"


async def search(
    query: str,
    mode: str = "hybrid",
    limit: int = 8,
    *,
    team_id: str | None = None,
    product_id: str = "",
) -> dict:
    """Look something up in a team's indexed policies, and a product's beside them, without touching a batch."""
    return await service.search_knowledge(query, mode=mode, limit=limit, team_id=team_id, product_id=product_id)


def _working_copy(existing: AnsweredQuestion | None, question: FormQuestion) -> AnsweredQuestion:
    """The stored answer to change, copied, or an empty one for a question never answered."""
    if existing:
        return existing.model_copy(deep=True)
    return AnsweredQuestion(question=_as_question(question), answer="", confidence=0.0)


def _as_question(question: FormQuestion) -> Question:
    """A detected question, in the shape the answering pipeline takes.

    The two models are deliberately separate: one describes a place in a
    document, the other a thing to answer. This is the only seam between them.
    """
    return Question(
        id=question.id,
        text=question.text,
        section=question.section or None,
        language=question.language,
    )


# ---------------------------------------------------------------------------
# Correcting what detection decided
# ---------------------------------------------------------------------------


def column_roles(user: User, batch_id: str) -> list[dict]:
    """The column each sheet's answers go into, as a person can change it.

    Derived from the questions rather than stored separately, so what is shown
    is what will actually be written. Detection proposes these; this is the
    other half of that sentence.
    """
    batch = _require(user, batch_id, reading=True)
    if batch.form.format != "xlsx":
        return []

    seen: dict[str, dict[str, str]] = {}
    for question in batch.form.questions:
        for role, target in question.targets.items():
            if "!" not in target.id:
                continue
            sheet, ref = target.id.rsplit("!", 1)
            column = "".join(c for c in ref if c.isalpha())
            seen.setdefault(sheet, {})[column] = role.value

    out = []
    for part in batch.form.parts:
        if not part.used or part.name not in seen:
            continue
        columns = seen[part.name]
        labels = {
            "".join(c for c in t.id.rsplit("!", 1)[1] if c.isalpha()): t.label
            for q in batch.form.questions
            for t in q.targets.values()
            if t.id.startswith(f"{part.name}!")
        }
        out.append(
            {
                "sheet": part.name,
                "columns": [
                    {"column": column, "role": role, "label": labels.get(column, "")}
                    for column, role in sorted(columns.items())
                ],
                "findings": [
                    {"subject": f.subject, "verdict": f.verdict, "because": f.because, "confident": f.confident}
                    for f in part.findings
                ],
            }
        )
    return out


SET_BY = "set by "
"""Opens the reason on a column a person chose, so a later correction can tell
its own kind of finding from the detector's."""


def set_column_role(user: User, batch_id: str, sheet: str, column: str, role: str) -> dict:
    """Move a sheet's answers into a different column, or stop writing one.

    Rebuilds the targets for every question on that sheet, so the change takes
    effect everywhere at once -- a column is wrong for the whole sheet or not at
    all. Answers already written are kept; only where they will be *put* moves.
    """
    from src.forms.xlsx_package import Workbook

    batch = _require(user, batch_id)
    column = column.strip().upper()
    try:
        wanted = Role(role)
    except ValueError as bad:
        raise ToolError(f"{role!r} is not a role.") from bad
    if wanted not in WRITABLE and wanted is not Role.IGNORE:
        raise ToolError(f"Answers cannot be written to a {wanted.value} column.")

    form = batch.form.model_copy(deep=True)
    on_sheet = [q for q in form.questions if any(t.id.startswith(f"{sheet}!") for t in q.targets.values())]
    if not on_sheet:
        raise ToolError(f"No questions were found on {sheet!r}.")

    # The heading already known for this column, from whichever target used to
    # sit there. Dropping it left the picker offering a bare "column D", which
    # is the one thing a person correcting a column needs to recognise it by.
    label = next(
        (
            t.label
            for q in on_sheet
            for t in q.targets.values()
            if t.id.startswith(f"{sheet}!")
            and "".join(c for c in t.id.rsplit("!", 1)[1] if c.isalpha()) == column
            and t.label
        ),
        "",
    )
    vocabulary: list[str] = []
    if batch.exists and wanted is Role.STATUS:
        with Workbook(batch.source_path) as workbook:
            page = workbook.get(sheet)
            if page is not None:
                vocabulary = workbook.vocabulary_for(page, column)

    for question in on_sheet:
        row = next(
            "".join(c for c in t.id.rsplit("!", 1)[1] if c.isdigit())
            for t in question.targets.values()
            if t.id.startswith(f"{sheet}!")
        )
        # Drop whatever used to hold this role, and whatever used to live in
        # this column -- otherwise a swap leaves the old assignment behind.
        question.targets = {
            existing_role: target
            for existing_role, target in question.targets.items()
            if existing_role is not wanted and "".join(c for c in target.id.rsplit("!", 1)[1] if c.isalpha()) != column
        }
        if wanted is not Role.IGNORE:
            question.targets[wanted] = Target(
                id=f"{sheet}!{column}{row}",
                role=wanted,
                label=label,
                vocabulary=vocabulary,
            )

    # The report is what is known about the file, so a correction belongs in it.
    # Left alone, it went on saying "column D: answer" directly above a picker
    # reading "evidence", and the person who had just changed it could not tell
    # which of the two the fill would follow.
    for part in form.parts:
        if part.name != sheet:
            continue
        subject = f"column {column}"
        previous = next((f for f in part.findings if f.subject == subject), None)
        # Only detection's own reading is worth quoting back. A second
        # correction that said "read from the file as evidence" would be
        # crediting the file with the last person's choice.
        detected = previous.verdict if previous is not None and not previous.because.startswith(SET_BY) else ""
        part.findings = [f for f in part.findings if f.subject != subject]
        part.findings.append(
            Finding(
                subject=subject,
                verdict=wanted.value,
                because=f"{SET_BY}{user.email}" + (f", read from the file as {detected}" if detected else ""),
                confident=True,
            )
        )

    _save_form(batch, form)
    events.record(
        user,
        events.ROLES_CORRECTED,
        subject_type=batches.SUBJECT,
        subject_id=batch.id,
        sheet=sheet,
        column=column,
        role=wanted.value,
    )
    return inspect(user, batch_id)


def set_questions(user: User, batch_id: str, changes: list[dict]) -> dict:
    """Set questions aside, bring them back, or correct how one is worded.

    Detection over-reports on purpose, so unticking a row is the ordinary case
    rather than an error path. Set aside rather than deleted: the row is still
    there when somebody sees what the sheet looks like filled in and wants it
    back.
    """
    batch = _require(user, batch_id)
    form = batch.form.model_copy(deep=True)
    by_id = {question.id: question for question in form.questions}

    touched = 0
    for change in changes:
        question = by_id.get(str(change.get("id", "")))
        if question is None:
            continue
        if "skip" in change:
            question.skip = bool(change["skip"])
        if change.get("text", "").strip():
            question.text = " ".join(str(change["text"]).split())
        touched += 1

    if not touched:
        raise ToolError("None of those questions are in this questionnaire.")

    _save_form(batch, form)
    events.record(
        user,
        events.QUESTIONS_CORRECTED,
        subject_type=batches.SUBJECT,
        subject_id=batch.id,
        changed=touched,
        set_aside=sum(1 for q in form.questions if q.skip),
    )
    return inspect(user, batch_id)


def _save_form(batch: Batch, form: DetectedForm) -> None:
    """Write a corrected reading back over the stored one."""
    conn = store.connect()
    conn.execute(
        "UPDATE form_batches SET detected = ?, updated_at = ? WHERE batch_id = ?",
        (form.model_dump_json(), store.utcnow(), batch.id),
    )
    conn.commit()
