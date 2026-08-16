"""Document catalog, preview, and extracted-text cache tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from src import service
from src.api import app
from src.config import settings


def _temporary_document_storage(monkeypatch, tmp_path):
    upload_dir = tmp_path / "uploads"
    extracted_dir = tmp_path / "extracted"
    monkeypatch.setattr(settings, "upload_dir", upload_dir)
    monkeypatch.setattr(settings, "extracted_text_dir", extracted_dir)
    upload_dir.mkdir()
    extracted_dir.mkdir()
    return upload_dir, extracted_dir


def test_document_catalog_lists_uploads_and_bundled_trials(monkeypatch, tmp_path):
    upload_dir, _ = _temporary_document_storage(monkeypatch, tmp_path)
    (upload_dir / "customer-policy.pdf").write_bytes(b"test pdf")
    (upload_dir / "ignore.txt").write_text("not supported")

    documents = service.list_documents()

    assert any(
        document["name"] == "customer-policy.pdf" and document["origin"] == "uploaded"
        for document in documents
    )
    assert any(
        document["name"] == "vendor_security_assessment_2026.docx"
        and document["category"] == "new_assessment"
        for document in documents
    )
    assert all(document["name"] != "ignore.txt" for document in documents)


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
    assert catalog.json()["trial_count"] >= 3
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


def test_trial_word_document_is_extracted_through_the_api(monkeypatch, tmp_path):
    _temporary_document_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "docling_base_url", "")

    with TestClient(app) as client:
        preview = client.get(
            "/api/documents/trial/new_assessment/vendor_security_assessment_2026.docx/preview"
        )
        response = client.get(
            "/api/documents/trial/new_assessment/vendor_security_assessment_2026.docx/text"
        )

    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("text/html")
    assert preview.headers["content-security-policy"].startswith("default-src 'none'")
    assert "Vendor Security Assessment 2026" in preview.text
    assert "<table>" in preview.text
    assert response.status_code == 200
    payload = response.json()
    assert payload["characters"] > 1_000
    assert "Vendor Security Assessment 2026" in payload["text"]
    assert "[table]" in payload["text"]
