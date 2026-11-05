"""Which questionnaires are being answered right now: one run at a time on each.

A run on a large questionnaire takes many minutes, and it carries on after the
page that started it is reloaded or its request times out. Nothing stopped a
second run from starting meanwhile, paid for twice, nor an edit made during
the run from being overwritten by the run's last save. So a run holds its
questionnaire for as long as it lasts, and everything that changes a
questionnaire asks first (`tools._require`): another run, an edit, an approval,
a rewording. Reading and filling do not; filling only writes a copy (plan 029).

Held in this process's memory, beside `src.progress`, because one process
serves the app (`serve.sh` and `run.sh` start one worker). A second worker
would hold its own runs only, and two runs on one questionnaire could start
again; holding it across workers needs a database flag, and so a migration.

A hold never expires: one that lapsed while its run was still going would let
the overwrite back in. It is let go when the run ends, however it ends.
Holds nest within one task, so a run that shortens its own answers, or a
rewording that does, is not refused by itself.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src import progress
from src.errors import QuestionnaireBusy
from src.logs import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class _Hold:
    run_id: str
    started_at: str


_LOCK = threading.Lock()
_HELD: dict[str, _Hold] = {}
_MINE: ContextVar[frozenset[str]] = ContextVar("busy_mine", default=frozenset())
"""The questionnaires the current task holds, so its own nested work passes."""


@contextmanager
def hold(batch_id: str, run_id: str) -> Iterator[None]:
    """Mark a questionnaire busy for the length of a run; `QuestionnaireBusy` if another task holds it."""
    if batch_id in _MINE.get():
        yield
        return
    with _LOCK:
        if batch_id in _HELD:
            refused = _HELD[batch_id]
        else:
            refused = None
            started = datetime.now(timezone.utc).isoformat(timespec="seconds")
            _HELD[batch_id] = _Hold(run_id=run_id, started_at=started)
    if refused is not None:
        _refuse(batch_id)
    token = _MINE.set(_MINE.get() | {batch_id})
    try:
        yield
    finally:
        _MINE.reset(token)
        with _LOCK:
            _HELD.pop(batch_id, None)


def refuse(batch_id: str) -> None:
    """Raise `QuestionnaireBusy` if another task is answering this questionnaire."""
    if batch_id in _MINE.get():
        return
    with _LOCK:
        held = batch_id in _HELD
    if held:
        _refuse(batch_id)


def _refuse(batch_id: str) -> None:
    now = state(batch_id) or {}
    done = f" ({now['completed']} of {now['total']} done)" if now.get("total") else ""
    logger.info("busy.refused", batch_id=batch_id, run_id=now.get("run_id", ""))
    raise QuestionnaireBusy(
        f"This questionnaire is being answered right now{done}. Wait until it finishes, then try again."
    )


def state(batch_id: str) -> dict[str, Any] | None:
    """How far the run holding this questionnaire has got, or None when nothing holds it.

    `run_id`, `started_at`, and `progress`'s `stage`, `total`, `completed`,
    `remaining` and `percent`. Answering, with nothing counted, when the
    progress of the run is not known.
    """
    with _LOCK:
        held = _HELD.get(batch_id)
    if held is None:
        return None
    counted = progress.snapshot(held.run_id) or {
        "stage": "answering",
        "total": 0,
        "completed": 0,
        "remaining": 0,
        "percent": 0,
    }
    return {"run_id": held.run_id, "started_at": held.started_at, **counted}
