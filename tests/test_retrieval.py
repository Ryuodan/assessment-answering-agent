"""Step 2 — Evidence locators and parent-unit expansion at retrieval.

Expansion is the safety net for the case Step 1 cannot prevent: a series so long
it must split. The contract is that a hit on *any one part* returns the whole
unit, in document order, without duplicates, and without blowing the budget.
"""

from __future__ import annotations

import pytest

from src.config import settings
from src.knowledge import KnowledgeStore
from src.models import Evidence, ExtractedQAPair, SourceType
from tests.conftest import bare_store, build_store


# --- locator ---------------------------------------------------------------


def make(**overrides) -> Evidence:
    base = dict(
        source_type=SourceType.GUIDELINE,
        source_name="MDS-CS-STD-003-secure-configuration.pdf",
        snippet="text",
    )
    base.update(overrides)
    return Evidence(**base)


def test_locator_prefers_doc_id_and_clause():
    single = make(doc_id="MDS-CS-STD-003", clause_start="7.2.1")
    assert single.locator == "MDS-CS-STD-003 \u00a77.2.1"


def test_locator_reports_a_span_when_the_chunk_covers_several_clauses():
    spanning = make(doc_id="MDS-CS-STD-006", clause_start="5.1", clause_end="5.6")
    assert spanning.locator == "MDS-CS-STD-006 \u00a75.1\u20135.6"


@pytest.mark.parametrize(
    ("clause", "expected"),
    [("5.1", True), ("5.5", True), ("5.6", True), ("4.9", False), ("6.1", False), ("", False)],
)
def test_covers_clause(clause, expected):
    """Guards against attaching a precise clause to evidence that lacks it."""
    spanning = make(clause_start="5.1", clause_end="5.6")
    assert spanning.covers_clause(clause) is expected


def test_locator_falls_back_to_page_then_filename():
    assert make(doc_id="MDS-CS-STD-003", page=14).locator == "MDS-CS-STD-003 p.14"
    assert make().locator == "MDS-CS-STD-003-secure-configuration.pdf"


def test_locator_uses_filename_when_doc_id_missing():
    assert make(source_name="policy.pdf", clause_start="4.1").locator == "policy.pdf \u00a74.1"


def test_prior_answer_locator_uses_questionnaire_and_date():
    evidence = make(
        source_type=SourceType.PRIOR_ANSWER,
        source_name="bank.pdf",
        questionnaire="SAMA CSF Assessment",
        answered_date="1446H",
    )
    assert evidence.locator == "SAMA CSF Assessment (1446H)"


def test_prior_answer_locator_degrades_to_filename():
    assert make(source_type=SourceType.PRIOR_ANSWER, source_name="bank.pdf").locator == "bank.pdf"


@pytest.mark.parametrize(("parts", "expected"), [(1, False), (2, True), (7, True)])
def test_is_fragment(parts, expected):
    assert make(parts=parts).is_fragment is expected


# --- expansion -------------------------------------------------------------


async def test_hit_on_one_part_returns_the_whole_unit(series_doc):
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=400)
    split = [r for r in fake.records if r["metadata"]["parts"] > 1]
    assert split, "fixture must produce a split unit"

    last = max(split, key=lambda r: r["metadata"]["part"])
    fake.stage(chunk_indexes=[last["metadata"]["chunk"]])

    evidence = await store.search("certificate expiry", SourceType.GUIDELINE, k=1)

    unit_id = last["metadata"]["unit_id"]
    returned = [e for e in evidence if e.unit_id == unit_id]
    assert len(returned) == last["metadata"]["parts"], "expansion did not recover every part"
    joined = "\n".join(e.snippet for e in returned)
    assert all(f"7.2.{n}" in joined for n in range(1, 13))


async def test_expansion_returns_parts_in_document_order(series_doc):
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=400)
    split = [r for r in fake.records if r["metadata"]["parts"] > 1]
    middle = sorted(split, key=lambda r: r["metadata"]["part"])[len(split) // 2]
    fake.stage(chunk_indexes=[middle["metadata"]["chunk"]])

    evidence = await store.search("privileged account", SourceType.GUIDELINE, k=1)
    unit = [e for e in evidence if e.unit_id == middle["metadata"]["unit_id"]]
    # The triggering hit leads; its siblings follow in part order.
    assert unit[0].part == middle["metadata"]["part"]
    assert [e.part for e in unit[1:]] == sorted(e.part for e in unit[1:])


async def test_expansion_does_not_duplicate_an_already_retrieved_part(series_doc):
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=400)
    split = sorted(
        [r for r in fake.records if r["metadata"]["parts"] > 1],
        key=lambda r: r["metadata"]["part"],
    )
    fake.stage(chunk_indexes=[r["metadata"]["chunk"] for r in split[:2]])

    evidence = await store.search("alerts", SourceType.GUIDELINE, k=2)
    keys = [(e.source_name, e.chunk) for e in evidence]
    assert len(keys) == len(set(keys)), "expansion produced duplicates"


