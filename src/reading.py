"""Which uploaded files are being read right now, so that deleting other work does not remove one (TD-078).

`service.save_upload` gives identical content one name, so a file can be read
again while a questionnaire already made from it is deleted, by its owner or
by retention. Deletion asked only whether a saved questionnaire read the file,
and a read under way is not saved yet: the file went from under it. So each
read holds the file's name for as long as it lasts, and deletion leaves a held
file alone.

Per process, like `busy` and `progress`: one process serves the app.
"""

from __future__ import annotations

import os
import threading
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_LOCK = threading.Lock()
_READING: Counter[str] = Counter()


def _key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


@contextmanager
def holding(path: Path) -> Iterator[None]:
    """Hold a file's name while it is read; let go however the read ends."""
    key = _key(path)
    with _LOCK:
        _READING[key] += 1
    try:
        yield
    finally:
        with _LOCK:
            _READING[key] -= 1
            if _READING[key] <= 0:
                del _READING[key]


def being_read(path: Path, *, besides: int = 0) -> bool:
    """Whether more than `besides` reads hold this file: a read deciding about its own file passes 1."""
    with _LOCK:
        return _READING.get(_key(path), 0) > besides
