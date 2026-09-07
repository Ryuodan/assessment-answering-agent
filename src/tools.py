"""The operations the interface performs, and the agent will later call.

Everything a person can do to a questionnaire is one of these, and each is a
plain function taking a user and returning data -- no request, no response, no
HTML. That is deliberate: the agent in a later phase chooses *which* of these to
call and with what arguments, and the less it can do beyond calling them, the
less there is to go wrong. Building them first also means they can be tested
with fixed inputs, before anything non-deterministic is choosing between them.

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
lives here rather than in the agent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import asyncio

from src.config import settings
from src import batches, events, progress, rewrite, service
from src.batches import Batch
from src.forms import status as status_map
from src.forms.model import WRITABLE, DetectedForm, Finding, FormQuestion, Role, Target
from src.identity import User
from src.models import AnsweredQuestion, Question

logger = logging.getLogger(__name__)


class ToolError(Exception):
    """An operation could not be performed. The message is safe to show."""


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
    """Skip questions that already have an answer.

    The default for re-answering a partly finished file: an upload of last
    year's submission should not silently overwrite reviewed work.
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
            if self.unanswered_only and _has_answer(answered.get(question.id)):
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

    @property
    def nothing_matched(self) -> bool:
        return self.attempted == 0


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

    intact: bool = True


# ---------------------------------------------------------------------------
# The operations
# ---------------------------------------------------------------------------


def open_form(user: User, path: Path, *, strategy: str | None = None) -> Batch:
    """Read an uploaded questionnaire and record it as a batch.

    `strategy` is one of `forms.reading.STRATEGIES` and decides how hard to
    work at understanding the file -- the rules alone, the rules plus a model
    call for each sheet they could not read, or an agent that explores it. It
    defaults to the configured one, and the choice is a cost decision rather
    than a correctness one: see `src.forms.reading`.

    Detection failures reach the caller as `forms.FormatError`, which already
    carries a message safe to show whoever uploaded the file.
    """
    from src.forms import reading

    chosen = strategy or settings.detection_strategy
    result = reading.read(path, chosen)
    form = result.form
    batch = batches.create(user, path, form)
    events.record(
        user, events.FORM_OPENED, subject_type=batches.SUBJECT, subject_id=batch.id,
        source_name=form.source_name, questions=len(form.questions),
        already_answered=form.answered_count,
        strategy=chosen, seconds=round(result.seconds, 2), tokens=result.tokens,
    )
    return batch


def _require(user: User, batch_id: str) -> Batch:
    batch = batches.load(batch_id, team_id=user.team_id)
    if batch is None:
        raise ToolError(f"No questionnaire {batch_id!r}.")
    return batch


def inspect(user: User, batch_id: str, scope: Scope | None = None) -> dict:
    """Everything about a batch: what was found, what is answered, what is not.

    Read-only, and the only operation the interface needs to render a batch.
    """
    batch = _require(user, batch_id)
    answered = batches.answers(batch.id)
    edits = batches.edited_by(batch.id)
    selected = {q.id for q in (scope or Scope()).select(batch.form, answered)}

    questions = []
    for question in batch.form.questions:
        result = answered.get(question.id)
        questions.append({
            "id": question.id,
            "number": question.number,
            "text": question.text,
            "section": question.section,
            "language": question.language,
            "location": question.location,
            "skip": question.skip,
            "selected": question.id in selected,
            "answer": result.answer if result else "",
            "confidence": result.confidence if result else 0.0,
            "needs_review": result.needs_review if result else False,
            "error": result.error if result else "",
            "citations": result.citations if result else [],
            "edited_by": edits.get(question.id, ""),
            # The whole answer, so the interface can show the sources it came
            # from and why the reviewer flagged it. A confidence number with no
            # evidence behind it is not something anyone can check.
            "answered": result.model_dump() if result else None,
            "targets": [
                {
                    "id": target.id, "role": target.role.value, "label": target.label,
                    "vocabulary": target.vocabulary, "existing": target.existing,
                }
                for target in question.writable
            ],
        })

    return {
        "id": batch.id,
        "source_name": batch.source_name,
        "format": batch.form.format,
        "file_present": batch.exists,
        "created_at": batch.created_at,
        "updated_at": batch.updated_at,
        "counts": {
            "questions": len(batch.form.questions),
            "answered": sum(1 for q in batch.form.questions if _has_answer(answered.get(q.id))),
            "needs_review": sum(
                1 for q in batch.form.questions
                if (answered.get(q.id) and answered[q.id].needs_review)
            ),
            "failed": sum(
                1 for q in batch.form.questions
                if (answered.get(q.id) and answered[q.id].error)
            ),
        },
        "parts": [
            {"name": part.name, "kind": part.kind, "questions": part.questions,
             "used": part.used,
             "findings": [
                 {"subject": f.subject, "verdict": f.verdict,
                  "because": f.because, "confident": f.confident}
                 for f in part.findings
             ]}
            for part in batch.form.parts
        ],
        "warnings": batch.form.warnings,
        "questions": questions,
    }


