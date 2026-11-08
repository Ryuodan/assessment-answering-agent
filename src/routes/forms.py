"""A questionnaire's routes, moving here from `src/api.py` (plan 029).

Filling came first, to make room in `src/api.py`; opening, listing and reading
one followed with plan 029's Stage 1, and downloading the filled copy with plan
033. Two routers, each included in `src/api.py` where its routes were, so the
order the routes are matched in, and the OpenAPI document, stay the same:
`opening` before answering, `router` (filling) after approving.

Plan 033 added a list's questionnaire (`POST /api/forms/list`), deleting one
(`DELETE /api/forms/{id}`), and the day each is kept until (`kept_until`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from src import batches, forms, lists, products, questionnaire, reading, retention, service, tools
from src.errors import NotFound
from src.identity import User
from src.logs import get_logger
from src.routes.auth import current_user
from src.routes.knowledge import check_suffix
from src.web import attachment_headers

logger = get_logger(__name__)

opening = APIRouter()
router = APIRouter()


class ApproveHeldRequest(BaseModel):
    """The held-back answers a person has just confirmed approving."""

    question_ids: list[str] = Field(min_length=1, max_length=2000)


@router.post("/api/forms/{batch_id}/approve-all")
def approve_all(batch_id: str, request: ApproveHeldRequest, user: User = Depends(current_user)) -> dict[str, Any]:
    """Release these held-back answers for writing, with the reviewer's name on them (plan 041).

    Nothing goes into the answer memory, whoever wrote the words. The ids are
    the ones the confirmation counted, so an answer that changed since then is
    not swept up. `approved` lists the ids that were.
    """
    approved = questionnaire.approve_held(user, batch_id, request.question_ids)
    return {**tools.inspect(user, batch_id), "approved": approved}


@opening.post("/api/forms")
async def open_questionnaire(
    file: UploadFile = File(...),
    product: str = Form(""),
    if_already_open: str = Form("new", pattern="^(new|ask)$"),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Read an uploaded questionnaire, for a `product` or General, and report what can be answered in it.

    Nothing is answered here. The point of the separation is that a person sees
    which sheets were used, which were skipped and why, and what each column was
    taken to be, *before* a run that costs minutes.

    `if_already_open="ask"`: when this person already has questionnaires read
    from a file with exactly these bytes, nothing is saved, read or created,
    and the answer is `{"already_open": [...]}`, last changed first, for them to
    open one or start fresh (plan 029, 1.2). "new", the default, opens a new
    questionnaire whatever there is, as it always did.
    """
    # Checked against what `forms` can read, not against the knowledge base's
    # list: the two accept different things. Policies come in as PDF or Word;
    # questionnaires are mostly spreadsheets, which the knowledge-base check
    # would have refused before the parser ever saw them.
    name = file.filename or "questionnaire"
    if Path(name).suffix.lower() not in forms.SUPPORTED:
        raise forms.UnsupportedForm(
            f"{Path(name).suffix or 'That file'} is not a questionnaire this can read. "
            f"Supported: {', '.join(forms.SUPPORTED)}."
        )
    product_id = products.chosen(user.team_id, product)  # before the file is kept
    content = await file.read()
    if if_already_open == "ask":
        matches = batches.same_upload(user.team_id, user.email, content)
        if matches:
            logger.info("forms.already_open", matches=len(matches))
            return {"already_open": matches}
    path = service.save_upload(name, content, user.team_id, owner=user.email)
    # In a thread: reading a workbook is a CPU-bound XML parse, and under the
    # assisted and agent strategies it is also a network call. Either way it is
    # not something to do on the event loop of a server answering other people.
    with reading.holding(path):  # not removed under the read by a deletion meanwhile (TD-078)
        batch = await run_in_threadpool(lambda: tools.open_form(user, path, product_id=product_id))
    return tools.inspect(user, batch.id)


