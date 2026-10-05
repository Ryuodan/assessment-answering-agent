"""Turning the fixture documents into the chunks the knowledge base indexes.

Each document in tests/fixtures is read by the local loaders (pdfplumber and
python-docx, the path used whenever Docling is unreachable) and chunked at the
default chunk size. Pinned: a fingerprint of the extracted text (its length,
its SHA-256 and its opening), and every chunk with its metadata. Docling's
conversion is a network service and is not characterized here.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.chunking import chunk_document
from src.documents import load_text_local

FIXTURES = Path(__file__).parent.parent / "fixtures"
DOCUMENTS = sorted(path.name for path in FIXTURES.iterdir() if path.suffix in (".pdf", ".docx"))


@pytest.mark.parametrize("name", DOCUMENTS)
def test_loading_and_chunking(name, default_settings, snapshot):
    text = load_text_local(FIXTURES / name)
    chunks = chunk_document(text, source_name=name, chunk_size=default_settings.chunk_size)
    snapshot(
        f"documents/{name}",
        {
            "extracted": {
                "characters": len(text),
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "opening": text[:300],
            },
            "chunk_size": default_settings.chunk_size,
            "chunks": [{"text": chunk.text, "metadata": chunk.metadata} for chunk in chunks],
        },
    )
