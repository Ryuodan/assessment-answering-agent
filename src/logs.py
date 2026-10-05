"""Structured logs: an event name, named fields, and the request they belong to.

    log = get_logger(__name__)
    log.info("storage.files_removed", person=email, files=3, freed_mb=12.5)

An event is a dotted, lower-case name -- `<area>.<what happened>` -- that can be
searched for; its facts are keyword fields, never formatted into a sentence.
ARCH-LOG checks both (plan 005, D-014).

`configure()` installs one handler on the root logger that writes either text,

    2026-10-05 14:03:11 INFO     src.storage storage.files_removed person=a@b.c files=3 request_id=4f2c...

or, with LOG_FORMAT=json, one JSON object per line. Records from loggers that
still log prose (TD-028) and from libraries go through the same handler, so
every line carries the request ID while a request is running, and every line
has configured secret values and key-shaped strings replaced by `[redacted]`.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, TextIO

EVENT_NAME = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+")
REDACTED = "[redacted]"
FORMATS = ("text", "json")

# Same shapes ARCH-SECRET looks for in tracked files.
_KEY_SHAPES = re.compile(
    r"gsk_[A-Za-z0-9]{20,}|lsv2_(?:pt|sk)_[A-Za-z0-9_]{20,}|\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}"
    r"|\bhf_[A-Za-z0-9]{30,}|\bAKIA[0-9A-Z]{16}\b"
)
_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")


def current_request_id() -> str:
    """The ID of the request this code is running for, or '' outside one."""
    return _request_id.get()


@contextmanager
def request_context(request_id: str) -> Iterator[None]:
    """Every record logged inside this block carries `request_id`."""
    token = _request_id.set(request_id)
    try:
        yield
    finally:
        _request_id.reset(token)


def _value(value: Any) -> str:
    text = str(value)
    return json.dumps(text, ensure_ascii=False) if not text or re.search(r'[\s"=]', text) else text


def render(event: str, fields: dict[str, Any]) -> str:
    """`event key=value ...`: the record's message, so any handler shows the fields."""
    return event + "".join(f" {key}={_value(value)}" for key, value in fields.items())


class EventLogger:
    """A logger whose every call names an event; keyword fields become data."""

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    def _log(self, level: int, event: str, fields: dict[str, Any], *, exc_info: bool = False) -> None:
        if self._logger.isEnabledFor(level):
            self._logger.log(
                level, render(event, fields), extra={"event": event, "fields": fields}, exc_info=exc_info, stacklevel=3
            )

    def debug(self, event: str, **fields: Any) -> None:
        self._log(logging.DEBUG, event, fields)

    def info(self, event: str, **fields: Any) -> None:
        self._log(logging.INFO, event, fields)

    def warning(self, event: str, *, exc_info: bool = False, **fields: Any) -> None:
        """`exc_info=True` attaches the exception being handled, at warning level."""
        self._log(logging.WARNING, event, fields, exc_info=exc_info)

    def error(self, event: str, **fields: Any) -> None:
        self._log(logging.ERROR, event, fields)

    def exception(self, event: str, **fields: Any) -> None:
        """`error`, with the exception being handled attached."""
        self._log(logging.ERROR, event, fields, exc_info=True)


def get_logger(name: str) -> EventLogger:
    return EventLogger(name)


class _RequestContext(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", ""):
            record.request_id = current_request_id()
        return True


class _Formatter(logging.Formatter):
    def __init__(self, style: str, secrets: Iterable[str]) -> None:
        super().__init__()
        self.json = style == "json"
        # Longest first, so a secret that contains another is replaced whole.
        self.secrets = sorted({s for s in secrets if s and len(s) >= 8}, key=len, reverse=True)

    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "event", "")
        fields: dict[str, Any] = getattr(record, "fields", {}) or {}
        request_id = getattr(record, "request_id", "")
        when = datetime.fromtimestamp(record.created, timezone.utc)
        if self.json:
            document: dict[str, Any] = dict(fields)
            document.update(ts=when.isoformat(timespec="milliseconds"), level=record.levelname.lower())
            document.update(logger=record.name)
            if event:
                document["event"] = event
            else:
                document["message"] = record.getMessage()
            if request_id:
                document["request_id"] = request_id
            if record.exc_info:
                document["exception"] = self.formatException(record.exc_info)
            text = json.dumps(document, default=str, ensure_ascii=False)
        else:
            text = f"{when:%Y-%m-%d %H:%M:%S} {record.levelname:<8} {record.name} {record.getMessage()}"
            if request_id:
                text += f" request_id={request_id}"
            if record.exc_info:
                text += "\n" + self.formatException(record.exc_info)
        return self.redact(text)

    def redact(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, REDACTED)
        return _KEY_SHAPES.sub(REDACTED, text)


class _StructuredHandler(logging.StreamHandler[TextIO]):
    """The handler `configure` installs; recognised by type so it can be replaced."""


def configure(
    level: str = "INFO", style: str = "text", secrets: Iterable[str] = (), stream: TextIO | None = None
) -> None:
    """Install the one handler on the root logger, replacing any this installed before."""
    if style not in FORMATS:
        raise ValueError(f"log format must be one of {FORMATS}, not {style!r}")
    root = logging.getLogger()
    for handler in [h for h in root.handlers if isinstance(h, _StructuredHandler)]:
        root.removeHandler(handler)
    handler = _StructuredHandler(stream)
    handler.setFormatter(_Formatter(style, secrets))
    handler.addFilter(_RequestContext())
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # Chatty at INFO; they only matter when debugging.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
