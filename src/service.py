"""Application service — the one orchestration layer the API and CLI share.

Both front ends do the same three things (ingest a guideline, ingest a previous
assessment, answer a new one), so those flows live here and the front ends stay
thin: HTTP plumbing in `api.py`, argument parsing in `cli.py`, no logic in either.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import re
import uuid
from pathlib import Path

from src.config import PROJECT_ROOT, settings
from src.documents import SUPPORTED_SUFFIXES, load_text
from src.extraction import extract_qa_pairs
from src.graph import answer_one_question, assessment_graph, failed_answer
from src.knowledge import get_store
from src.models import (
    AnsweredQuestion,
    AssessmentResult,
    IngestResult,
    Language,
    Question,
    SourceType,
)

logger = logging.getLogger(__name__)

TRIAL_DOCUMENT_DIRS: dict[str, Path] = {
    "guideline": PROJECT_ROOT / "demo_data" / "guidelines",
    "prior_assessment": PROJECT_ROOT / "demo_data" / "prior_assessments",
    "new_assessment": PROJECT_ROOT / "demo_data" / "new_assessments",
}

_DOCUMENT_LABELS = {
    "guideline": "Trial guideline",
    "prior_assessment": "Trial completed assessment",
    "new_assessment": "Trial blank assessment",
    "uploaded": "Uploaded document",
}

_ARABIC_TEXT = re.compile(r"[؀-ۿ]")


async def ingest(path: str | Path, source_type: SourceType) -> IngestResult:
    """Index one uploaded file as either a guideline or a previously answered assessment.

    Failures are returned, not raised: a batch upload of ten policies should
    report which one was unreadable and index the other nine.
    """
    path = Path(path)
    store = get_store()

    try:
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        original = store.source_with_hash(content_hash, excluding=path.name)
        if original:
            logger.info("Skipping '%s': byte-identical to already-indexed '%s'", path.name, original)
            return IngestResult(
                source_name=path.name,
                source_type=source_type,
                chunks_indexed=0,
                duplicate_of=original,
            )

        text = await extracted_document_text(path)

        if source_type is SourceType.GUIDELINE:
            chunks = store.add_guideline(path.name, text, content_hash)
            return IngestResult(source_name=path.name, source_type=source_type, chunks_indexed=chunks)

        pairs = await extract_qa_pairs(text)
        chunks = store.add_prior_answers(path.name, pairs, content_hash)
        return IngestResult(
            source_name=path.name,
            source_type=source_type,
            chunks_indexed=chunks,
            qa_pairs_found=len(pairs),
        )

    except Exception as exc:  # noqa: BLE001 - reported per file, not fatal to the batch
        logger.exception("Failed to ingest %s", path.name)
        return IngestResult(source_name=path.name, source_type=source_type, chunks_indexed=0, error=str(exc))


async def answer_assessment(path: str | Path, language: Language | None = None) -> AssessmentResult:
    """Answer every question in an assessment document.

    `language` forces the output language; leaving it None answers each question
    in whatever language it was asked.
    """
    path = Path(path)
    text = await extracted_document_text(path)

    final_state = await assessment_graph().ainvoke(
        {
            "source_name": path.name,
            "document_text": text,
            "language": language,
            "questions": [],
            "answers": [],
        },
        # Bounds how many questions hit Groq at once. Without it a 60-question
        # assessment fans out 60 ways and trips the rate limit.
        config={"max_concurrency": settings.max_concurrent_questions},
    )

    questions = final_state.get("questions", [])
    answers = final_state.get("answers", [])

    # The fan-out completes out of order; the filled assessment must read in
    # document order, so answers are re-sorted against the question list.
    position = {question.id: index for index, question in enumerate(questions)}
    answers.sort(key=lambda answered: position.get(answered.question.id, len(position)))

    return AssessmentResult(
        run_id=uuid.uuid4().hex[:12],
        source_name=path.name,
        language=final_state.get("language") or final_state.get("document_language") or "en",
        questions_found=len(questions),
        answers=answers,
    )


async def answer_questions(
    questions: list[Question], language: Language | None = None
) -> list[AnsweredQuestion]:
    """Answer a list of questions that did not come from a document.

    The same per-question graph the assessment flow fans out to, minus the
    extraction step. Used by the evaluation harness, which holds its questions
    as data, and by any caller with a question already in hand.
    """
    semaphore = asyncio.Semaphore(settings.max_concurrent_questions)

    async def run(question: Question) -> AnsweredQuestion:
        async with semaphore:
            try:
                return await answer_one_question(question, language or question.language)
            except Exception as exc:  # noqa: BLE001 - contained per question, as in the fan-out
                # The document flow already contains a per-question failure; this
                # path did not, so a single transient upstream error — a model
                # briefly withdrawn from the region, say — discarded a whole
                # forty-two question run that had nearly finished.
                logger.exception("Failed to answer question %s", question.id)
                return failed_answer(question, exc)

    return list(await asyncio.gather(*(run(question) for question in questions)))


def knowledge_stats() -> dict:
    """Counts and indexed file names, for the UI's knowledge panel."""
    return get_store().stats()


