"""A questionnaire's routes, moving here from `src/api.py` (plan 029).

Filling came first, to make room in `src/api.py`; opening, listing and reading
one followed with plan 029's Stage 1. Two routers, each included in
`src/api.py` where its routes were, so the order the routes are matched in, and
the OpenAPI document, stay the same: `opening` before answering, `router`
(filling) after approving.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from src import batches, forms, products, service, tools
from src.identity import User
from src.routes.auth import current_user

opening = APIRouter()
router = APIRouter()


@opening.post("/api/forms")
async def open_questionnaire(
    file: UploadFile = File(...), product: str = Form(""), user: User = Depends(current_user)
) -> dict[str, Any]:
    """Read an uploaded questionnaire, for a `product` or General, and report what can be answered in it.

    Nothing is answered here. The point of the separation is that a person sees
    which sheets were used, which were skipped and why, and what each column was
    taken to be, *before* a run that costs minutes.
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
    path = service.save_upload(name, await file.read(), user.team_id, owner=user.email)
    # In a thread: reading a workbook is a CPU-bound XML parse, and under the
    # assisted and agent strategies it is also a network call. Either way it is
    # not something to do on the event loop of a server answering other people.
    batch = await run_in_threadpool(lambda: tools.open_form(user, path, product_id=product_id))
    return tools.inspect(user, batch.id)


@opening.get("/api/forms")
def list_questionnaires(user: User = Depends(current_user), limit: int = 25) -> dict[str, Any]:
    return {"forms": batches.recent(user.team_id, actor_email=user.email, limit=limit)}


@opening.get("/api/forms/{batch_id}")
def get_questionnaire(batch_id: str, user: User = Depends(current_user)) -> dict[str, Any]:
    return tools.inspect(user, batch_id)


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
