"""Page numbers, from Docling's placeholder to a citation a reader can open.

Docling emits Markdown with no page information, so a citation could name a
clause but never a page. It will insert a fixed placeholder between pages if
asked, and the local pdfplumber loader already emits `--- page N ---` markers
the chunker reads. Rewriting one into the other means page numbers reach chunk
metadata without the chunker learning a second convention.
"""

from __future__ import annotations

import pytest

from src.chunking import chunk_document
from src.config import settings
from src.docling_client import number_pages
from src.models import Evidence, SourceType

MARK = "<!-- docling-page-break -->"


@pytest.fixture(autouse=True)
def placeholder(monkeypatch):
    monkeypatch.setattr(settings, "docling_page_break_placeholder", MARK)


# --- rewriting -------------------------------------------------------------


def test_placeholders_become_numbered_markers():
    out = number_pages(f"first{MARK}second{MARK}third")
    assert out == "--- page 1 ---\nfirst\n--- page 2 ---\nsecond\n--- page 3 ---\nthird"


def test_the_markers_are_the_ones_the_chunker_already_reads():
    from src.chunking import _PAGE

    lines = number_pages(f"a{MARK}b").splitlines()
    assert [line for line in lines if _PAGE.match(line.strip())] == ["--- page 1 ---", "--- page 2 ---"]


def test_text_without_placeholders_is_left_alone():
    """A document extracted before this existed must not be given a page 1 it
    cannot support: an invented page makes a citation look checkable."""
    assert number_pages("plain markdown") == "plain markdown"


def test_no_page_is_claimed_when_the_feature_is_off(monkeypatch):
    monkeypatch.setattr(settings, "docling_page_break_placeholder", "")
    assert number_pages(f"a{MARK}b") == f"a{MARK}b"


def test_a_single_page_document_still_gets_page_one():
    assert number_pages(f"only page{MARK}").startswith("--- page 1 ---")


# --- reaching chunk metadata ----------------------------------------------


def test_a_chunk_records_the_page_it_came_from():
    """Sections long enough not to be coalesced. The chunker merges small
    neighbours by design, so two one-line pages become a single chunk spanning
    both — correct behaviour, and not what this is testing."""
    first = "## 1 Scope\n\n" + "Scope detail for the reader. " * 90
    second = "## 2 Controls\n\n" + "Control detail for the reader. " * 90
    chunks = chunk_document(number_pages(first + MARK + second), source_name="p.pdf", chunk_size=1800)

    assert {c.metadata["page"] for c in chunks} == {1, 2}
    assert all(c.metadata["page"] <= c.metadata["page_end"] for c in chunks)


def test_a_chunk_spanning_a_break_records_both_ends():
    """Tables and clauses run over page boundaries. `page` alone would send a
    reader to where the text starts rather than where it is."""
    document = number_pages("## 1 Scope\n\n" + "Detail. " * 30 + MARK + "More of the same clause. " * 30)
    chunk = next(c for c in chunk_document(document, source_name="p.pdf", chunk_size=4000) if c.metadata["page"] >= 0)

    assert chunk.metadata["page"] == 1
    assert chunk.metadata["page_end"] == 2


def test_a_document_with_no_markers_reports_no_page():
    chunks = chunk_document("## 1 Scope\n\nText.", source_name="p.pdf", chunk_size=1800)
    assert all(c.metadata["page"] == -1 for c in chunks)


# --- reaching the citation -------------------------------------------------


def evidence(**overrides) -> Evidence:
    base = dict(source_type=SourceType.GUIDELINE, source_name="Policy.pdf", snippet="x")
    return Evidence(**{**base, **overrides})


def test_the_citation_carries_clause_and_page_together():
    assert evidence(clause_start="3.1.1", page=3, page_end=3).locator == "Policy.pdf §3.1.1 (Page: 3)"


def test_the_citation_shows_a_range_when_the_chunk_spans_pages():
    assert evidence(clause_start="3.1.1", page=3, page_end=5).locator == ("Policy.pdf §3.1.1 (Pages: 3–5)")


def test_a_page_alone_is_still_better_than_a_bare_filename():
    assert evidence(page=9, page_end=9).locator == "Policy.pdf (Page: 9)"


def test_nothing_is_claimed_without_a_page():
    assert evidence(clause_start="3.1.1").locator == "Policy.pdf §3.1.1"
