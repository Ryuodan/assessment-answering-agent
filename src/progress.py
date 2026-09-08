"""How far along a run is, for anything watching it.

Answering a long assessment is minutes of silence otherwise: the request does
not return until the last question is done, so the interface can say "this may
take several minutes" and nothing else. A reviewer with a sixty-question form
cannot tell a slow run from a stuck one.

The registry is deliberately in-process and in-memory. It holds counters, not
results — losing it costs a progress bar, never an answer — and a single
process serves the interface, so there is nothing here worth a database or a
cache server. Entries are capped and expire, so a long-lived server does not
accumulate them.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

# Long enough for a client to collect the final state after the run returns,
# short enough that abandoned runs do not pile up.
_TTL_SECONDS = 30 * 60
_MAX_RUNS = 64


@dataclass
class Run:
    """The state of one assessment run."""

    total: int = 0
    completed: int = 0
    stage: str = "extracting"
    updated_at: float = field(default_factory=time.monotonic)

    def as_dict(self) -> dict:
        remaining = max(self.total - self.completed, 0)
        return {
            "stage": self.stage,
            "total": self.total,
            "completed": self.completed,
            "remaining": remaining,
            "percent": round(100 * self.completed / self.total) if self.total else 0,
        }


_LOCK = threading.Lock()
_RUNS: dict[str, Run] = {}


def _expire(now: float) -> None:
    """Drop stale entries. Called under the lock."""
    for key in [key for key, run in _RUNS.items() if now - run.updated_at > _TTL_SECONDS]:
        del _RUNS[key]
    while len(_RUNS) > _MAX_RUNS:
        oldest = min(_RUNS, key=lambda key: _RUNS[key].updated_at)
        del _RUNS[oldest]


def start(run_id: str | None, stage: str = "extracting") -> None:
    """Register a run, before the question count is known."""
    if not run_id:
        return
    with _LOCK:
        now = time.monotonic()
        _RUNS[run_id] = Run(stage=stage, updated_at=now)
        # Trimmed after the insert, so the cap is a cap: trimming first leaves
        # the new entry one over it.
        _expire(now)


def note(run_id: str | None, stage: str) -> None:
    """Say what is happening now, with no count behind it.

    An agent's turn is a sequence of short operations -- reading a file,
    listing questions, searching -- and only one of them has a denominator.
    Naming them is the difference between a person watching progress and a
    person watching the word "Working" and wondering whether it has frozen.

    The count is cleared, because it belonged to whatever finished: leaving it
    would draw a full bar beside a label about something that has not started.
    """
    if not run_id:
        return
    with _LOCK:
        run = _RUNS.setdefault(run_id, Run())
        run.stage = stage
        run.total = 0
        run.completed = 0
        run.updated_at = time.monotonic()


def set_total(run_id: str | None, total: int) -> None:
    """Record how many questions were found, once extraction has run."""
    if not run_id:
        return
    with _LOCK:
        run = _RUNS.setdefault(run_id, Run())
        run.total = total
        run.stage = "answering"
        run.updated_at = time.monotonic()


def advance(run_id: str | None) -> None:
    """One more question finished — successfully or not."""
    if not run_id:
        return
    with _LOCK:
        run = _RUNS.setdefault(run_id, Run())
        run.completed += 1
        run.updated_at = time.monotonic()


def finish(run_id: str | None) -> None:
    if not run_id:
        return
    with _LOCK:
        run = _RUNS.setdefault(run_id, Run())
        run.stage = "done"
        run.completed = max(run.completed, run.total)
        run.updated_at = time.monotonic()


def snapshot(run_id: str) -> dict | None:
    """The current state of a run, or None when it is unknown."""
    with _LOCK:
        run = _RUNS.get(run_id)
        return run.as_dict() if run else None
