"""The answer memory's routes: the shared memory, or a product's (plan 022).

Moved out of `src/api.py` and included where they were. The readers and "teach
an answer" take an optional `product`, Shared when it is left out; an entry,
once it exists, is reached by its id whichever memory it is in, and
`/api/memory/{id}/move` moves it between them. A product that is not the
caller's team's is absent (`product_not_found`).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field

from src import answer_memory, events, products, tools
from src.errors import NotFound
from src.identity import User
from src.logs import get_logger
from src.memory import Entry
from src.routes.auth import current_user

logger = get_logger(__name__)
router = APIRouter()


def _scope(user: User, product: str) -> str:
    """The memory asked for: "" for the shared one, or the id of one of the team's products."""
    return products.get(user.team_id, product).id if product else ""


# ---------------------------------------------------------------------------
# The answer memory
#
# Shared by the whole team and by nobody else, like the knowledge base and for
# the same reason: what the team has said before is one fact about the team, not
# a private note, and not another team's to read or change. Who added or
# approved each entry is recorded on it, so a shared record is still an
# attributable one.
# ---------------------------------------------------------------------------


def _memory_payload(entry: Entry) -> dict[str, Any]:
    return {
        "entry_id": entry.entry_id,
        "question": entry.question,
        "answer": entry.answer,
        "section": entry.section,
        "from_file": entry.from_file,
        "origin": entry.origin,
        "approved_by": entry.approved_by,
        "approved_on": entry.approved_on,
        "superseded_by": entry.superseded_by,
        "stands": entry.stands,
        "product_id": entry.product_id,
    }


