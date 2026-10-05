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

One class of PDF is routed away from Docling deliberately: see
`_prefers_local_extraction` and the bidi reconstruction below it.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from pathlib import Path
from typing import Callable

from bidi.algorithm import get_display

from src import docling_client
from src.config import settings
from src.docling_client import DoclingError

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = (".pdf", ".docx")


class UnsupportedDocumentError(ValueError):
    """Raised for a file type the app cannot read."""


# ---------------------------------------------------------------------------
# Right-to-left text layers
# ---------------------------------------------------------------------------
#
# Some Arabic PDFs — including the T2 password and safe-usage policies — store
# their text layer in *visual* order using Arabic presentation forms, the shapes
# the renderer draws rather than the letters an author typed. Docling reads
# those files as a series of disconnected fragments: it drops most of each
# sentence and reverses embedded numbers, which is how a 12-character minimum
# password length was indexed as 21.
#
# pdfplumber returns the same visual order but keeps every character, so the
# logical text can be recovered exactly: run the Unicode bidirectional
# algorithm to undo the reordering, then normalise the presentation forms back
# to letters. Both steps are standard and reversible, and the round trip is
# covered by tests.

_ARABIC_PRESENTATION = re.compile(r"[ﭐ-﷿ﹰ-﻿]")
_ARABIC_ANY = re.compile(r"[؀-ۿﭐ-﷿ﹰ-﻿]")

# Below these, a document is not Arabic enough for the question to arise: a
# single Arabic word in an English policy is not evidence of a visual-order
# text layer, and misrouting a well-formed document costs Docling's tables.
_MIN_ARABIC_CHARS = 200
_MIN_PRESENTATION_RATIO = 0.5

# Below this many characters of text layer per page, a PDF is treated as scanned
# and OCR is switched on for it alone. Real pages in this corpus run 600-2000.
_MIN_CHARS_PER_PAGE = 120

# These PDFs' fonts map Arabic letters onto Persian/Urdu look-alikes, which
# survive NFKC because they are distinct letters rather than shape variants.
# Folding them keeps "يجب" spelled one way across the corpus, so retrieval and
# clause matching are not split across two encodings of the same word.
_LETTER_FOLD = str.maketrans(
    {
        "ی": "ي",  # Farsi yeh   -> Arabic yeh
        "ک": "ك",  # Keheh       -> Kaf
        "ھ": "ه",  # Heh doachashmee -> Heh
    }
)


def to_logical_order(text: str) -> str:
    """Recover logical-order Arabic from a visual-order line.

    `get_display` is the Unicode bidirectional algorithm (UAX #9). For a line
    whose only embedding levels are the RTL paragraph and its LTR runs — which
    is what a PDF text layer holds — the reordering is its own inverse, so
    applying it to visual order yields logical order. Latin and numeric runs
    survive intact: "AES-256" and "NIST SP 800-63B" come back unchanged, and
    "12" does not become "21".

    NFKC then maps the presentation forms back to the letters they render,
    including the lam-alef ligatures. It runs *after* the reordering, because a
    ligature is one character in visual order and two in logical order.
    """
    if not _ARABIC_ANY.search(text):
        return text
    reordered = get_display(text, base_dir="R")
    return unicodedata.normalize("NFKC", reordered).translate(_LETTER_FOLD)


def _visual_order_arabic_score(path: Path, pages: int = 4) -> tuple[int, float]:
    """Arabic character count and presentation-form share of a PDF's opening pages."""
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        sample = "\n".join((page.extract_text() or "") for page in pdf.pages[:pages])

    arabic = len(_ARABIC_ANY.findall(sample))
    presentation = len(_ARABIC_PRESENTATION.findall(sample))
    return arabic, (presentation / arabic if arabic else 0.0)


