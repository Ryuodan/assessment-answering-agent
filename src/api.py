"""FastAPI application: REST endpoints plus the single-page frontend.

Run with:  uvicorn src.api:app --reload
"""

from __future__ import annotations

import logging
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response

from src import service
from src.config import configure_logging, settings
from src.documents import SUPPORTED_SUFFIXES
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
) -> AssessmentResult:
    """Answer a new assessment.

    `language` forces the output language ("ar" or "en"); omit it to answer each
    question in the language it was asked.
    """
    _check_suffix(file.filename or "")
    path = service.save_upload(file.filename or "assessment", await file.read())

    result = await service.answer_assessment(path, language=language)
    if not result.answers:
        raise HTTPException(
            status_code=422,
            detail=f"No questions could be extracted from '{result.source_name}'.",
        )
    return result


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": settings.groq_chat_model}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
