"""What the HTTP surface does with input designed to break it.

Every path here reaches the filesystem with a segment the caller controls, so
these are the tests that decide whether the service can face a network. They
run against an isolated upload directory: an earlier throwaway version of this
probe wrote its stubs into the real corpus.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import service
from src.api import app
from src.config import settings


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Point every writable directory at a temporary one."""
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setattr(settings, "upload_dir", uploads)
    monkeypatch.setattr(settings, "extracted_text_dir", tmp_path / "extracted")

    async def never_index(path, source_type):
        raise AssertionError("a hostile upload must not reach ingestion in these tests")

    return uploads


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# --- reading a document ----------------------------------------------------


@pytest.mark.parametrize("name", [
    "../../.env",
    "....//....//.env",
    "%2e%2e%2f%2e%2e%2f.env",
    "..%5c..%5c.env",
    "..",
    ".",
    "",
    "a/b/c.pdf",
    "x.pdf%00.txt",
])
def test_no_document_name_escapes_its_directory(client, name):
    response = client.get(f"/api/documents/uploaded/uploaded/{name}/file")

    assert response.status_code in (400, 404, 405, 422), response.status_code
    assert "GROQ" not in response.text and "API_KEY" not in response.text


@pytest.mark.parametrize(("origin", "category"), [
    ("uploaded", "secrets"),
    ("trial", "uploaded"),          # an origin that no longer exists
    ("..", ".."),
    ("trial", "../../.."),
])
def test_only_known_locations_can_be_read(client, origin, category):
    response = client.get(f"/api/documents/{origin}/{category}/policy.pdf/file")
    assert response.status_code in (400, 404, 422)


def test_a_raw_null_byte_never_reaches_the_route(client):
    """Kept as a test rather than dropped: the guarantee is that the transport
    rejects it, so the route is never asked to reason about it."""
    import httpx2

    with pytest.raises(httpx2.InvalidURL):
        client.get("/api/documents/uploaded/uploaded/x.pdf\x00.txt/file")


def test_a_supported_suffix_is_still_required(client):
    """The allowlist is what stops the endpoint serving .env or a private key."""
    assert client.get("/api/documents/uploaded/uploaded/id_rsa/file").status_code == 400


# --- uploading -------------------------------------------------------------


@pytest.mark.parametrize("name", ["../../.env.pdf", "a/b/c.pdf", r"..\..\evil.pdf"])
def test_an_upload_lands_inside_the_upload_directory(client, isolated, monkeypatch, name):
    """A crafted name must be reduced to a bare filename before it is written."""
    async def stub(path, source_type):
        from src.models import IngestResult
        return IngestResult(source_name=path.name, source_type=source_type, chunks_indexed=0)

    monkeypatch.setattr(service, "ingest", stub)
    response = client.post(
        "/api/knowledge/guidelines",
        files={"files": (name, b"%PDF-1.4 stub", "application/pdf")},
    )

    assert response.status_code == 200
    written = list(isolated.rglob("*"))
    assert written, "the upload should have been saved"
    for path in written:
        assert path.parent == isolated, f"{path} escaped {isolated}"


@pytest.mark.parametrize("name", [".", "..", "", "notes.txt", "archive.zip", "script.sh"])
def test_an_unusable_name_or_type_is_refused_not_crashed(client, name):
    response = client.post(
        "/api/knowledge/guidelines",
        files={"files": (name, b"stub", "application/octet-stream")},
    )
    assert response.status_code in (400, 415, 422), response.status_code


def test_an_upload_with_no_files_is_refused(client):
    assert client.post("/api/knowledge/guidelines", files=[]).status_code in (400, 422)


# --- search ----------------------------------------------------------------


@pytest.mark.parametrize("query", [
    "'; DROP TABLE chunks; --",
    "<script>alert(1)</script>",
    "../../etc/passwd",
    "\x00",
    "a" * 5000,
    '"' * 50,
    "-" * 50,
    "\\",
    "[",
])
def test_no_search_query_can_break_the_endpoint(client, query):
    """The query reaches a regex, a tokeniser and a vector store; none of them
    may turn a strange string into a 500."""
    response = client.get("/api/search", params={"q": query, "mode": "keyword"})
    assert response.status_code == 200, response.text


def test_the_search_limit_cannot_be_driven_negative_or_huge(client):
    for limit in (-5, 0, 10_000_000):
        response = client.get("/api/search", params={"q": "policy", "limit": limit})
        assert response.status_code == 200
        assert len(response.json()["results"]) <= 50


# --- when something downstream is broken -----------------------------------


@pytest.mark.parametrize(("target", "url"), [
    ("src.service.knowledge_stats", "/api/knowledge"),
    ("src.service.search_knowledge", "/api/search?q=policy"),
    ("src.service.list_documents", "/api/documents"),
])
def test_a_broken_dependency_returns_a_clean_500(target, url):
    """Everything here talks to something that can be down. The person gets a
    sentence; the stack trace stays in the log rather than in the browser."""
    from unittest.mock import patch

    boom = ConnectionError("chroma is down at /srv/internal/path")
    with patch(target, side_effect=boom):
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(url)

    assert response.status_code == 500
    assert "/srv/internal/path" not in response.text
    assert "Traceback" not in response.text
    assert response.json()["detail"]


def test_search_still_answers_when_the_embedding_host_is_down():
    """Meaning-based search needs a remote host; literal search does not. Losing
    one must not take the other with it."""
    from unittest.mock import patch

    with patch("src.knowledge.KnowledgeStore.search", side_effect=TimeoutError("no answer")):
        with TestClient(app) as client:
            response = client.get("/api/search", params={"q": "policy", "mode": "hybrid"})

    assert response.status_code == 200
    assert response.json()["degraded"] is True