@router.get("/api/memory")
def list_memory(
    query: str = "",
    standing: str = "",
    origin: str = "",
    limit: int = 100,
    offset: int = 0,
    product: str = "",
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """What we have said before, newest first: the shared memory, or a `product`'s."""
    scope = _scope(user, product)
    keep = {"yes": True, "no": False}.get(standing.lower())
    found = answer_memory.entries(
        query=query,
        standing=keep,
        origin=origin,
        limit=max(1, min(limit, 500)),
        offset=max(0, offset),
        team_id=user.team_id,
        product_id=scope,
    )
    return {
        "entries": [_memory_payload(entry) for entry in found],
        "total": answer_memory.count(
            query=query,
            standing=keep,
            origin=origin,
            team_id=user.team_id,
            product_id=scope,
        ),
        "stats": answer_memory.stats(user.team_id, scope),
    }


@router.get("/api/memory/conflicts")
def list_memory_conflicts(product: str = "", user: User = Depends(current_user)) -> dict[str, Any]:
    """Pairs that disagree, with both answers, for somebody to decide between. One memory's."""
    pairs = []
    for conflict in answer_memory.conflicts(team_id=user.team_id, product_id=_scope(user, product)):
        first = answer_memory.get(conflict.entry_id, user.team_id)
        second = answer_memory.get(conflict.other_id, user.team_id)
        if first is None or second is None:
            continue
        pairs.append(
            {
                "because": conflict.because,
                "raised_at": conflict.raised_at,
                "entry": _memory_payload(first),
                "other": _memory_payload(second),
            }
        )
    return {"conflicts": pairs}


class MemoryEntryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    answer: str = Field(min_length=1, max_length=20000)
    section: str = Field(default="", max_length=400)
    product: str = Field(default="", max_length=64)


@router.post("/api/memory")
def add_memory_entry(
    body: MemoryEntryRequest, tasks: BackgroundTasks, user: User = Depends(current_user)
) -> dict[str, Any]:
    """Teach the memory an answer by hand."""
    entry = answer_memory.record(
        body.question,
        body.answer,
        section=body.section,
        origin="manual",
        approved_by=user.email,
        team_id=user.team_id,
        product_id=_scope(user, body.product),
    )
    events.record(
        user,
        events.MEMORY_ADDED,
        subject_type=tools.SUBJECT_MEMORY,
        subject_id=entry.entry_id,
        question=entry.question[:200],
    )
    tasks.add_task(scan_memory)
    return _memory_payload(entry)


class MemoryEditRequest(BaseModel):
    question: str | None = Field(default=None, max_length=4000)
    answer: str | None = Field(default=None, max_length=20000)


# `:path` on every one of these, and it is not cosmetic. An approved answer's id
# is `approved::<batch>::<question id>`, and a question id carries the shape of
# the questionnaire it came from -- `Cybersecurity Governance/Q1` in the Word
# forms. `encodeURIComponent` sends that slash as `%2F`, the server decodes it
# before routing, and a plain `{entry_id}` never matches a value with a slash in
# it: every attempt to correct or forget those entries returned 404, and the
# page left the card on screen because nothing had happened to it.
@router.patch("/api/memory/{entry_id:path}")
def edit_memory_entry(
    entry_id: str,
    body: MemoryEditRequest,
    tasks: BackgroundTasks,
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Correct an entry. Not a supersession: nothing changed its mind.

    A corrected answer is compared again, because correcting one is one of the
    ways it comes to contradict another.
    """
    entry = answer_memory.update(
        entry_id,
        question=body.question,
        answer=body.answer,
        team_id=user.team_id,
    )
    if entry is None:
        raise NotFound("No such entry in the answer memory.", code="memory_entry_not_found")
    events.record(
        user,
        events.MEMORY_EDITED,
        subject_type=tools.SUBJECT_MEMORY,
        subject_id=entry_id,
    )
    tasks.add_task(scan_memory)
    return _memory_payload(entry)


@router.delete("/api/memory/{entry_id:path}")
def remove_memory_entry(entry_id: str, user: User = Depends(current_user)) -> dict[str, Any]:
    """Forget an entry: the row, its vector, and the conflicts it raised."""
    if not answer_memory.remove(entry_id, user.team_id):
        raise NotFound("No such entry in the answer memory.", code="memory_entry_not_found")
    events.record(
        user,
        events.MEMORY_REMOVED,
        subject_type=tools.SUBJECT_MEMORY,
        subject_id=entry_id,
    )
    return {"deleted": entry_id}


@router.post("/api/memory/{entry_id:path}/restore")
def restore_memory_entry(entry_id: str, user: User = Depends(current_user)) -> dict[str, Any]:
    """Put a superseded entry back into use, when the later answer was wrong."""
    if answer_memory.get(entry_id, user.team_id) is None:
        raise NotFound("No such entry in the answer memory.", code="memory_entry_not_found")
    answer_memory.restore(entry_id, user.team_id)
    events.record(
        user,
        events.MEMORY_EDITED,
        subject_type=tools.SUBJECT_MEMORY,
        subject_id=entry_id,
        restored=True,
    )
    restored = answer_memory.get(entry_id, user.team_id)
    if restored is None:  # forgotten by somebody else in the moment between
        raise NotFound("No such entry in the answer memory.", code="memory_entry_not_found")
    return _memory_payload(restored)


class MoveRequest(BaseModel):
    product: str = Field(default="", max_length=64)


@router.post("/api/memory/{entry_id:path}/move")
def move_memory_entry(
    entry_id: str, body: MoveRequest, tasks: BackgroundTasks, user: User = Depends(current_user)
) -> dict[str, Any]:
    """Move an entry to the shared memory (`product` empty) or a product's, and compare it again there."""
    moved = answer_memory.move(entry_id, _scope(user, body.product), user.team_id)
    if moved is None:
        raise NotFound("No such entry in the answer memory.", code="memory_entry_not_found")
    events.record(
        user,
        events.MEMORY_EDITED,
        subject_type=tools.SUBJECT_MEMORY,
        subject_id=entry_id,
        moved_to=moved.product_id,
    )
    tasks.add_task(scan_memory)
    return _memory_payload(moved)


class ResolveConflictRequest(BaseModel):
    entry_id: str = Field(min_length=1, max_length=400)
    other_id: str = Field(min_length=1, max_length=400)
    resolution: str = Field(pattern="^(keep_this|keep_other|keep_both)$")


@router.post("/api/memory/conflicts/resolve")
def resolve_memory_conflict(body: ResolveConflictRequest, user: User = Depends(current_user)) -> dict[str, Any]:
    """Say which of two disagreeing answers is our position, or that neither loses."""
    for entry_id in (body.entry_id, body.other_id):
        if answer_memory.get(entry_id, user.team_id) is None:
            raise NotFound("No such entry in the answer memory.", code="memory_entry_not_found")
    answer_memory.apply_resolution(
        body.entry_id,
        body.other_id,
        resolution=body.resolution,
        by=user.email,
        team_id=user.team_id,
    )
    events.record(
        user,
        events.MEMORY_RESOLVED,
        subject_type=tools.SUBJECT_MEMORY,
        subject_id=body.entry_id,
        other_id=body.other_id,
        resolution=body.resolution,
    )
    return {"resolved": True}


@router.post("/api/memory/scan")
async def scan_memory_now(limit: int = 50, user: User = Depends(current_user)) -> dict[str, Any]:
    """Compare everything that has arrived since the last sweep, and report it.

    The same sweep that runs by itself after an upload or an approval, exposed
    so a person can ask for it — after importing eleven questionnaires at once,
    "has anything I just added contradicted us" is a question with an answer,
    and waiting for a background task to have got round to it is not one.

    Bounded, and it says how much is left. A sweep is one model call per entry
    and a backlog can be hundreds: a button that returns in twenty seconds
    saying what it found and what remains is a button somebody will press again,
    and one that hangs for four minutes is one they will reload the page on.
    """
    findings = await answer_memory.scan_pending(
        limit=max(1, min(limit, 500)),
        team_id=user.team_id,
    )
    return {
        "scanned": True,
        "found": [
            {"kind": f.kind, "other_id": f.other_id, "because": f.because, "other_question": f.other_question}
            for f in findings
        ],
        "stats": answer_memory.stats(user.team_id),
    }


_sweep = {"running": False, "again": False}
"""Whether a background sweep is under way, and whether another was asked for meanwhile."""


async def scan_memory() -> None:
    """The sweep as a background task: never raises, never blocks a response.

    One at a time. Every approval of a written answer asks for a sweep, and a
    sweep is a model call per pending entry, so five approvals clicked through
    in a row ran five sweeps over the same five entries. A request that arrives
    while one is running is folded into it: the running sweep goes round once
    more when it finishes, and picks up whatever arrived in the meantime.
    """
    if _sweep["running"]:
        _sweep["again"] = True
        return
    _sweep["running"] = True
    try:
        while True:
            _sweep["again"] = False
            try:
                found = await answer_memory.scan_pending(limit=200)
            except Exception:  # noqa: BLE001 - a background sweep must not take the app down
                logger.exception("memory.sweep_failed")
                return
            if found:
                logger.info("memory.sweep_found", findings=len(found))
            if not _sweep["again"]:
                return
    finally:
        _sweep["running"] = False