# An Arabic line whose list marker has been carried to the end: "…العقد؟ وما .25"
# should read "25. …العقد؟ وما". The marker is an LTR run inside an RTL
# paragraph, so it belongs at the logical start even though it is drawn on the
# right, and converters routinely emit it last.
#
# The dot is what distinguishes a marker from a value. "25." reversed becomes
# ".25", so the punctuation travels with the number, while a figure quoted
# mid-sentence carries none. Without that test a line cut after its number
# would be rewritten with that figure promoted to a list marker.
_TRAILING_MARKER = re.compile(r"^(?P<body>.*?)[\s ]+(?:\.(?P<dotted>\d{1,3})|(?P<plain>\d{1,3})\.)$")
_ARABIC_LETTERS = re.compile(r"[ء-ي]")


def repair_rtl_numbering(text: str) -> str:
    """Move a displaced list marker back to the start of an Arabic line.

    Only the marker moves; the words are already in logical order, so running
    the bidi algorithm over these lines would reverse letters that are
    perfectly correct. This is the narrower and safer repair.

    It matters more than it looks. With the number stranded at the end, the
    extraction model has to guess where each question begins, and it guessed
    differently from run to run — which is why the same questionnaire yielded
    27 questions on one run and 28 on the next, and why Arabic question ids
    came back as ".25".
    """
    repaired = []
    for line in text.splitlines():
        stripped = line.strip()
        match = _TRAILING_MARKER.match(stripped) if stripped else None
        if match and _ARABIC_LETTERS.search(match.group("body")):
            body = match.group("body").strip()
            number = match.group("dotted") or match.group("plain")
            if body:
                repaired.append(f"{number}. {body}")
                continue
        repaired.append(line)
    return "\n".join(repaired)


def _looks_scanned(path: Path, pages: int = 6) -> bool:
    """Whether a PDF carries too little text to have a real text layer.

    OCR is decided per file rather than per deployment. Forcing it on costs
    roughly 2.3x on ingestion and, on a born-digital policy, changes nothing
    that matters: table structure is recognised by a separate model that runs
    either way, so the only text it adds is whatever it reads off the logos —
    "E: info@t2.com" and a stray full-width colon, scattered through the
    chunks. Forcing it off would silently index a scanned document as empty.
    Sampling the text layer answers the question directly.
    """
    if path.suffix.lower() != ".pdf":
        return False

    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            sample = pdf.pages[: min(pages, len(pdf.pages))]
            if not sample:
                return False
            characters = sum(len((page.extract_text() or "").strip()) for page in sample)
        per_page = characters / len(sample)
    except Exception as exc:  # noqa: BLE001 - detection must never fail an upload
        logger.debug("Could not sample %s for a text layer: %s", path.name, exc)
        return False

    if per_page < _MIN_CHARS_PER_PAGE:
        logger.info("Enabling OCR for %s: only %.0f characters per page of text layer", path.name, per_page)
        return True
    return False


def _prefers_local_extraction(path: Path) -> bool:
    """Whether this PDF should bypass Docling for the RTL-aware local loader."""
    if path.suffix.lower() != ".pdf":
        return False

    try:
        arabic, ratio = _visual_order_arabic_score(path)
    except Exception as exc:  # noqa: BLE001 - routing must never fail an upload
        logger.debug("Could not sample %s for text direction: %s", path.name, exc)
        return False

    if arabic >= _MIN_ARABIC_CHARS and ratio >= _MIN_PRESENTATION_RATIO:
        logger.info(
            "Routing %s to the local RTL loader: %d Arabic characters, %.0f%% presentation forms",
            path.name,
            arabic,
            ratio * 100,
        )
        return True

    logger.debug(
        "Routing %s to Docling: %d Arabic characters, %.0f%% presentation forms",
        path.name,
        arabic,
        ratio * 100,
    )
    return False


