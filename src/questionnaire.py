"""One questionnaire as its owner sees it: the gate every operation passes, what the pages draw, and deleting it.

Moved from `src/tools.py` (plan 033) to make room there, which re-exports what
its callers use: `tools.inspect`, `tools._require` and `tools._memory_id` are
the names the interface, the assistant and the tests have always used.

A list -- typed questions, or a PDF's or a Word text's (`forms.model.LIST`,
`src/lists.py`) -- is a questionnaire like a file's, with no file to write
into: everything here works on it, and filling it is refused (`refuse_list`).
"""

from __future__ import annotations

from typing import Any

from src import answer_memory, batches, busy, events, products, retention
from src.batches import Batch
from src.errors import NothingToFill, QuestionnaireBusy, QuestionnaireNotFound
from src.forms.model import LIST
from src.identity import User
from src.logs import get_logger
from src.selection import (
    APPROVED,
    BLANKED,
    Scope,
    _has_answer,
    _settled,
    length_of,
    ready_to_write,
    written_by_a_person,
)

logger = get_logger(__name__)


def require(user: User, batch_id: str, *, reading: bool = False) -> Batch:
    """The one gate every operation on a questionnaire passes through.

    Somebody else's questionnaire is "no questionnaire": the person who
    uploaded it owns it and its answers. A deleted product's is kept to be
    read and filled, `reading`, and nothing else (plan 027); so is one another
    run is answering, until it ends (`busy`, plan 029).
    """
    batch = batches.load(batch_id, team_id=user.team_id, actor_email=user.email)
    if batch is None:
        raise QuestionnaireNotFound(f"No questionnaire {batch_id!r}.")
    if not reading:
        products.refuse_deleted(user.team_id, batch.product_id)
        busy.refuse(batch.id)
    return batch


def inspect(user: User, batch_id: str, scope: Scope | None = None) -> dict[str, Any]:
    """Everything about a batch: what was found, what is answered, what is not.

    Read-only, and the only operation the interface needs to render a batch.
    """
    batch = require(user, batch_id, reading=True)
    answered = batches.answers(batch.id)
    edits = batches.edited_by(batch.id)
    selected = {q.id for q in (scope or Scope()).select(batch.form, answered)}
    # One query for the whole questionnaire: approving has a second effect, and
    # a card that cannot say whether it happened is a button working in silence.
    remembered = answer_memory.ids_from_batch(batch.id, user.team_id)

    questions = []
    for question in batch.form.questions:
        result = answered.get(question.id)
        ready, held_because = ready_to_write(result, edits.get(question.id, ""))
        questions.append(
            {
                "id": question.id,
                "number": question.number,
                "text": question.text,
                "section": question.section,
                "language": question.language,
                "location": question.location,
                "skip": question.skip,
                "selected": question.id in selected,
                "existing": question.existing_answer,
                # Deliberately empty, as opposed to not answered yet. Opposite
                # states that look identical from the outside.
                "blanked": bool(result and result.confidence_reason == BLANKED),
                # Whether `fill` would write this, and why not. The card shows the
                # reason, because "held back" on its own is a wall.
                "approved": bool(result and result.confidence_reason == APPROVED),
                # Whether this answer's wording is in the answer memory, which is
                # true only of answers somebody wrote and then approved.
                "remembered": memory_id(batch.id, question.id) in remembered,
                "by_hand": bool(result and written_by_a_person(result)),
                # Set aside is decided about the question rather than the answer:
                # whatever state the answer is in, nothing is written for it. This
                # said "will be written" of a set-aside answer, and the cards beside
                # the assistant drew it exactly like the others.
                "will_be_written": ready and not question.skip,
                "held_back_because": "" if question.skip else held_because,
                "answer": result.answer if result else "",
                "brief": result.brief if result else "",
                "prefer": result.prefer if result else "",
                "length": length_of(result, batch.detail) if result else batch.detail,
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
                        "id": target.id,
                        "role": target.role.value,
                        "label": target.label,
                        "vocabulary": target.vocabulary,
                        "existing": target.existing,
                    }
                    for target in question.writable
                ],
            }
        )

    return {
        "id": batch.id,
        "source_name": batch.source_name,
        "format": batch.form.format,
        "detail": batch.detail,
        "product_id": batch.product_id,
        "read_only": batch.product_id in products.deleted(user.team_id),  # a deleted product's (plan 027)
        "file_present": batch.exists,
        "created_at": batch.created_at,
        "updated_at": batch.updated_at,
        # Last opened or changed, and the day it is kept until; None when nothing is deleted (plan 033).
        "used_at": batch.used_at,
        "kept_until": retention.kept_until(batch.used_at),
        "running": busy.state(batch.id),  # being answered now, and how far it has got (plan 029)
        "counts": {
            "questions": len(batch.form.questions),
            "answered": sum(1 for q in batch.form.questions if _has_answer(answered.get(q.id))),
            # Answers the file arrived with. Uploading last year's completed
            # submission and being told it has none is a lie the interface used
            # to tell, because this count only ever looked at what we wrote.
            "already_in_file": batch.form.answered_count,
            "needs_review": sum(
                1 for q in batch.form.questions if (answered.get(q.id) and answered[q.id].needs_review)
            ),
            "held_back": sum(
                1
                for q in batch.form.questions
                if _has_answer(answered.get(q.id))
                and not q.skip
                and not ready_to_write(answered.get(q.id), edits.get(q.id, ""))[0]
            ),
            "set_aside": sum(1 for q in batch.form.questions if q.skip),
            # Work still to do, counted the way `answer` decides it: not answered
            # here, not answered in the file, not left blank on purpose, and not
            # set aside. The question count minus our own answers called the
            # file's answers and every set-aside row "still blank".
            "still_blank": sum(1 for q in batch.form.questions if not q.skip and not _settled(answered.get(q.id), q)),
            "failed": sum(1 for q in batch.form.questions if (answered.get(q.id) and answered[q.id].error)),
        },
        "parts": [
            {
                "name": part.name,
                "kind": part.kind,
                "questions": part.questions,
                "used": part.used,
                "findings": [
                    {"subject": f.subject, "verdict": f.verdict, "because": f.because, "confident": f.confident}
                    for f in part.findings
                ],
            }
            for part in batch.form.parts
        ],
        "warnings": batch.form.warnings,
        "questions": questions,
    }


