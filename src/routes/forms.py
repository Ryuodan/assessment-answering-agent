"""A questionnaire's routes, moving here from `src/api.py` (plan 029).

Filling came first, to make room in `src/api.py`; the other questionnaire
routes follow with plan 029's Stage 1. Included in `src/api.py` where the routes
were, so the order the routes are matched in, and the OpenAPI document, stay
the same.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src import tools
from src.identity import User
from src.routes.auth import current_user

router = APIRouter()


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
