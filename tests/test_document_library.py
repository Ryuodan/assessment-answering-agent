"""Document catalog, preview, and extracted-text cache tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import knowledge, products, service
from src.api import app
from src.config import settings
from tests.conftest import FakeVectorStore, bare_store

TEAM = settings.default_team


@pytest.fixture
def stores(monkeypatch):
    """A fake index per (team, product), so deleting a product never waits on Chroma."""
    made: dict[tuple[str, str], knowledge.KnowledgeStore] = {}

    def get_store(team_id=None, *, product_id=""):
        key = (team_id or TEAM, product_id)
        if key not in made:
            made[key] = bare_store(FakeVectorStore([]))
            made[key]._store.delete_collection = lambda key=key: made.pop(key, None)
        return made[key]

    monkeypatch.setattr("src.knowledge.get_store", get_store)
    return made


def _temporary_document_storage(monkeypatch, tmp_path):
    upload_dir = tmp_path / "uploads"
    extracted_dir = tmp_path / "extracted"
    monkeypatch.setattr(settings, "upload_dir", upload_dir)
    monkeypatch.setattr(settings, "extracted_text_dir", extracted_dir)
    upload_dir.mkdir()
    extracted_dir.mkdir()
    return upload_dir, extracted_dir


def test_the_catalog_lists_what_was_uploaded_and_nothing_else(monkeypatch, tmp_path):
    """It used to bundle a set of invented policies for a first run. They were
    scaffolding, and they left a document list where half the entries were
    fictional documents nobody should have been citing."""
    upload_dir, _ = _temporary_document_storage(monkeypatch, tmp_path)
    (upload_dir / "customer-policy.pdf").write_bytes(b"test pdf")
    (upload_dir / "ignore.txt").write_text("not supported")

    documents = service.list_documents()

    assert [document["name"] for document in documents] == ["customer-policy.pdf"]
    assert documents[0]["origin"] == "uploaded"


def test_the_library_shows_which_product_a_file_belongs_to(stores):
    availo = products.add(None, TEAM, "Availo")
    service.save_upload("Availo policy.pdf", b"%PDF-1.4 availo", TEAM, product_id=availo.id)
    service.save_upload("Shared policy.pdf", b"%PDF-1.4 shared", TEAM)

    listed = {doc["name"]: (doc["product_id"], doc["product_name"]) for doc in service.list_documents(TEAM)}
    assert listed == {"Availo policy.pdf": (availo.id, "Availo"), "Shared policy.pdf": ("", "")}

    with TestClient(app) as client:
        documents = client.get("/api/documents").json()["documents"]
    assert {doc["name"]: (doc["product_id"], doc["product_name"]) for doc in documents} == listed


def test_a_product_file_opens_by_name_until_its_product_is_deleted(stores):
    availo = products.add(None, TEAM, "Availo")
    service.save_upload("Availo policy.pdf", b"%PDF-1.4 availo", TEAM, product_id=availo.id)

    with TestClient(app) as client:
        opened = client.get("/api/documents/uploaded/uploaded/Availo policy.pdf/file")
        assert (opened.status_code, opened.content) == (200, b"%PDF-1.4 availo")

        assert client.delete(f"/api/products/{availo.id}?confirm=confirm").status_code == 200

        gone = client.get("/api/documents/uploaded/uploaded/Availo policy.pdf/file")
        assert (gone.status_code, gone.json()["code"]) == (404, "document_not_found")
        assert client.get("/api/documents").json()["documents"] == []


def test_document_resolution_rejects_traversal(monkeypatch, tmp_path):
    upload_dir, _ = _temporary_document_storage(monkeypatch, tmp_path)
    (upload_dir / "safe.pdf").write_bytes(b"safe")

    assert service.resolve_document("uploaded", "uploaded", "safe.pdf") == upload_dir / "safe.pdf"

    for name in ("../safe.pdf", "/etc/passwd", "safe.txt"):
        try:
            service.resolve_document("uploaded", "uploaded", name)
        except ValueError:
            pass
        else:  # pragma: no cover - makes a traversal regression explicit
            raise AssertionError(f"Unsafe document name was accepted: {name}")


async def test_extracted_text_is_cached(monkeypatch, tmp_path):
    upload_dir, extracted_dir = _temporary_document_storage(monkeypatch, tmp_path)
    source = upload_dir / "sample.docx"
    source.write_bytes(b"placeholder")
    calls = []

    async def fake_load_text(path):
        calls.append(path)
        return "Question | Extracted answer"

    monkeypatch.setattr(service, "load_text", fake_load_text)

    assert await service.extracted_document_text(source) == "Question | Extracted answer"
    assert await service.extracted_document_text(source) == "Question | Extracted answer"
    assert calls == [source]
    assert len(list(extracted_dir.glob("*.txt"))) == 1


def test_docx_preview_preserves_formatting_and_escapes_content(tmp_path):
    from docx import Document

    path = tmp_path / "preview.docx"
    document = Document()
    document.add_heading("Preview heading", level=1)
    paragraph = document.add_paragraph()
    paragraph.add_run("Bold text").bold = True
    paragraph.add_run(" <script>alert('unsafe')</script>")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Question"
    table.cell(0, 1).text = "Answer"
    table.cell(1, 0).text = "هل البيانات مشفرة؟"
    table.cell(1, 1).text = "نعم"
    document.save(path)

    preview = service.docx_preview_html(path)

    assert "<h1>Preview heading</h1>" in preview
    assert "<strong>Bold text</strong>" in preview
    assert "<table>" in preview
    assert 'dir="rtl"' in preview
    assert "&lt;script&gt;alert(&#x27;unsafe&#x27;)&lt;/script&gt;" in preview
    assert "<script>" not in preview


def test_document_api_serves_original_and_extracted_text(monkeypatch, tmp_path):
    upload_dir, _ = _temporary_document_storage(monkeypatch, tmp_path)
    source = upload_dir / "sample.pdf"
    source.write_bytes(b"synthetic pdf bytes")

    async def fake_extracted_text(path):
        assert path == source
        return "Extracted sample text"

    monkeypatch.setattr(service, "extracted_document_text", fake_extracted_text)

    with TestClient(app) as client:
        catalog = client.get("/api/documents")
        original = client.get("/api/documents/uploaded/uploaded/sample.pdf/file")
        extracted = client.get("/api/documents/uploaded/uploaded/sample.pdf/text")

    assert catalog.status_code == 200
    assert catalog.json()["uploaded_count"] == 1
    assert original.status_code == 200
    assert original.content == b"synthetic pdf bytes"
    assert original.headers["content-disposition"].startswith("inline")
    assert extracted.status_code == 200
    assert extracted.json() == {
        "name": "sample.pdf",
        "text": "Extracted sample text",
        "characters": 21,
    }


def test_document_api_rejects_unknown_locations(monkeypatch, tmp_path):
    _temporary_document_storage(monkeypatch, tmp_path)

    with TestClient(app) as client:
        bad_location = client.get("/api/documents/private/secrets/missing.pdf/file")
        missing = client.get("/api/documents/uploaded/uploaded/missing.pdf/file")

    assert bad_location.status_code == 400
    assert missing.status_code == 404


def test_an_uploaded_word_document_is_previewed_and_extracted(monkeypatch, tmp_path):
    """The preview is rendered HTML in a locked-down frame, and the extracted
    text is what the answering pipeline actually read -- the two together are
    how somebody checks a citation against the document it names."""
    from docx import Document

    upload_dir, _ = _temporary_document_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "docling_base_url", "")
    document = Document()
    document.add_heading("Vendor Security Assessment 2026", level=1)
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Question"
    table.cell(0, 1).text = "Answer"
    table.cell(1, 0).text = "Is there an approved information security policy?"
    document.save(upload_dir / "assessment.docx")

    with TestClient(app) as client:
        preview = client.get("/api/documents/uploaded/uploaded/assessment.docx/preview")
        response = client.get("/api/documents/uploaded/uploaded/assessment.docx/text")

    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("text/html")
    assert preview.headers["content-security-policy"].startswith("default-src 'none'")
    assert "Vendor Security Assessment 2026" in preview.text
    assert "<table>" in preview.text
    assert response.status_code == 200
    text = response.json()["text"]
    assert "Vendor Security Assessment 2026" in text
    assert "approved information security policy" in text
