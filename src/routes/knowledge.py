"""The knowledge base's routes: the shared knowledge base, or a product's (plan 021).

Moved out of `src/api.py` and included where they were. Each takes an optional
`product`; with none, every call below is the one these routes made before
products existed. A product that is not the caller's team's is absent
(`product_not_found`), as everything of another team's is.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile

from src import events, products, service
from src.documents import SUPPORTED_SUFFIXES
from src.errors import Invalid, NotFound, UnsupportedFile
from src.identity import User
from src.models import IngestResult, SourceType
from src.routes.auth import current_user

router = APIRouter()


def _scope(user: User, product: str) -> dict[str, str]:
    """The keyword a scoped call takes, or nothing for the shared knowledge base."""
    if not product:
        return {}
    return {"product_id": products.get(user.team_id, product).id}


def check_suffix(filename: str) -> None:
    """Refuse a file the knowledge base cannot read, judged by its suffix (`document_type_unsupported`)."""
    if Path(filename).suffix.lower() not in SUPPORTED_SUFFIXES:
        raise UnsupportedFile(
            f"'{filename}' is not supported. Upload {' or '.join(SUPPORTED_SUFFIXES)}.",
            code="document_type_unsupported",
        )


async def _ingest_files(
    files: list[UploadFile],
    source_type: SourceType,
    authority: str = "ours",
    team_id: str | None = None,
    scope: dict[str, str] | None = None,
) -> list[IngestResult]:
    """Save and index a batch of uploads into the shared knowledge base or a product's."""
    if not files:
        raise Invalid("No files were uploaded.", code="no_files")

    # Every name checked before any file is saved. Checked one at a time, a
    # policy uploaded beside a stray .zip was indexed and the request still
    # failed, leaving nobody sure which half had happened.
    for upload in files:
        check_suffix(upload.filename or "")

    results = []
    for upload in files:
        path = service.save_upload(upload.filename or "upload", await upload.read(), team_id)
        results.append(await service.ingest(path, source_type, authority, team_id, **(scope or {})))
    return results


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------


# Every route here takes a session. The corpus has no owner -- it is what the
# organisation is bound by, and everyone on the team works from the same one --
# but "shared" is not "public": these read the policies out, index documents
# into them, and one of them empties the lot. Who did each of those is recorded,
# so a shared corpus is still an attributable one.


@router.get("/api/knowledge")
def get_knowledge(product: str = "", user: User = Depends(current_user)) -> dict[str, Any]:
    """What is currently indexed for the caller's team, shared or for one `product`."""
    return service.knowledge_stats(user.team_id, **_scope(user, product))


@router.post("/api/knowledge/guidelines")
async def upload_guidelines(
    files: list[UploadFile] = File(...),
    authority: str = Form(default="ours"),
    product: str = Form(default=""),
    user: User = Depends(current_user),
) -> list[IngestResult]:
    """Index policy and guideline documents.

    `authority` is "ours" for something this organisation wrote and is bound by,
    "external" for a law, regulation or framework it is subject to. The drafter
    is told which, because our policy says what we *do* and a regulation says
    what we are *required* to do -- and answering the second as though it were
    the first claims a control we may not have.
    """
    if authority not in ("ours", "external"):
        raise Invalid("authority must be 'ours' or 'external'.", code="authority_invalid")
    scope = _scope(user, product)
    results = await _ingest_files(files, SourceType.GUIDELINE, authority, user.team_id, scope)
    _record_indexing(user, results, authority=authority, **scope)
    return results


# No route takes a filled questionnaire into the answer memory. Answers arrive
# one at a time -- `POST /api/memory`, or an edited answer approved on its card --
# so every one of them was read by the person who put it there. The command line
# (`python -m src.cli answers`) remains for whoever sets up a corpus.


def _record_indexing(user: User, results: list[IngestResult], **payload: str) -> None:
    """One event per file that actually went in."""
    for result in results:
        if result.error or not result.chunks_indexed:
            continue
        events.record(
            user,
            events.DOCUMENT_INDEXED,
            subject_type="document",
            subject_id=result.source_name,
            chunks=result.chunks_indexed,
            source_type=result.source_type.value,
            **payload,
        )


@router.delete("/api/knowledge/sources/{source_name}")
def remove_source(source_name: str, product: str = "", user: User = Depends(current_user)) -> dict[str, Any]:
    """Remove one indexed policy document, from the shared knowledge base or a `product`'s."""
    scope = _scope(user, product)
    try:
        service.delete_source(source_name, user.team_id, **scope)
    except KeyError as missing:
        raise NotFound(f"{source_name!r} is not in the knowledge base.", code="source_not_found") from missing
    events.record(
        user,
        events.SOURCE_REMOVED,
        subject_type="document",
        subject_id=source_name,
        **scope,
    )
    return {"deleted": source_name}


@router.delete("/api/knowledge")
def clear_knowledge(product: str = "", user: User = Depends(current_user)) -> dict[str, Any]:
    """Remove every policy document, shared or a `product`'s. The answer memory is left as it is."""
    scope = _scope(user, product)
    service.clear_knowledge(user.team_id, **scope)
    events.record(user, events.SOURCE_REMOVED, subject_type="document", subject_id="*", all=True, **scope)
    return {"cleared": True}
