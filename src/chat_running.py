"""Which conversations have a chat turn running right now: one turn at a time in each.

A turn runs inside the request that sent it, and can take minutes: "answer the
183 questions" is one message. The conversation is saved only when the turn
ends (`assistant.say`), so until then nothing stored says a turn is under way.
A page that opened another conversation meanwhile, or was reloaded, could not
show the message that had been sent or how far it had got, and the reply, when
it came, was drawn into whichever conversation was on screen (plan 031).

So the chat routes hold a conversation for the length of each turn, with what a
page needs to draw the turn again: the run's id (its progress is at
`/api/assessments/progress/{run_id}`), what the person typed, the file they
attached and when they sent it. While it is held, a second message to the same
conversation is refused, and so is forgetting it (`conversation_busy`): each
turn saves the history it started from, so the later save would drop the other
turn, and a conversation forgotten mid-turn would lose the reply on its way.

Held in this process's memory, like `src.progress` and `src.busy`, because one
process serves the app. A second worker would know only its own turns. A hold
never expires; it is let go when the turn ends, however it ends.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from src.errors import Conflict
from src.logs import get_logger

logger = get_logger(__name__)

_LOCK = threading.Lock()
_RUNNING: dict[str, dict[str, str]] = {}
"""Conversation id -> the turn running in it: `run_id`, `message`, `file`, `at`."""


@contextmanager
def hold(conversation_id: str, *, run_id: str, message: str, file: str = "") -> Iterator[None]:
    """Mark a turn running in a conversation for as long as it lasts; `conversation_busy` if one already is."""
    turn = {
        "run_id": run_id,
        "message": message,
        "file": file,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with _LOCK:
        refused = _RUNNING.get(conversation_id)
        if refused is None:
            _RUNNING[conversation_id] = turn
    if refused is not None:
        _refuse(conversation_id, refused)
    try:
        yield
    finally:
        with _LOCK:
            if _RUNNING.get(conversation_id) is turn:
                del _RUNNING[conversation_id]


def refuse(conversation_id: str) -> None:
    """Raise `conversation_busy` if a turn is running in this conversation."""
    with _LOCK:
        held = _RUNNING.get(conversation_id)
    if held is not None:
        _refuse(conversation_id, held)


def running(conversation_id: str) -> dict[str, str] | None:
    """The turn running in this conversation, as `{run_id, message, file, at}`, or None."""
    with _LOCK:
        held = _RUNNING.get(conversation_id)
        return dict(held) if held is not None else None


def _refuse(conversation_id: str, held: dict[str, str]) -> None:
    logger.info("chat_running.refused", conversation_id=conversation_id, run_id=held["run_id"])
    raise Conflict(
        "This conversation is still working on your last message. Wait until it finishes, then try again.",
        code="conversation_busy",
    )
