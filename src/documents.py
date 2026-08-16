"""PDF and DOCX text extraction.

Assessments are overwhelmingly tables — "question | answer | evidence" grids —
so plain text extraction is not enough. Every path here emits tables as pipe-
delimited rows inline, in document order, which keeps each question next to the
answer cell that belongs to it. That adjacency is what lets the extraction model
recover question/answer pairs from previously filled assessments.

Conversion goes through the hosted Docling service, which returns Markdown with
tables intact and handles far more layouts than the local libraries do. The
pdfplumber / python-docx loaders remain as a fallback for when Docling is down
or switched off, so an upload never fails purely because a container is
unreachable; they emit `[table]` markers instead of Markdown pipe tables, which
the extraction prompts accept either way.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable

from src import docling_client
from src.config import settings
from src.docling_client import DoclingError

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = (".pdf", ".docx")


class UnsupportedDocumentError(ValueError):
    """Raised for a file type the app cannot read."""


async def load_text(path: str | Path) -> str:
    """Extract the full text of a PDF or DOCX file, tables included."""
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise UnsupportedDocumentError(
            f"Cannot read '{path.name}'. Supported types: {', '.join(SUPPORTED_SUFFIXES)}"
        )
    if not path.is_file():
        raise FileNotFoundError(f"No such document: {path}")

    text = ""
    if settings.docling_enabled:
        try:
            text = (await docling_client.convert_file(path)).strip()
        except DoclingError as exc:
            if not settings.docling_fallback_local:
                raise UnsupportedDocumentError(f"Could not convert '{path.name}': {exc}") from exc
            logger.warning("Docling failed for %s, falling back to local extraction: %s", path.name, exc)

    if not text:
        # `load_text_local` is blocking (pdfplumber is CPU-bound), so it is kept
        # off the event loop the API and the answering fan-out share.
        text = (await asyncio.to_thread(load_text_local, path)).strip()

    if not text:
        raise UnsupportedDocumentError(
            f"No text found in '{path.name}'. Scanned images are not supported — enable DOCLING_DO_OCR."
        )

    logger.info("Loaded %s (%d characters)", path.name, len(text))
    return text


async def load_url_text(url: str) -> str:
    """Extract the text of a document Docling fetches by URL.

    Requires Docling — there is no local fallback for a remote source.
    """
    if not settings.docling_enabled:
        raise UnsupportedDocumentError("DOCLING_BASE_URL is not set, so URLs cannot be converted.")

    try:
        text = (await docling_client.convert_url(url)).strip()
    except DoclingError as exc:
        raise UnsupportedDocumentError(f"Could not convert '{url}': {exc}") from exc

    if not text:
        raise UnsupportedDocumentError(f"No text found at '{url}'.")

    logger.info("Loaded %s (%d characters)", url, len(text))
    return text


def load_text_local(path: str | Path) -> str:
    """Extract text without Docling, using pdfplumber / python-docx."""
    path = Path(path)
    loader = _LOADERS.get(path.suffix.lower())
    if loader is None:
        raise UnsupportedDocumentError(
            f"Cannot read '{path.name}'. Supported types: {', '.join(SUPPORTED_SUFFIXES)}"
        )
    return loader(path)


def _format_row(cells: list) -> str:
    """Render one table row as a pipe-delimited line, dropping empty rows."""
    values = [str(cell).replace("\n", " ").strip() if cell else "" for cell in cells]
    return " | ".join(values) if any(values) else ""


def _load_pdf(path: Path) -> str:
    import pdfplumber

    parts: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            parts.append(f"\n--- page {page_number} ---")

            page_text = page.extract_text() or ""
            if page_text.strip():
                parts.append(page_text.strip())

            # pdfplumber's extract_text already includes cell text, but without
            # row structure. Re-emitting the tables costs a few tokens and makes
            # the column a question's answer lives in unambiguous.
            for table in page.extract_tables():
                rows = [_format_row(row) for row in table]
                rendered = "\n".join(row for row in rows if row)
                if rendered:
                    parts.append(f"[table]\n{rendered}\n[/table]")

    return "\n".join(parts)


def _load_docx(path: Path) -> str:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = Document(str(path))
    parts: list[str] = []

    # `document.paragraphs` and `document.tables` are separate sequences that
    # lose interleaving, so the body XML is walked directly to keep reading order.
    for child in document.element.body.iterchildren():
        tag = child.tag.split("}")[-1]

        if tag == "p":
            text = Paragraph(child, document).text.strip()
            if text:
                parts.append(text)

        elif tag == "tbl":
            rows = [_format_row([cell.text for cell in row.cells]) for row in Table(child, document).rows]
            rendered = "\n".join(row for row in rows if row)
            if rendered:
                parts.append(f"[table]\n{rendered}\n[/table]")

    return "\n".join(parts)


_LOADERS: dict[str, Callable[[Path], str]] = {
    ".pdf": _load_pdf,
    ".docx": _load_docx,
}


def windows(text: str, size: int, overlap: int = 400) -> list[str]:
    """Split `text` into overlapping windows for per-window LLM extraction.

    Splits on paragraph boundaries so a question and its answer row are not cut
    apart mid-table. The overlap is carried as whole trailing paragraphs.
    """
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_length = 0

    for block in text.split("\n"):
        block_length = len(block) + 1
        if current_length + block_length > size and current:
            chunks.append("\n".join(current))
            current, current_length = _tail(current, overlap)
        current.append(block)
        current_length += block_length

    if current:
        chunks.append("\n".join(current))

    return chunks


def _tail(blocks: list[str], overlap: int) -> tuple[list[str], int]:
    """Return the trailing blocks of `blocks` totalling at most `overlap` chars."""
    kept: list[str] = []
    length = 0
    for block in reversed(blocks):
        block_length = len(block) + 1
        if length + block_length > overlap:
            break
        kept.insert(0, block)
        length += block_length
    return kept, length
