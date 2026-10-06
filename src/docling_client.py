"""Client for the Docling conversion service.

Docling is hosted as a container on the testing server and turns PDF, DOCX and
friends into Markdown, keeping tables as real Markdown tables. It is the primary
extraction path; `documents.py` owns the decision to fall back to the local
loaders when this service is unavailable.

Conversion of a local file is submitted asynchronously and polled:

    POST /v1/convert/file/async   multipart upload, returns a task id
    GET  /v1/status/poll/{id}     task state
    GET  /v1/result/{id}          the converted document

The synchronous file endpoint is deliberately unused. docling-serve caps it at
`DOCLING_SERVE_MAX_SYNC_WAIT` seconds — 300 by default — and answers HTTP 504
past that, so the longest documents in a corpus are exactly the ones it cannot
convert.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.config import settings
from src.logs import get_logger

logger = get_logger(__name__)

FILE_ENDPOINT = "/v1/convert/file"
FILE_ASYNC_ENDPOINT = "/v1/convert/file/async"

# Async task states that mean the job is no longer moving.
_TERMINAL_STATUSES = {"success", "partial_success", "failure"}

_POLL_INITIAL_SECONDS = 2.0
_POLL_MAX_SECONDS = 15.0

# Docling reports a per-request status; anything outside this set means the
# response carries no text worth using.
_OK_STATUSES = {"success", "partial_success"}


class DoclingError(RuntimeError):
    """Docling was unreachable, errored, or returned no Markdown."""


async def convert_file(path: Path, *, do_ocr: bool | None = None) -> str:
    """Convert a local file to Markdown.

    `do_ocr` is decided per file by the caller — see `documents._looks_scanned`
    — and falls back to the configured default when not given.

    Submitted to the asynchronous endpoint and polled. The synchronous one is
    capped server-side by `DOCLING_SERVE_MAX_SYNC_WAIT` (300 seconds by
    default) and returns HTTP 504 past it — which a 161-page standard reaches
    comfortably, so on a corpus with real reference material the synchronous
    path fails exactly on the documents worth having.
    """
    # The multipart form takes the same options as flat fields; booleans and
    # list values are sent the way the service's OpenAPI schema expects them.
    form = {
        "to_formats": "md",
        "image_export_mode": settings.docling_image_export_mode,
        "do_ocr": str(settings.docling_do_ocr if do_ocr is None else do_ocr).lower(),
        "do_pdf_heading_hierarchy": str(settings.docling_heading_hierarchy).lower(),
        "md_page_break_placeholder": settings.docling_page_break_placeholder,
    }
    submitted = await _post(FILE_ASYNC_ENDPOINT, data=form, files={"files": (path.name, path.read_bytes())})
    payload = await _await_task(submitted, path.name)
    return _markdown(payload, path.name)


class _Task(BaseModel):
    """What Docling says about an asynchronous conversion (plan 007: parsed, not indexed)."""

    model_config = ConfigDict(extra="ignore")
    task_id: str = ""
    task_status: str = ""
    task_meta: object = None


class _Document(BaseModel):
    model_config = ConfigDict(extra="ignore")
    md_content: str | None = None


class _Result(BaseModel):
    """A finished conversion: its status, the Markdown, and any errors."""

    model_config = ConfigDict(extra="ignore")
    status: str | None = None
    document: _Document | None = None
    errors: list[object] = Field(default_factory=list)


_Response = TypeVar("_Response", _Task, _Result)


def _parse(model: type[_Response], payload: object, what: str) -> _Response:
    """Docling's JSON as a model; a response of another shape is a DoclingError."""
    try:
        return model.model_validate(payload if payload is not None else {})
    except ValidationError as error:
        raise DoclingError(f"Docling returned an unexpected {what}: {error.errors()[0]['msg']}") from error


async def _await_task(submitted: dict, name: str) -> dict:
    """Poll an async conversion to completion and return its result payload."""
    task = _parse(_Task, submitted, "task")
    task_id = task.task_id
    if not task_id:
        raise DoclingError(f"Docling accepted '{name}' without returning a task id: {submitted}")

    deadline = time.monotonic() + settings.docling_conversion_timeout
    delay = _POLL_INITIAL_SECONDS

    while True:
        status = task.task_status.lower()
        if status in _TERMINAL_STATUSES:
            break
        if time.monotonic() > deadline:
            raise DoclingError(
                f"Docling did not finish '{name}' within {settings.docling_conversion_timeout:.0f}s"
                f" (last status: {status or 'unknown'})"
            )

        await asyncio.sleep(delay)
        delay = min(delay * 1.5, _POLL_MAX_SECONDS)
        task = _parse(_Task, await _get(f"/v1/status/poll/{task_id}"), "task status")

    if status == "failure":
        raise DoclingError(f"Docling failed to convert '{name}': {task.task_meta or task.model_dump()}")

    return await _get(f"/v1/result/{task_id}")


async def _get(endpoint: str) -> dict:
    """GET from Docling and return the decoded body, or raise `DoclingError`."""
    return await _request("GET", endpoint)


async def _post(endpoint: str, **kwargs: Any) -> dict:
    return await _request("POST", endpoint, **kwargs)


async def _request(method: str, endpoint: str, **kwargs: Any) -> dict:
    """Call Docling and return the decoded body, or raise `DoclingError`."""
    url = settings.docling_base_url.rstrip("/") + endpoint
    try:
        async with httpx.AsyncClient(timeout=settings.docling_timeout) as client:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:300]
        raise DoclingError(f"Docling returned HTTP {exc.response.status_code} from {endpoint}: {detail}") from exc
    except httpx.HTTPError as exc:
        raise DoclingError(f"Docling at {settings.docling_base_url} is unreachable: {exc}") from exc
    except ValueError as exc:  # body was not JSON
        raise DoclingError(f"Docling returned a non-JSON response from {endpoint}: {exc}") from exc


def _markdown(payload: dict, name: str) -> str:
    """Pull `md_content` out of a conversion response, insisting it is usable."""
    result = _parse(_Result, payload, "conversion result")
    status = (result.status or "unknown").lower()
    markdown = (result.document.md_content if result.document else None) or ""

    if status not in _OK_STATUSES or not markdown.strip():
        detail = f" — {result.errors}" if result.errors else ""
        raise DoclingError(f"Docling could not convert '{name}' (status={status}){detail}")

    if status == "partial_success":
        logger.warning("docling.partial_conversion", document=name, errors=len(result.errors))

    return number_pages(markdown)


def number_pages(markdown: str) -> str:
    """Turn Docling's page-break placeholders into numbered page markers.

    Docling can insert a fixed string between pages but cannot number them, and
    the chunker already reads `--- page N ---` because the local pdfplumber
    loader emits exactly that. Rewriting one into the other means page numbers
    reach chunk metadata without the chunker learning a second convention, and
    an answer can cite a page as well as a clause.

    A document Docling converted without the placeholder -- anything extracted
    before this existed -- comes back unchanged rather than being given a
    misleading page 1.
    """
    marker = settings.docling_page_break_placeholder
    if not marker or marker not in markdown:
        return markdown

    pages = markdown.split(marker)
    numbered = ["--- page 1 ---\n" + pages[0]]
    numbered += [f"\n--- page {number} ---\n" + body for number, body in enumerate(pages[1:], start=2)]
    return "".join(numbered)
