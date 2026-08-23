"""FastAPI application: REST endpoints plus the single-page frontend.

Run with:  uvicorn src.api:app --reload
"""

from __future__ import annotations

import logging
import unicodedata
from pathlib import Path
from urllib.parse import quote

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response

from src import service
from src.config import configure_logging, settings
from src.documents import SUPPORTED_SUFFIXES
from src.export_docx import render_docx
from src.export_pdf import ExportError, ExportOptions, render_pdf, selected_answers
from src.models import AssessmentResult, IngestResult, Language, SourceType

configure_logging()
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.ensure_directories()
    logger.info("Chat model: %s | Embeddings: %s", settings.groq_chat_model, settings.embedding_model)
    if not settings.groq_api_key:
        logger.warning("GROQ_API_KEY is not set — answering will fail until it is.")
    yield


app = FastAPI(
    title="Assessment Answering Agent",
    description="Answers assessment questionnaires from your guidelines and previously answered assessments.",
    version="0.1.0",
    lifespan=lifespan,
)


def _check_suffix(filename: str) -> None:
    if Path(filename).suffix.lower() not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail=f"'{filename}' is not supported. Upload {' or '.join(SUPPORTED_SUFFIXES)}.",
        )


async def _ingest_files(files: list[UploadFile], source_type: SourceType) -> list[IngestResult]:
    """Save and index a batch of uploads. Shared by both ingestion endpoints."""
    if not files:
        raise HTTPException(status_code=400, detail="No files were uploaded.")

    results = []
    for upload in files:
        _check_suffix(upload.filename or "")
        path = service.save_upload(upload.filename or "upload", await upload.read())
        results.append(await service.ingest(path, source_type))
    return results


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------


@app.get("/api/knowledge")
def get_knowledge() -> dict:
    """What is currently indexed."""
    return service.knowledge_stats()


@app.post("/api/knowledge/guidelines")
async def upload_guidelines(files: list[UploadFile] = File(...)) -> list[IngestResult]:
    """Index policy and guideline documents."""
    return await _ingest_files(files, SourceType.GUIDELINE)


@app.post("/api/knowledge/prior-assessments")
async def upload_prior_assessments(files: list[UploadFile] = File(...)) -> list[IngestResult]:
    """Index previously answered assessments as question/answer pairs."""
    return await _ingest_files(files, SourceType.PRIOR_ANSWER)


@app.delete("/api/knowledge/sources/{source_name}")
def remove_source(source_name: str) -> dict:
    """Remove one indexed file."""
    service.delete_source(source_name)
    return {"deleted": source_name}


@app.delete("/api/knowledge")
def clear_knowledge() -> dict:
    """Empty the knowledge base."""
    service.clear_knowledge()
    return {"cleared": True}


# ---------------------------------------------------------------------------
# Document library and previews
# ---------------------------------------------------------------------------


@app.get("/api/documents")
def get_documents() -> dict:
    """List uploaded files and the bundled documents available for trial runs."""
    documents = service.list_documents()
    return {
        "documents": documents,
        "uploaded_count": sum(document["origin"] == "uploaded" for document in documents),
        "trial_count": sum(document["origin"] == "trial" for document in documents),
    }