def delete_source(source_name: str) -> None:
    """Remove one previously uploaded file from the knowledge base."""
    get_store().delete_source(source_name)


def clear_knowledge() -> None:
    """Empty the knowledge base."""
    get_store().reset()


def save_upload(filename: str, content: bytes) -> Path:
    """Persist an uploaded file under the configured upload directory.

    Only the basename is used, so a crafted filename such as `../../.env` cannot
    escape the upload directory.
    """
    settings.ensure_directories()
    destination = settings.upload_dir / Path(filename).name
    destination.write_bytes(content)
    return destination


def list_documents() -> list[dict]:
    """Return uploaded and bundled trial documents available to the web UI."""
    settings.ensure_directories()
    documents: list[dict] = []

    for path in _document_files(settings.upload_dir):
        documents.append(_document_info(path, origin="uploaded", category="uploaded"))

    for category, directory in TRIAL_DOCUMENT_DIRS.items():
        for path in _document_files(directory):
            documents.append(_document_info(path, origin="trial", category=category))

    return sorted(
        documents,
        key=lambda document: (document["origin"] != "uploaded", document["category"], document["name"]),
    )


def resolve_document(origin: str, category: str, name: str) -> Path:
    """Resolve a catalog document without allowing traversal outside its directory."""
    if not name or name != Path(name).name or Path(name).suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError("Invalid document name.")

    if origin == "uploaded" and category == "uploaded":
        directory = settings.upload_dir
    elif origin == "trial" and category in TRIAL_DOCUMENT_DIRS:
        directory = TRIAL_DOCUMENT_DIRS[category]
    else:
        raise ValueError("Invalid document location.")

    base = directory.resolve()
    path = (base / name).resolve()
    if path.parent != base:
        raise ValueError("Invalid document path.")
    if not path.is_file():
        raise FileNotFoundError(name)
    return path


async def extracted_document_text(path: str | Path) -> str:
    """Return extracted text, caching it until the source or converter settings change."""
    path = Path(path)
    settings.ensure_directories()
    cache_path = _extracted_text_cache_path(path)

    if cache_path.is_file() and cache_path.stat().st_mtime_ns >= path.stat().st_mtime_ns:
        return cache_path.read_text(encoding="utf-8")

    text = await load_text(path)
    cache_path.write_text(text, encoding="utf-8")
    return text


