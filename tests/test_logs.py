"""Structured logs: events and fields, the request ID, and redaction (plan 005)."""

from __future__ import annotations

import io
import json
import logging

import pytest

from src import logs

SECRET = "a-configured-secret-value-123"


@pytest.fixture
def output():
    """Configure logging into a buffer, and put the root logger back afterwards."""
    root = logging.getLogger()
    before_handlers, before_level = list(root.handlers), root.level
    buffer = io.StringIO()

    def configure(style: str = "text") -> io.StringIO:
        logs.configure("DEBUG", style, secrets=[SECRET, "short", ""], stream=buffer)
        return buffer

    yield configure
    for handler in list(root.handlers):
        if handler not in before_handlers:
            root.removeHandler(handler)
    root.setLevel(before_level)


def test_an_event_renders_as_its_name_and_fields(output):
    buffer = output()
    logs.get_logger("src.storage").info("storage.files_removed", person="a@b.c", files=3, note="two words")
    line = buffer.getvalue().strip()
    assert line.endswith('INFO     src.storage storage.files_removed person=a@b.c files=3 note="two words"')


def test_json_output_is_one_object_per_line_with_the_fields(output):
    buffer = output("json")
    with logs.request_context("req-12345678"):
        logs.get_logger("src.api").warning("http.app_error", code="unavailable", status=503)
    record = json.loads(buffer.getvalue())
    assert record["event"] == "http.app_error"
    assert (record["code"], record["status"], record["level"], record["request_id"]) == (
        "unavailable",
        503,
        "warning",
        "req-12345678",
    )


def test_every_record_inside_a_request_carries_its_id_even_prose(output):
    buffer = output()
    with logs.request_context("req-abcdefgh"):
        logging.getLogger("src.legacy").info("Loaded %s (%d characters)", "policy.pdf", 120)
    logging.getLogger("src.legacy").info("outside any request")
    first, second = buffer.getvalue().strip().split("\n")
    assert first.endswith("Loaded policy.pdf (120 characters) request_id=req-abcdefgh")
    assert "request_id" not in second


def test_configured_secrets_and_key_shapes_are_redacted_from_any_logger(output):
    buffer = output()
    key_shape = "gsk_" + "A1b2" * 10
    logs.get_logger("src.llm").error("llm.call_failed", key=SECRET)
    logging.getLogger("httpx_like").warning("Authorization: Bearer %s", key_shape)
    text = buffer.getvalue()
    assert SECRET not in text and key_shape not in text
    assert text.count(logs.REDACTED) == 2


def test_short_values_are_not_treated_as_secrets(output):
    """`EMBEDDING_API_KEY=unused` must not blank out the word "unused" everywhere."""
    buffer = output()
    logs.get_logger("src.x").info("x.done", detail="short")
    assert "detail=short" in buffer.getvalue()


def test_exception_attaches_the_traceback(output):
    buffer = output()
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logs.get_logger("src.x").exception("x.failed", step=2)
    text = buffer.getvalue()
    assert "x.failed step=2" in text and "RuntimeError: boom" in text


def test_configuring_twice_keeps_one_handler(output):
    output()
    output()
    assert sum(isinstance(h, logs._StructuredHandler) for h in logging.getLogger().handlers) == 1


def test_an_unknown_format_is_refused():
    with pytest.raises(ValueError, match="text"):
        logs.configure("INFO", "yaml")


def test_event_names_are_dotted_lower_case():
    assert logs.EVENT_NAME.fullmatch("storage.files_removed")
    assert not logs.EVENT_NAME.fullmatch("Storage: removed %d files")
    assert not logs.EVENT_NAME.fullmatch("removed")