async def load_text(path: str | Path) -> str:
    """Extract the full text of a PDF or DOCX file, tables included."""
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise UnsupportedDocumentError(f"Cannot read '{path.name}'. Supported types: {', '.join(SUPPORTED_SUFFIXES)}")
    if not path.is_file():
        raise FileNotFoundError(f"No such document: {path}")

    text = ""
    local_only = await asyncio.to_thread(_prefers_local_extraction, path)
    if settings.docling_enabled and not local_only:
        do_ocr = settings.docling_do_ocr or (
            settings.docling_ocr_auto and await asyncio.to_thread(_looks_scanned, path)
        )
        try:
            text = (await docling_client.convert_file(path, do_ocr=do_ocr)).strip()
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

    # Applied to whichever path produced the text: both Docling and the bidi
    # reconstruction strand an RTL list marker at the end of its line.
    text = repair_rtl_numbering(text)

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
        raise UnsupportedDocumentError(f"Cannot read '{path.name}'. Supported types: {', '.join(SUPPORTED_SUFFIXES)}")
    return loader(path)


def _format_row(cells: list, transform: Callable[[str], str] = lambda text: text) -> str:
    """Render one table row as a pipe-delimited line, dropping empty rows."""
    values = [transform(str(cell).replace("\n", " ")).strip() if cell else "" for cell in cells]
    return " | ".join(values) if any(values) else ""


def _load_pdf(path: Path) -> str:
    import pdfplumber

    # Decided once per document, not per line: direction is a property of how
    # the file was produced, and a per-line guess would flip on the English
    # headers and page furniture an Arabic policy also carries.
    transform = to_logical_order if _prefers_local_extraction(path) else _identity

    parts: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            parts.append(f"\n--- page {page_number} ---")

            page_text = page.extract_text() or ""
            if page_text.strip():
                parts.append("\n".join(transform(line) for line in page_text.strip().splitlines()))

            # pdfplumber's extract_text already includes cell text, but without
            # row structure. Re-emitting the tables costs a few tokens and makes
            # the column a question's answer lives in unambiguous.
            for table in page.extract_tables():
                rows = [_format_row(row, transform) for row in table]
                rendered = "\n".join(row for row in rows if row)
                if rendered:
                    parts.append(f"[table]\n{rendered}\n[/table]")

    return "\n".join(parts)


def _identity(text: str) -> str:
    return text


_HEADING_STYLE = re.compile(r"^Heading\s+([1-6])$", re.IGNORECASE)
_LIST_STYLE = re.compile(r"list\s*(number|bullet|paragraph)", re.IGNORECASE)
_LITERAL_NUMBER = re.compile(r"^\s*(\d+(?:[.\u066b]\d+){0,5})[.)\-]?\s+\S")


def _has_numbering(paragraph) -> bool:
    """True when Word generates this paragraph's list number from the numbering XML."""
    p_pr = paragraph._p.pPr
    return p_pr is not None and p_pr.numPr is not None


def _load_docx(path: Path) -> str:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = Document(str(path))
    parts: list[str] = []

    # Walk the body XML directly: document.paragraphs and document.tables are
    # separate sequences and lose the interleaving that reading order depends on.
    for child in document.element.body.iterchildren():
        tag = child.tag.split("}")[-1]

        if tag == "p":
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            if not text:
                continue

            style_name = paragraph.style.name if paragraph.style is not None else ""

            heading = _HEADING_STYLE.match(style_name.strip())
            if heading:
                parts.append(f"{'#' * int(heading.group(1))} {text}")
                continue

            if _LIST_STYLE.search(style_name) or _has_numbering(paragraph):
                # Word keeps a numbered list's number in the numbering XML, so
                # paragraph.text arrives unnumbered. Keep an author-typed number
                # as a real clause id; otherwise mark it a bullet rather than
                # inventing a number that would poison citations.
                parts.append(text if _LITERAL_NUMBER.match(text) else f"- {text}")
                continue

            parts.append(text)

        elif tag == "tbl":
            rows = [_format_row([cell.text for cell in row.cells]) for row in Table(child, document).rows]
            rendered = "\n".join(row for row in rows if row)
            if rendered:
                parts.append(f"[table]\n{rendered}\n[/table]")

    return "\n\n".join(parts)


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