def docx_preview_html(path: str | Path) -> str:
    """Render a safe, self-contained HTML preview of a Word document."""
    from docx import Document as WordDocument
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    path = Path(path)
    if path.suffix.lower() != ".docx":
        raise ValueError("HTML preview is only available for DOCX files.")

    document = WordDocument(str(path))
    blocks: list[str] = []
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            blocks.append(_preview_paragraph(Paragraph(child, document)))
        elif tag == "tbl":
            blocks.append(_preview_table(Table(child, document)))

    title = html.escape(path.stem.replace("_", " ").replace("-", " ").title())
    content = "\n".join(blocks)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 28px; background: #e8eaee; color: #1b1d21;
          font: 15px/1.55 Arial, "Noto Sans Arabic", sans-serif; }}
  .page {{ width: min(850px, 100%); min-height: 1050px; margin: 0 auto; padding: 58px 64px;
           counter-reset: preview-list;
           background: white; box-shadow: 0 2px 16px rgba(0,0,0,.14); }}
  h1, h2, h3, h4, h5, h6 {{ line-height: 1.25; margin: 1.2em 0 .45em; }}
  h1:first-child, h2:first-child {{ margin-top: 0; }}
  p {{ margin: .55em 0; white-space: normal; }}
  .spacer {{ height: .75em; }}
  .list-bullet {{ padding-inline-start: 1.4em; }}
  .list-bullet::before {{ content: "•"; display: inline-block; width: 1.2em; margin-inline-start: -1.2em; }}
  .list-number {{ padding-inline-start: 1.4em; }}
  .list-number {{ counter-increment: preview-list; }}
  .list-number::before {{ content: counter(preview-list) "."; display: inline-block; width: 1.4em;
                          margin-inline-start: -1.4em; }}
  .align-center {{ text-align: center; }}
  .align-right {{ text-align: right; }}
  .align-justify {{ text-align: justify; }}
  table {{ width: 100%; border-collapse: collapse; margin: 1em 0; font-size: 13px; }}
  th, td {{ border: 1px solid #aeb4bd; padding: 7px 9px; vertical-align: top; text-align: start; }}
  th {{ background: #edf1f6; font-weight: 700; }}
  [dir="rtl"] {{ text-align: right; }}
  @media (max-width: 700px) {{ body {{ padding: 0; }} .page {{ padding: 28px 22px; min-height: 100vh; }} }}
</style>
</head>
<body><main class="page">{content}</main></body>
</html>"""


def _preview_paragraph(paragraph) -> str:
    text = paragraph.text
    if not text.strip():
        return '<div class="spacer"></div>'

    style_name = paragraph.style.name if paragraph.style is not None else ""
    heading_match = re.fullmatch(r"Heading\s+([1-6])", style_name, flags=re.IGNORECASE)
    tag = f"h{heading_match.group(1)}" if heading_match else "p"

    classes = []
    lowered_style = style_name.lower()
    if "list bullet" in lowered_style:
        classes.append("list-bullet")
    elif "list number" in lowered_style:
        classes.append("list-number")

    alignment_class = {1: "align-center", 2: "align-right", 3: "align-justify"}.get(paragraph.alignment)
    if alignment_class:
        classes.append(alignment_class)

    attributes = []
    if classes:
        attributes.append(f'class="{" ".join(classes)}"')
    if _ARABIC_TEXT.search(text):
        attributes.append('dir="rtl"')

    rendered_runs = "".join(_preview_run(run) for run in paragraph.runs)
    if not rendered_runs:
        rendered_runs = html.escape(text)
    attrs = f" {' '.join(attributes)}" if attributes else ""
    return f"<{tag}{attrs}>{rendered_runs}</{tag}>"


def _preview_run(run) -> str:
    rendered = html.escape(run.text).replace("\t", "&emsp;").replace("\n", "<br>")
    if not rendered:
        return ""
    if run.bold:
        rendered = f"<strong>{rendered}</strong>"
    if run.italic:
        rendered = f"<em>{rendered}</em>"
    if run.underline:
        rendered = f"<u>{rendered}</u>"
    return rendered


def _preview_table(table) -> str:
    rows = []
    for row_index, row in enumerate(table.rows):
        cells = []
        seen_cells = set()
        for cell in row.cells:
            cell_id = id(cell._tc)
            if cell_id in seen_cells:
                continue
            seen_cells.add(cell_id)

            cell_tag = "th" if row_index == 0 else "td"
            text = cell.text
            direction = ' dir="rtl"' if _ARABIC_TEXT.search(text) else ""
            paragraphs = "<br>".join(
                "".join(_preview_run(run) for run in paragraph.runs) or html.escape(paragraph.text)
                for paragraph in cell.paragraphs
                if paragraph.text.strip()
            )
            cells.append(f"<{cell_tag}{direction}>{paragraphs}</{cell_tag}>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return f"<table>{''.join(rows)}</table>"


def _document_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )


def _document_info(path: Path, *, origin: str, category: str) -> dict:
    title = path.stem.replace("_", " ").replace("-", " ").strip().title()
    return {
        "name": path.name,
        "title": title,
        "origin": origin,
        "category": category,
        "label": _DOCUMENT_LABELS[category],
        "extension": path.suffix.lower().lstrip("."),
        "size_bytes": path.stat().st_size,
    }


# Bumped whenever the extraction code changes in a way that alters its output,
# so cached text from an older, worse extractor is not silently reused.
_EXTRACTION_VERSION = "3"


def _extracted_text_cache_path(path: Path) -> Path:
    cache_input = "\0".join(
        (
            _EXTRACTION_VERSION,
            str(path.resolve()),
            settings.docling_base_url,
            str(settings.docling_do_ocr),
            str(settings.docling_ocr_auto),
            settings.docling_image_export_mode,
        )
    )
    cache_key = hashlib.sha256(cache_input.encode("utf-8")).hexdigest()[:24]
    return settings.extracted_text_dir / f"{cache_key}.txt"