def memory_id(batch_id: str, question_id: str) -> str:
    """One entry per approved question, so approving twice does not remember twice.

    Derived from the questionnaire and the question rather than random, because
    the same answer gets approved, corrected and approved again — and three
    near-identical entries in the memory is three chances to retrieve the one
    that was wrong.
    """
    return f"approved::{batch_id}::{question_id}"


def refuse_list(batch: Batch) -> None:
    """`nothing_to_fill` for a list: it has no file to write into, so its answers are downloaded instead."""
    if batch.form.format == LIST:
        raise NothingToFill(
            "This questionnaire is a list of questions, with no file to write the answers into. "
            "Download the answers instead, as PDF, Word, CSV or JSON."
        )


def fillable(user: User, batch_id: str) -> Batch:
    """The questionnaire to fill or whose filled copy to download: a deleted product's too, never a list."""
    batch = require(user, batch_id, reading=True)
    refuse_list(batch)
    return batch


def delete(user: User, batch_id: str) -> dict[str, int]:
    """Delete one of the caller's questionnaires: its answers, its upload and its filled copy (plan 033).

    A deleted product's too: it is kept to be read, and its owner may still
    want it gone. Refused with `questionnaire_busy` while it is being answered,
    or while a chat turn runs in a conversation about it. The conversation
    keeps its messages and loses its answers panel; the answer memory keeps
    what approving taught it. The event has counts, never content.
    """
    batch = require(user, batch_id, reading=True)
    if retention.in_a_running_chat(batch.id):
        raise QuestionnaireBusy("A chat is working with this questionnaire right now. Wait until it finishes.")
    with busy.hold(batch.id, "deleting"):  # refused if a run holds it; and none starts meanwhile
        answers = len(batches.answers(batch.id))
        files = retention.remove_questionnaire(batch)
    events.record(
        user,
        events.QUESTIONNAIRE_DELETED,
        subject_type=batches.SUBJECT,
        subject_id=batch.id,
        format=batch.form.format,  # "list" for a list
        questions=len(batch.form.questions),
        answers=answers,
        files=files,
    )
    logger.info("questionnaire.deleted", batch_id=batch.id, answers=answers, files=files)
    return {"answers": answers, "files": files}