def _resolve_document(origin: str, category: str, name: str) -> Path:
    try:
        return service.resolve_document(origin, category, name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Document '{name}' was not found.") from exc


@app.get("/api/documents/{origin}/{category}/{name}/file")
def view_document(origin: str, category: str, name: str) -> FileResponse:
    """Open or download the original PDF/DOCX document."""
    path = _resolve_document(origin, category, name)
    return FileResponse(path, filename=path.name, content_disposition_type="inline")


@app.get("/api/documents/{origin}/{category}/{name}/preview")
def preview_document(origin: str, category: str, name: str) -> Response:
    """Return a browser preview: the original PDF or safe HTML converted from DOCX."""
    path = _resolve_document(origin, category, name)
    if path.suffix.lower() == ".pdf":
        return FileResponse(path, filename=path.name, content_disposition_type="inline")

    try:
        preview = service.docx_preview_html(path)
    except Exception as exc:  # noqa: BLE001 - normalize malformed Word files for the web client
        logger.exception("Could not preview %s", path.name)
        raise HTTPException(status_code=422, detail=f"Could not preview '{path.name}': {exc}") from exc

    return HTMLResponse(
        preview,
        headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/api/documents/{origin}/{category}/{name}/text")
async def view_extracted_text(origin: str, category: str, name: str) -> dict:
    """Extract and return the document text, using the persistent extraction cache."""
    path = _resolve_document(origin, category, name)
    try:
        text = await service.extracted_document_text(path)
    except Exception as exc:  # noqa: BLE001 - normalize converter failures for the web client
        logger.exception("Could not extract text from %s", path.name)
        raise HTTPException(status_code=422, detail=f"Could not extract text from '{path.name}': {exc}") from exc
    return {"name": path.name, "text": text, "characters": len(text)}


# ---------------------------------------------------------------------------
# Answering
# ---------------------------------------------------------------------------


@app.post("/api/assessments/answer")
async def answer_assessment(
    file: UploadFile = File(...),
    language: Language | None = Form(default=None),
    run_id: str | None = Form(default=None),
) -> AssessmentResult:
    """Answer a new assessment.

    `language` forces the output language ("ar" or "en"); omit it to answer each
    question in the language it was asked.

    `run_id` is chosen by the caller so it can watch the run while this request
    is still open — answering a long assessment is minutes of silence, and the
    identifier has to be known before the work starts to be of any use.
    """
    _check_suffix(file.filename or "")
    path = service.save_upload(file.filename or "assessment", await file.read())

    result = await service.answer_assessment(path, language=language, run_id=run_id)
    if not result.answers:
        raise HTTPException(
            status_code=422,
            detail=f"No questions could be extracted from '{result.source_name}'.",
        )
    return result


@app.get("/api/assessments/progress/{run_id}")
def assessment_progress(run_id: str) -> dict:
    """How far a run has got: questions found, answered, and left to answer."""
    state = service.run_progress(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"No run in progress with id '{run_id}'.")
    return state


def attachment_headers(filename: str) -> dict[str, str]:
    """`Content-Disposition` for a download, safe for a non-ASCII file name.

    HTTP header values are latin-1, so an Arabic assessment name raised
    UnicodeEncodeError inside Starlette and the download failed with a 500 —
    on precisely the corpus this system exists to serve. RFC 6266 answers it
    with two parameters: a transliterated `filename` that any client can read,
    and a percent-encoded `filename*` that modern browsers prefer.
    """
    stripped = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode()
    fallback = stripped.replace('"', "").strip() or "assessment"
    if fallback.startswith("."):
        fallback = f"assessment{fallback}"
    return {
        "Content-Disposition":
            f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quote(filename, safe="")}'
    }


@app.post("/api/assessments/export/pdf")
def export_pdf(
    result: AssessmentResult,
    include_flagged: bool = False,
    include_citations: bool = True,
    include_reasoning: bool = False,
) -> Response:
    """Render an answered assessment as a PDF.

    The result is posted back rather than looked up, because the interface lets
    a reviewer edit answers before exporting and those edits are the point.

    By default the file carries only answers that were not flagged for review:
    what goes back to an assessor should not silently include drafts the system
    itself was unsure of.
    """
    options = ExportOptions(
        include_flagged=include_flagged,
        include_citations=include_citations,
        include_reasoning=include_reasoning,
    )
    if not selected_answers(result, options):
        raise HTTPException(
            status_code=422,
            detail="No answer met the confidence threshold. Enable 'answers flagged for review' to export drafts.",
        )

    try:
        content = render_pdf(result, options)
    except ExportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    filename = f"{Path(result.source_name).stem or 'assessment'}.answers.pdf"
    return Response(
        content=content,
        media_type="application/pdf",
        headers=attachment_headers(filename),
    )


@app.post("/api/assessments/export/docx")
def export_docx(
    result: AssessmentResult,
    include_flagged: bool = False,
    include_citations: bool = True,
    include_reasoning: bool = False,
) -> Response:
    """Render an answered assessment as a Word document.

    Same selection rule and same options as the PDF export; the difference is
    that the reviewer can carry on editing in the file. Arabic is laid out by
    Word rather than by us, which makes this the better format for an Arabic
    questionnaire.
    """
    options = ExportOptions(
        include_flagged=include_flagged,
        include_citations=include_citations,
        include_reasoning=include_reasoning,
    )
    if not selected_answers(result, options):
        raise HTTPException(
            status_code=422,
            detail="No answer met the confidence threshold. Enable 'answers flagged for review' to export drafts.",
        )

    content = render_docx(result, options)
    filename = f"{Path(result.source_name).stem or 'assessment'}.answers.docx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=attachment_headers(filename),
    )


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": settings.groq_chat_model}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
