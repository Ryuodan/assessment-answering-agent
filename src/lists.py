"""A list of questions, kept as a questionnaire with no file to write into (plan 033).

Typed questions, and the questions read out of a PDF or a Word file's text,
were answered on the page and kept nowhere a page could read: a reload lost
them, and their answers went to `runs`, which no page lists. Now a list is a
questionnaire like a file's (`forms.model.LIST`): owned by whoever made it,
for the product chosen then (fixed, D-018), listed with the others, opened by
its address, answered with progress and the running guard, and every card
action works on it. There is nothing to fill (`questionnaire.refuse_list`):
its answers are downloaded instead.

A list's questions are numbered from 1, in the order given. A PDF's or a Word
file's keep the section, the type and the options extraction read, which the
drafter uses; a typed one is free text in the language it is written in.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from src import batches, events, preferences, products, retention, service, uploads
from src.batches import Batch
from src.errors import Invalid, Unprocessable
from src.extraction import detect_question_language
from src.forms.model import LIST, DetectedForm, FormQuestion, Part
from src.identity import User
from src.models import Question

MAX_QUESTIONS = 1000
"""More than any questionnaire seen; a list longer than this is a mistake, not work."""

MAX_LENGTH = 4000
"""Characters in one question, as when a question's wording is corrected."""

TYPED = "Typed questions"
"""A typed list's name when none is given."""


def _name(name: str, fallback: str) -> str:
    cleaned = " ".join(name.split())[:200]
    return cleaned or fallback


def typed(texts: Sequence[str]) -> list[Question]:
    """Typed questions as the pipeline takes them, blank ones left out; `Invalid` for one too long."""
    questions: list[Question] = []
    for text in texts:
        cleaned = " ".join(text.split())
        if not cleaned:
            continue
        if len(cleaned) > MAX_LENGTH:
            raise Invalid(f"A question can be at most {MAX_LENGTH} characters.", code="question_too_long")
        questions.append(Question(id=str(len(questions) + 1), text=cleaned, language=detect_question_language(cleaned)))
    return questions


def open_list(
    user: User, questions: Sequence[Question], *, name: str, product_id: str = "", source: Path | None = None
) -> Batch:
    """Keep `questions` as a questionnaire, for a product or General (""), and return it. Nothing is answered.

    `source` is the PDF or Word file they were read from, kept with the list
    and deleted with it; None for typed questions. The product is checked
    here, as `tools.open_form` checks it: another team's, or one deleted, is
    `product_not_found`.
    """
    product_id = products.chosen(user.team_id, product_id)
    if not questions:
        raise Invalid(
            "There are no questions to keep. Type at least one, or give a PDF or Word file.", code="no_questions_given"
        )
    if len(questions) > MAX_QUESTIONS:
        raise Invalid(f"A list can hold at most {MAX_QUESTIONS} questions.", code="too_many_questions")
    name = _name(name, source.name if source is not None else TYPED)
    form = DetectedForm(
        source_name=name,
        format=LIST,
        questions=[
            FormQuestion(
                id=str(number),
                number=str(number),
                text=question.text,
                section=question.section or "",
                language=question.language,
                question_type=question.question_type,
                options=question.options,
            )
            for number, question in enumerate(questions, start=1)
        ],
        parts=[Part(name=name, kind="questions", questions=len(questions))],
    )
    batch = batches.create(user, source, form, product_id)
    # Whoever opens it decides how long its answers start out, as for a file (`tools.open_form`).
    wanted = preferences.load(user.email).default_length
    if wanted != batch.detail:
        batches.set_detail(batch.id, wanted)
        batch = batches.load(batch.id, team_id=user.team_id, actor_email=user.email) or batch
    events.record(
        user,
        events.FORM_OPENED,
        subject_type=batches.SUBJECT,
        subject_id=batch.id,
        source_name=name,
        questions=len(form.questions),
        already_answered=0,
        strategy="list" if source is None else "text",
        detail=batch.detail,
        **({"product_id": product_id} if product_id else {}),
    )
    return batch


async def read_list(
    user: User, path: Path, *, name: str = "", product_id: str = "", also: Sequence[Question] = ()
) -> Batch:
    """The questions in a PDF or a Word file's text, then `also` (typed ones), kept as a list.

    Read the way `/api/assessments/extract` reads them. When nothing is found
    the upload goes again, unless another questionnaire reads that file, and
    the answer is `no_questions_found`.
    """
    _, found = await service.extract_assessment_questions(path)
    questions = [*found, *also]
    if not questions:
        if not retention.read_by_a_questionnaire(path):
            uploads.remove([path])
        raise Unprocessable(f"No questions could be extracted from '{path.name}'.", code="no_questions_found")
    return open_list(user, questions, name=name, product_id=product_id, source=path)
