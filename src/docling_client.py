"""Client for the Docling conversion service.

Docling is hosted as a container on the testing server and turns PDF, DOCX and
friends into Markdown, keeping tables as real Markdown tables. It is the primary
extraction path; `documents.py` owns the decision to fall back to the local
loaders when this service is unavailable.

Two endpoints are used, both documented by docling-serve:

    POST /v1/convert/file    multipart upload of a local file
    POST /v1/convert/source  JSON body naming a remote URL
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from src.config import settings

logger = logging.getLogger(__name__)

FILE_ENDPOINT = "/v1/convert/file"
SOURCE_ENDPOINT = "/v1/convert/source"

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


async def convert_file(path: Path) -> str:
    """Convert a local file to Markdown."""
    # The multipart form takes the same options as flat fields; booleans and
    # list values are sent the way the service's OpenAPI schema expects them.
    form = {
        "to_formats": "md",
        "image_export_mode": settings.docling_image_export_mode,
        "do_ocr": str(settings.docling_do_ocr).lower(),
    }
    payload = await _post(FILE_ENDPOINT, data=form, files={"files": (path.name, path.read_bytes())})
    return _markdown(payload, path.name)


async def convert_url(url: str) -> str:
    """Convert a document Docling fetches itself, by URL."""
    body = {"sources": [{"kind": "http", "url": url}], "options": _conversion_options()}
    payload = await _post(SOURCE_ENDPOINT, json=body)
    return _markdown(payload, url)


async def _post(endpoint: str, **kwargs: Any) -> dict:
    """POST to Docling and return the decoded body, or raise `DoclingError`."""
    url = settings.docling_base_url.rstrip("/") + endpoint
    try:
        async with httpx.AsyncClient(timeout=settings.docling_timeout) as client:
            response = await client.post(url, **kwargs)
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
