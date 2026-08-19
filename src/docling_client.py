"""Client for the Docling conversion service.

Docling is hosted as a container on the testing server and turns PDF, DOCX and
friends into Markdown, keeping tables as real Markdown tables. It is the primary
extraction path; `documents.py` owns the decision to fall back to the local
loaders when this service is unavailable.

Conversion of a local file is submitted asynchronously and polled:

    POST /v1/convert/file/async   multipart upload, returns a task id
    GET  /v1/status/poll/{id}     task state
    GET  /v1/result/{id}          the converted document
    POST /v1/convert/source       JSON body naming a remote URL (synchronous)

The synchronous file endpoint is deliberately unused. docling-serve caps it at
`DOCLING_SERVE_MAX_SYNC_WAIT` seconds — 300 by default — and answers HTTP 504
past that, so the longest documents in a corpus are exactly the ones it cannot
convert.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from src.config import settings

logger = logging.getLogger(__name__)

FILE_ENDPOINT = "/v1/convert/file"
FILE_ASYNC_ENDPOINT = "/v1/convert/file/async"
SOURCE_ENDPOINT = "/v1/convert/source"

# Async task states that mean the job is no longer moving.
_TERMINAL_STATUSES = {"success", "partial_success", "failure"}

_POLL_INITIAL_SECONDS = 2.0
_POLL_MAX_SECONDS = 15.0

# Docling reports a per-request status; anything outside this set means the
# response carries no text worth using.
_OK_STATUSES = {"success", "partial_success"}


class DoclingError(RuntimeError):
    """Docling was unreachable, errored, or returned no Markdown."""


def _conversion_options() -> dict[str, Any]:
    """The options block shared by both endpoints (JSON-shaped)."""
    return {
        "to_formats": ["md"],
        "image_export_mode": settings.docling_image_export_mode,
        "do_ocr": settings.docling_do_ocr,
    }


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
    }
    submitted = await _post(
        FILE_ASYNC_ENDPOINT, data=form, files={"files": (path.name, path.read_bytes())}
    )
    payload = await _await_task(submitted, path.name)
    return _markdown(payload, path.name)


async def _await_task(submitted: dict, name: str) -> dict:
    """Poll an async conversion to completion and return its result payload."""
    task_id = submitted.get("task_id")
    if not task_id:
        raise DoclingError(f"Docling accepted '{name}' without returning a task id: {submitted}")

    deadline = time.monotonic() + settings.docling_conversion_timeout
    delay = _POLL_INITIAL_SECONDS

    while True:
        status = str((submitted or {}).get("task_status") or "").lower()
        if status in _TERMINAL_STATUSES:
            break
        if time.monotonic() > deadline:
            raise DoclingError(
                f"Docling did not finish '{name}' within {settings.docling_conversion_timeout:.0f}s"
                f" (last status: {status or 'unknown'})"
            )

        await asyncio.sleep(delay)
        delay = min(delay * 1.5, _POLL_MAX_SECONDS)
        submitted = await _get(f"/v1/status/poll/{task_id}")

    if status == "failure":
        raise DoclingError(f"Docling failed to convert '{name}': {submitted.get('task_meta') or submitted}")

    return await _get(f"/v1/result/{task_id}")


async def convert_url(url: str) -> str:
    """Convert a document Docling fetches itself, by URL."""
    body = {"sources": [{"kind": "http", "url": url}], "options": _conversion_options()}
    payload = await _post(SOURCE_ENDPOINT, json=body)
    return _markdown(payload, url)


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
    status = str(payload.get("status") or "unknown").lower()
    document = payload.get("document") or {}
    markdown = document.get("md_content") or ""

    if status not in _OK_STATUSES or not markdown.strip():
        errors = payload.get("errors") or []
        detail = f" — {errors}" if errors else ""
        raise DoclingError(f"Docling could not convert '{name}' (status={status}){detail}")

    if status == "partial_success":
        logger.warning("Docling partially converted %s: %s", name, payload.get("errors"))

    return markdown