async def answer(
    user: User,
    batch_id: str,
    scope: Scope | None = None,
    *,
    run_id: str = "",
) -> Outcome:
    """Answer a selection of a batch's questions.

    Always the same prompt. How an answer should be worded is `revise`'s job,
    over an answer that already exists -- see the note on the drafting node for
    what measuring the two ways showed.

    Each question is answered in its own language: the samples mix an Arabic
    question into an English form, and the question's own language is the one
    the assessor asked in.
    """
    batch = _require(user, batch_id)
    scope = scope or Scope()
    existing = batches.answers(batch.id)
    chosen = scope.select(batch.form, existing)

    outcome = Outcome(batch_id=batch.id, attempted=len(chosen), scope=scope.describe())
    if not chosen:
        return outcome

    results = await service.answer_questions(
        [_as_question(question) for question in chosen],
        run_id=run_id or batch.id,
    )
    batches.save_answers(batch.id, results)

    outcome.answered = sum(1 for r in results if not r.error)
    outcome.failed = sum(1 for r in results if r.error)
    outcome.needs_review = sum(1 for r in results if r.needs_review and not r.error)
    events.record(
        user, events.BATCH_ANSWERED, subject_type=batches.SUBJECT, subject_id=batch.id,
        scope=outcome.scope, attempted=outcome.attempted,
        answered=outcome.answered, failed=outcome.failed,
    )
    return outcome