@opening.post("/api/forms/list")
async def open_question_list(
    questions: list[str] = Form(default=[]),
    file: UploadFile | None = File(default=None),
    product: str = Form(""),
    name: str = Form("", max_length=200),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Keep typed questions, or a PDF's or a Word file's, as a questionnaire with no file to write into (plan 033).

    Multipart: one `questions` field per typed question, in order, and/or a
    `file` (PDF or Word) whose questions are read first. `product` as for a
    file, checked before anything is kept; `name` is what it is listed as (the
    file's name, or "Typed questions", when left out). Nothing is answered:
    the answer is the questionnaire as `GET /api/forms/{id}` returns it, with
    `format` "list". 400 `no_questions_given` when there is nothing to keep;
    422 `no_questions_found` when the file has no questions.
    """
    product_id = products.chosen(user.team_id, product)  # before the file is kept
    typed = lists.typed(questions)
    if file is None:
        batch = lists.open_list(user, typed, name=name, product_id=product_id)
        return tools.inspect(user, batch.id)
    check_suffix(file.filename or "")
    path = service.save_upload(file.filename or "questions", await file.read(), user.team_id, owner=user.email)
    with reading.holding(path):  # TD-078
        batch = await lists.read_list(user, path, name=name, product_id=product_id, also=typed)
    return tools.inspect(user, batch.id)


def _kept(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "kept_until": retention.kept_until(row["used_at"])}


@opening.get("/api/forms")
def list_questionnaires(user: User = Depends(current_user), limit: int = 25) -> dict[str, Any]:
    """One person's questionnaires, most recently used first, each with the day it is kept until (plan 033)."""
    return {"forms": [_kept(row) for row in batches.recent(user.team_id, actor_email=user.email, limit=limit)]}


@opening.get("/api/forms/{batch_id}")
def get_questionnaire(batch_id: str, user: User = Depends(current_user)) -> dict[str, Any]:
    """One questionnaire. Opening it is using it: its `kept_until` starts again from now (plan 033)."""
    questionnaire.require(user, batch_id, reading=True)
    batches.touch(batch_id)
    return tools.inspect(user, batch_id)


@opening.delete("/api/forms/{batch_id}")
def delete_questionnaire(batch_id: str, user: User = Depends(current_user)) -> dict[str, Any]:
    """Delete one of the caller's questionnaires, a list's or a deleted product's too, with its answers and files.

    409 `questionnaire_busy` while it is being answered, or while a chat turn
    runs in a conversation about it. A conversation about it still opens,
    without its answers.
    """
    removed = questionnaire.delete(user, batch_id)
    return {"deleted": batch_id, **removed}


class FillRequest(BaseModel):
    """How much of the questionnaire to write."""

    include_unreviewed: bool = False
    """Write answers nobody has confirmed as well.

    Off by default, and deliberately awkward to turn on. Measured against the
    security team's own answers, every answer that contradicted them came back
    flagged and under 0.50 confidence -- so the default holds back exactly the
    ones that would embarrass the organisation, and turning it off is a thing
    somebody should have to mean.
    """

    unreviewed_ids: list[str] | None = Field(default=None, max_length=2000)
    """With `include_unreviewed`: which held answers to write, by question id.

    The ones the person was shown and agreed to. An answer held since then
    stays out and is reported as held back, so a confirm that counted N never
    writes more than N (plan 029's review). Left out: every held answer.
    """


@router.post("/api/forms/{batch_id}/fill")
def fill_questionnaire(
    batch_id: str,
    request: FillRequest | None = None,
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Write the confirmed answers into a copy of the original, and report the rest."""
    include = bool(request and request.include_unreviewed)
    chosen = request.unreviewed_ids if request else None
    filled = tools.fill(user, batch_id, include_unreviewed=include, unreviewed_ids=chosen)
    return {
        "file": filled.path.name,
        "written": filled.written,
        "created": filled.created,
        "replaced": filled.replaced,
        "intact": filled.intact,
        "skipped": filled.skipped,
        "blank": filled.blank,
        "held_back": filled.held_back,
        "written_anyway": len(filled.written_anyway),
        "because": filled.because,
    }


OOXML_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@router.get("/api/forms/{batch_id}/file")
def download_filled_questionnaire(batch_id: str, user: User = Depends(current_user)) -> FileResponse:
    """The filled copy. Produced by `/fill`, which must have run first."""
    batch = questionnaire.fillable(user, batch_id)  # a deleted product's too (plan 027); a list's has none
    filled = tools._filled_path(batch)
    if not filled.exists():
        raise NotFound("Fill the questionnaire first.", code="filled_file_missing")
    # The real type, so a browser hands it to Excel or Word rather than to
    # whatever it does with an unknown blob; `attachment_headers` still forces
    # the download and carries the Arabic file name.
    return FileResponse(
        filled,
        filename=filled.name,
        headers=attachment_headers(filled.name),
        media_type=OOXML_TYPES.get(filled.suffix.lower(), "application/octet-stream"),
    )