async def test_whole_unit_hit_triggers_no_expansion_query(series_doc):
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=1800)
    whole = next(r for r in fake.records if r["metadata"]["kind"] == "series")
    fake.stage(chunk_indexes=[whole["metadata"]["chunk"]])

    evidence = await store.search("alerts", SourceType.GUIDELINE, k=1)
    assert len(evidence) == 1
    assert fake.get_calls == [], "expanded a unit that was never split"


async def test_expansion_query_scopes_to_source_and_unit(series_doc):
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=400)
    split = next(r for r in fake.records if r["metadata"]["parts"] > 1)
    fake.stage(chunk_indexes=[split["metadata"]["chunk"]])

    await store.search("alerts", SourceType.GUIDELINE, k=1)
    assert fake.get_calls, "no expansion query issued"
    clauses = fake.get_calls[0]["$and"]
    keys = {key for clause in clauses for key in clause}
    assert keys == {"source_name", "unit_id"}, "expansion must scope to one unit of one document"


async def test_expansion_respects_the_char_budget(series_doc, monkeypatch):
    monkeypatch.setattr(settings, "max_expanded_chars", 10)
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=400)
    split = next(r for r in fake.records if r["metadata"]["parts"] > 1)
    fake.stage(chunk_indexes=[split["metadata"]["chunk"]])

    evidence = await store.search("alerts", SourceType.GUIDELINE, k=1)
    assert len(evidence) == 1, "budget of 10 chars should admit no siblings"


async def test_expand_false_skips_expansion(series_doc):
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=400)
    split = next(r for r in fake.records if r["metadata"]["parts"] > 1)
    fake.stage(chunk_indexes=[split["metadata"]["chunk"]])

    evidence = await store.search("alerts", SourceType.GUIDELINE, k=1, expand=False)
    assert len(evidence) == 1 and fake.get_calls == []


async def test_expanded_siblings_inherit_the_hit_score(series_doc):
    """Siblings must rank with the hit, not sink below unrelated documents."""
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=400)
    split = next(r for r in fake.records if r["metadata"]["parts"] > 1)
    fake.stage(chunk_indexes=[split["metadata"]["chunk"]], score=0.61)

    evidence = await store.search("alerts", SourceType.GUIDELINE, k=1)
    assert {e.score for e in evidence} == {0.61}


async def test_metadata_survives_the_round_trip(series_doc):
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=1800)
    series = next(r for r in fake.records if r["metadata"]["kind"] == "series")
    fake.stage(chunk_indexes=[series["metadata"]["chunk"]])

    evidence = (await store.search("alerts", SourceType.GUIDELINE, k=1))[0]
    assert evidence.doc_id == "MDS-CS-STD-003"
    assert evidence.clause_start == "7"
    assert evidence.clause_end == "8"
    assert evidence.kind == "series"
    assert evidence.locator == "MDS-CS-STD-003 \u00a77\u20138"


async def test_empty_query_short_circuits(series_doc):
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=1800)
    assert await store.search("   ", SourceType.GUIDELINE, k=5) == []
    assert await store.search("alerts", SourceType.GUIDELINE, k=0) == []

# --- previously answered assessments ---------------------------------------


class _RecordingStore:
    """Captures what `add_documents` was handed, and serves nothing back."""

    def __init__(self):
        self.documents = []
        self.deleted = []

    def add_documents(self, documents, ids=None):
        self.documents = documents

    def delete(self, where=None):
        self.deleted.append(where)

    def get(self, where=None, include=None):
        return {"documents": [], "metadatas": []}

    async def asimilarity_search_with_relevance_scores(self, query, k, filter=None):
        return []


def _store_with(recorder):
    return bare_store(recorder)


def test_prior_answers_embed_the_question_with_its_answer():
    """The question wording is what a new question matches on; the answer must travel with it."""
    recorder = _RecordingStore()
    store = _store_with(recorder)

    store.add_prior_answers(
        "vendor_review_2025.docx",
        [ExtractedQAPair(question="Do you encrypt data at rest?", answer="Yes, AES-256.", section="Cryptography")],
    )

    (document,) = recorder.documents
    assert "Do you encrypt data at rest?" in document.page_content
    assert "AES-256" in document.page_content
    assert document.metadata["source_type"] == SourceType.PRIOR_ANSWER.value
    assert document.metadata["question"] == "Do you encrypt data at rest?"
    assert document.metadata["section"] == "Cryptography"


async def test_an_empty_prior_answer_bank_is_not_an_error():
    """Most deployments start with policies only; retrieval must simply return nothing."""
    store = _store_with(_RecordingStore())
    assert await store.search("anything at all", SourceType.PRIOR_ANSWER, 5) == []


def test_duplicate_upload_is_reported_against_the_original():
    recorder = _RecordingStore()
    recorder.get = lambda where=None, include=None: {
        "metadatas": [{"source_name": "Acceptable Use Policy.pdf", "content_hash": "abc"}]
    }
    store = _store_with(recorder)

    assert store.source_with_hash("abc", excluding="Acceptable Use Policy(1).pdf") == "Acceptable Use Policy.pdf"
    # The file already indexed under this hash must not report itself as a duplicate.
    assert store.source_with_hash("abc", excluding="Acceptable Use Policy.pdf") is None