async def revise(
    user: User, batch_id: str, instruction: str, scope: Scope | None = None, *, run_id: str = ""
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
    """
    if not instruction.strip():
        raise ToolError("Say how the answers should change.")

    batch = _require(user, batch_id)
    existing = batches.answers(batch.id)
    scope = scope or Scope()
    chosen = [
        question for question in scope.select(batch.form, existing)
        if _has_answer(existing.get(question.id))
    ]

    outcome = Outcome(batch_id=batch.id, attempted=len(chosen), scope=scope.describe())
    if not chosen:
        return outcome

    # Reworded, not re-answered. Running the pipeline again with the instruction
    # as a style would re-retrieve and re-review, so "make it shorter" could come
    # back saying something different -- which is not what revise means. One call
    # over the answer and the sources it already used keeps the facts, the
    # citations and the clause a reader would go and check.
    progress.start(run_id or batch.id, stage="rewriting")
    progress.set_total(run_id or batch.id, len(chosen))
    try:
        async def one(question: FormQuestion) -> AnsweredQuestion:
            try:
                return await rewrite.rewrite(existing[question.id], instruction)
            finally:
                progress.advance(run_id or batch.id)

        results = list(await asyncio.gather(*(one(q) for q in chosen)))
    finally:
        progress.finish(run_id or batch.id)

    batches.save_answers(batch.id, results)

    outcome.answered = sum(1 for r in results if not r.error)
    outcome.failed = sum(1 for r in results if r.error)
    outcome.needs_review = sum(1 for r in results if r.needs_review and not r.error)
    events.record(
        user, events.BATCH_REVISED, subject_type=batches.SUBJECT, subject_id=batch.id,
        scope=outcome.scope, instruction=instruction, attempted=outcome.attempted,
    )
    return outcome


def set_answer(user: User, batch_id: str, question_id: str, text: str) -> None:
    """Replace one answer with words a person wrote.

    Recorded as an edit with their name on it. This is one of only three ways
    answer text is ever written -- the other two are `answer` and `revise` --
    and the agent, when it arrives, will have none of its own.
    """
    batch = _require(user, batch_id)
    question = next((q for q in batch.form.questions if q.id == question_id), None)
    if question is None:
        raise ToolError(f"No question {question_id!r} in this questionnaire.")

    existing = batches.answers(batch.id).get(question_id)
    previous = existing.answer if existing else ""
    answered = existing.model_copy(deep=True) if existing else AnsweredQuestion(
        question=_as_question(question), answer="", confidence=0.0,
    )
    answered.answer = text
    answered.needs_review = False
    answered.error = ""
    answered.confidence = 1.0
    answered.confidence_reason = "written by hand"

    batches.save_answers(batch.id, [answered], edited_by=user.email)
    events.record(
        user, events.ANSWER_EDITED, subject_type=batches.SUBJECT, subject_id=batch.id,
        question_id=question_id, was=previous[:400], now=text[:400],
    )


def fill(user: User, batch_id: str, destination: Path | None = None) -> Filled:
    """Write the answers into a copy of the original questionnaire.

    Status columns are answered from the file's own dropdown, matched to what
    the answer says. Evidence columns are left blank, which is the default the
    cyber-team asked for; an instruction can fill them, and that is a later
    tool rather than a hidden setting here.
    """
    from src import forms

    batch = _require(user, batch_id)
    if not batch.exists:
        raise ToolError(
            f"The uploaded file for {batch.source_name!r} is no longer on the server. "
            "Upload it again to fill it in."
        )

    answered = batches.answers(batch.id)
    values: dict[str, str] = {}
    blank: dict[str, str] = {}

    for question in batch.form.questions:
        result = answered.get(question.id)
        if not _has_answer(result):
            continue
        for target in question.writable:
            if target.role is Role.EVIDENCE:
                blank[target.id] = "evidence columns are left blank by default"
                continue
            if target.role is Role.STATUS:
                choice = status_map.choose(result.answer, target.vocabulary)
                if choice.chosen:
                    values[target.id] = choice.value
                else:
                    blank[target.id] = choice.because
                continue
            values[target.id] = result.answer

    destination = destination or _filled_path(batch)
    report = forms.write(batch.source_path, destination, values)
    events.record(
        user, events.FILE_FILLED, subject_type=batches.SUBJECT, subject_id=batch.id,
        written=report.written, created=len(report.created),
        replaced=len(report.replaced), left_blank=len(blank),
    )
    return Filled(
        path=destination,
        written=report.written,
        created=len(report.created),
        replaced=len(report.replaced),
        skipped=report.skipped,
        blank=blank,
        intact=report.intact,
    )


def _filled_path(batch: Batch) -> Path:
    """Where a filled copy goes. Beside the upload, never over it.

    The original is what a person compares against and what a re-run starts
    from, so answering never consumes it.
    """
    source = batch.source_path
    return source.with_name(f"{source.stem} - answered{source.suffix}")


async def search(query: str, mode: str = "hybrid", limit: int = 8) -> dict:
    """Look something up in the indexed policies, without touching a batch."""
    return await service.search_knowledge(query, mode=mode, limit=limit)


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
    batch = _require(user, batch_id)
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
            for q in batch.form.questions for t in q.targets.values()
            if t.id.startswith(f"{part.name}!")
        }
        out.append({
            "sheet": part.name,
            "columns": [
                {"column": column, "role": role, "label": labels.get(column, "")}
                for column, role in sorted(columns.items())
            ],
            "findings": [
                {"subject": f.subject, "verdict": f.verdict,
                 "because": f.because, "confident": f.confident}
                for f in part.findings
            ],
        })
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
    on_sheet = [q for q in form.questions if any(
        t.id.startswith(f"{sheet}!") for t in q.targets.values())]
    if not on_sheet:
        raise ToolError(f"No questions were found on {sheet!r}.")

    # The heading already known for this column, from whichever target used to
    # sit there. Dropping it left the picker offering a bare "column D", which
    # is the one thing a person correcting a column needs to recognise it by.
    label = next(
        (t.label for q in on_sheet for t in q.targets.values()
         if t.id.startswith(f"{sheet}!")
         and "".join(c for c in t.id.rsplit("!", 1)[1] if c.isalpha()) == column
         and t.label),
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
            for t in question.targets.values() if t.id.startswith(f"{sheet}!")
        )
        # Drop whatever used to hold this role, and whatever used to live in
        # this column -- otherwise a swap leaves the old assignment behind.
        question.targets = {
            existing_role: target
            for existing_role, target in question.targets.items()
            if existing_role is not wanted
            and "".join(c for c in target.id.rsplit("!", 1)[1] if c.isalpha()) != column
        }
        if wanted is not Role.IGNORE:
            question.targets[wanted] = Target(
                id=f"{sheet}!{column}{row}", role=wanted, label=label,
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
        detected = (
            previous.verdict
            if previous is not None and not previous.because.startswith(SET_BY)
            else ""
        )
        part.findings = [f for f in part.findings if f.subject != subject]
        part.findings.append(Finding(
            subject=subject,
            verdict=wanted.value,
            because=f"{SET_BY}{user.email}"
                    + (f", read from the file as {detected}" if detected else ""),
            confident=True,
        ))

    _save_form(batch, form)
    events.record(
        user, events.ROLES_CORRECTED, subject_type=batches.SUBJECT, subject_id=batch.id,
        sheet=sheet, column=column, role=wanted.value,
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
        user, events.QUESTIONS_CORRECTED, subject_type=batches.SUBJECT,
        subject_id=batch.id, changed=touched,
        set_aside=sum(1 for q in form.questions if q.skip),
    )
    return inspect(user, batch_id)


def _save_form(batch: Batch, form: DetectedForm) -> None:
    """Write a corrected reading back over the stored one."""
    from src import store

    conn = store.connect()
    conn.execute(
        "UPDATE form_batches SET detected = ?, updated_at = ? WHERE batch_id = ?",
        (form.model_dump_json(), store.utcnow(), batch.id),
    )
    conn.commit()
