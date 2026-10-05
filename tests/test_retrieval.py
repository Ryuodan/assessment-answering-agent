"""Step 2 — Evidence locators and parent-unit expansion at retrieval.

Expansion is the safety net for the case Step 1 cannot prevent: a series so long
it must split. The contract is that a hit on *any one part* returns the whole
unit, in document order, without duplicates, and without blowing the budget.
"""

from __future__ import annotations

import pytest

from src.config import settings
from src.knowledge import cosine_from_relevance
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


def test_locator_leads_with_the_file_name_and_clause():
    """A reader has to find the file; a document code alone is not findable."""
    single = make(doc_id="MDS-CS-STD-003", clause_start="7.2.1")
    assert single.locator == "MDS-CS-STD-003-secure-configuration.pdf \u00a77.2.1"


def test_locator_appends_a_document_code_the_file_name_does_not_carry():
    spanning = make(doc_id="MDS-CS-STD-006", clause_start="5.1", clause_end="5.6")
    assert spanning.locator == "MDS-CS-STD-003-secure-configuration.pdf [MDS-CS-STD-006] \u00a75.1\u20135.6"


def test_locator_does_not_repeat_a_code_already_in_the_file_name():
    assert "[" not in make(doc_id="MDS-CS-STD-003", clause_start="1").locator


def test_locator_names_an_arabic_file_rather_than_its_internal_code():
    """The reported bug: "PRO-PMP-2024 \u00a74.1\u20134.5" named no findable file."""
    evidence = make(
        source_name="T2 - \u0633\u064a\u0627\u0633\u0629 \u0625\u062f\u0627\u0631\u0629 \u0643\u0644\u0645\u0627\u062a \u0627\u0644\u0645\u0631\u0648\u0631.pdf",
        doc_id="PRO-PMP-2024",
        clause_start="5",
        clause_end="5.2",
    )
    assert evidence.locator.startswith("T2 - \u0633\u064a\u0627\u0633\u0629")
    assert "[PRO-PMP-2024]" in evidence.locator


@pytest.mark.parametrize(
    ("clause", "expected"),
    [("5.1", True), ("5.5", True), ("5.6", True), ("4.9", False), ("6.1", False), ("", False)],
)
def test_covers_clause(clause, expected):
    """Guards against attaching a precise clause to evidence that lacks it."""
    spanning = make(clause_start="5.1", clause_end="5.6")
    assert spanning.covers_clause(clause) is expected


def test_locator_shows_the_page_beside_the_clause():
    """A clause number says what to look for; the page says where to open the
    file. On a 161-page standard a reader needs both."""
    assert make(clause_start="7.2.1", page=14, page_end=14).locator == (
        "MDS-CS-STD-003-secure-configuration.pdf §7.2.1 (Page: 14)"
    )


def test_a_chunk_spanning_a_break_cites_both_pages():
    """Tables and clauses run over page boundaries; citing only where the text
    starts sends a reader to the wrong half of it."""
    assert make(clause_start="7.2.1", page=14, page_end=15).locator == (
        "MDS-CS-STD-003-secure-configuration.pdf §7.2.1 (Pages: 14–15)"
    )


def test_locator_falls_back_to_page_then_filename():
    assert make(doc_id="MDS-CS-STD-003", page=14, page_end=14).locator == (
        "MDS-CS-STD-003-secure-configuration.pdf (Page: 14)"
    )
    assert make().locator == "MDS-CS-STD-003-secure-configuration.pdf"


def test_a_document_indexed_before_pages_existed_claims_none():
    """Inventing a page would make an uncheckable citation look checkable."""
    assert "(Page" not in make(clause_start="7.2.1").locator


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


async def test_hit_on_one_part_returns_the_whole_unit(series_doc, expansion_uncapped):
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


async def test_expansion_query_scopes_to_source_and_unit(series_doc, expansion_uncapped):
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
    """Siblings must rank with the hit, not sink below unrelated documents.

    Pinned to the converted value rather than the staged one: a sibling that
    was run through the cosine conversion a second time would still equal its
    siblings and still pass an equality-only check, while ranking lower than
    the hit that pulled it in.
    """
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=400)
    split = next(r for r in fake.records if r["metadata"]["parts"] > 1)
    fake.stage(chunk_indexes=[split["metadata"]["chunk"]], score=0.61)

    evidence = await store.search("alerts", SourceType.GUIDELINE, k=1)

    expected = round(cosine_from_relevance(0.61, "l2"), 4)
    assert {e.score for e in evidence} == {expected}
    assert {e.raw_score for e in evidence} == {0.61}


async def test_metadata_survives_the_round_trip(series_doc):
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=1800)
    series = next(r for r in fake.records if r["metadata"]["kind"] == "series")
    fake.stage(chunk_indexes=[series["metadata"]["chunk"]])

    evidence = (await store.search("alerts", SourceType.GUIDELINE, k=1))[0]
    assert evidence.doc_id == "MDS-CS-STD-003"
    assert evidence.clause_start == "7"
    assert evidence.clause_end == "8"
    assert evidence.kind == "series"
    assert evidence.locator == "std.pdf [MDS-CS-STD-003] \u00a77\u20138"


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

    def _select_relevance_score_fn(self):
        return lambda score: score

    def similarity_search_by_vector_with_relevance_scores(self, embedding, k, filter=None, **kwargs):
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


# --- the score the reader is shown -----------------------------------------
#
# Chroma's l2 space returns a SQUARED distance; LangChain's converter assumes
# an unsquared one and divides by sqrt(2). The result is an affine squash of
# the cosine, so a chunk matching at 0.72 was displayed as 0.60.


@pytest.mark.parametrize(
    ("relevance", "cosine"),
    [
        (1.0, 1.0),  # identical vectors
        (0.6006, 0.7176),  # measured against the real corpus
        (0.4993, 0.6460),
        (1 - 2**0.5 / 2, 0.5),
    ],
)
def test_the_cosine_is_recovered_from_the_l2_relevance(relevance, cosine):
    assert cosine_from_relevance(relevance, "l2") == pytest.approx(cosine, abs=1e-4)


@pytest.mark.parametrize("space", ["cosine", "ip"])
def test_a_similarity_metric_is_passed_through_untouched(space):
    """Converting an already-correct similarity would be a second bug."""
    assert cosine_from_relevance(0.6006, space) == 0.6006


def test_the_conversion_is_strictly_increasing():
    """Ranking must be identical either way, which is why this was invisible."""
    values = [cosine_from_relevance(r / 100, "l2") for r in range(0, 101)]
    assert values == sorted(values)
    assert len(set(values)) == len(values)


def test_the_negative_region_is_gone():
    """The old figure went negative below cosine 0.293 and collided with the
    0.0 seed in order_evidence; a real cosine on this corpus does not."""
    assert cosine_from_relevance(0.034, "l2") > 0.0


async def test_a_search_reports_cosine_and_keeps_the_raw_figure(series_doc):
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=1800)
    fake.stage(chunk_indexes=[0], score=0.5)

    evidence = await store.search("alerts", SourceType.GUIDELINE, k=1, expand=False)

    assert evidence[0].raw_score == 0.5
    assert evidence[0].score == round(cosine_from_relevance(0.5, "l2"), 4)
    assert evidence[0].score > evidence[0].raw_score, "cosine should exceed the squashed figure"


async def test_an_unreadable_collection_config_falls_back_to_l2(series_doc, monkeypatch):
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=1800)
    monkeypatch.setattr(type(store), "_space", None)
    fake.stage(chunk_indexes=[0], score=0.5)

    evidence = await store.search("alerts", SourceType.GUIDELINE, k=1, expand=False)

    assert evidence[0].score == round(cosine_from_relevance(0.5, "l2"), 4)


# --- expansion has to know a series from a chapter -------------------------
#
# 61% of this corpus sits inside 66 units of more than six parts, the largest
# 113 parts long — a whole standard with no internal headings to divide on.
# Expanding one of those returned fourteen chunks from a single document and
# left no room for any other policy.


async def test_a_chapter_sized_unit_is_not_expanded(series_doc, monkeypatch):
    monkeypatch.setattr(settings, "max_expanded_parts", 3)
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=400)
    split = next(r for r in fake.records if r["metadata"]["parts"] > 3)
    fake.stage(chunk_indexes=[split["metadata"]["chunk"]])

    evidence = await store.search("alerts", SourceType.GUIDELINE, k=1)

    assert len(evidence) == 1, "a chapter-sized unit was expanded anyway"
    assert fake.get_calls == [], "it should not even query for the siblings"


async def test_a_series_sized_unit_is_still_expanded(series_doc, monkeypatch):
    """The behaviour the cap must not break."""
    monkeypatch.setattr(settings, "max_expanded_parts", 99)
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=400)
    split = next(r for r in fake.records if r["metadata"]["parts"] > 1)
    fake.stage(chunk_indexes=[split["metadata"]["chunk"]])

    evidence = await store.search("alerts", SourceType.GUIDELINE, k=1)

    assert len(evidence) == split["metadata"]["parts"]


async def test_the_character_budget_is_shared_across_the_whole_search(series_doc, monkeypatch):
    """Two hits in one unit used to authorise two full budgets between them."""
    monkeypatch.setattr(settings, "max_expanded_parts", 99)
    monkeypatch.setattr(settings, "max_expanded_chars", 900)
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=400)
    split = sorted(
        [r for r in fake.records if r["metadata"]["parts"] > 1],
        key=lambda r: r["metadata"]["part"],
    )
    fake.stage(chunk_indexes=[r["metadata"]["chunk"] for r in split[:2]])

    evidence = await store.search("alerts", SourceType.GUIDELINE, k=2)
    added = len(evidence) - 2

    total = sum(len(e.snippet) for e in evidence[2:])
    assert total <= 900, f"expansion returned {total} chars against a 900 budget"
    assert added >= 1, "the budget should still admit something"


# --- one embedding per query, not one per source type ----------------------


@pytest.mark.asyncio
async def test_both_source_types_share_a_single_embedding(series_doc):
    """Guidelines and prior answers are one collection behind a metadata
    filter, so asking for each separately embedded identical text twice --
    two round trips to the slowest dependency for the same 1024 numbers."""
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=400)
    fake.stage(chunk_indexes=[0], score=0.7)

    await store.search_types(
        "how quickly are alerts raised",
        [(SourceType.PRIOR_ANSWER, 5), (SourceType.GUIDELINE, 8)],
    )

    assert store.embedded == ["how quickly are alerts raised"], store.embedded
    assert len(fake.searched_vectors) == 2, "one vector query per source type"
    assert fake.searched_vectors[0] == fake.searched_vectors[1], "the same vector both times"


@pytest.mark.asyncio
async def test_each_source_type_keeps_its_own_budget(series_doc):
    """One query for both kinds would return the best k overall, which on a
    corpus that is almost all guidelines means prior answers never appear."""
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=400)
    fake.stage(chunk_indexes=[0, 1, 2], score=0.7)

    found = await store.search_types("alerts", [(SourceType.PRIOR_ANSWER, 1), (SourceType.GUIDELINE, 3)], expand=False)

    assert len(found[SourceType.PRIOR_ANSWER]) == 1
    assert len(found[SourceType.GUIDELINE]) == 3


@pytest.mark.asyncio
async def test_a_zero_budget_type_is_not_searched(series_doc):
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=400)
    fake.stage(chunk_indexes=[0], score=0.7)

    found = await store.search_types("alerts", [(SourceType.PRIOR_ANSWER, 0), (SourceType.GUIDELINE, 5)])

    assert SourceType.PRIOR_ANSWER not in found
    assert len(fake.searched_vectors) == 1


@pytest.mark.asyncio
async def test_an_empty_query_costs_no_embedding(series_doc):
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=400)

    assert await store.search_types("   ", [(SourceType.GUIDELINE, 5)]) == {}
    assert store.embedded == []


@pytest.mark.asyncio
async def test_search_still_returns_what_it_did_before(series_doc):
    """`search` is now a one-type call through `search_types`; the contract it
    had -- k chunks of one type, best first, units expanded -- is unchanged."""
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=400)
    fake.stage(chunk_indexes=[0, 1], score=0.7)

    found = await store.search("alerts", SourceType.GUIDELINE, 2, expand=False)

    assert len(found) == 2
    assert all(item.source_type is SourceType.GUIDELINE for item in found)
    assert store.embedded == ["alerts"], "one embedding, not one per call layer"


@pytest.mark.asyncio
async def test_the_relevance_conversion_is_applied_not_the_raw_distance(series_doc):
    """The by-vector call returns distances -- lower is nearer -- while the
    by-string call returns relevance. Dropping the conversion would invert the
    ranking and silently break the cosine figure shown to a reader."""
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=400)
    fake.stage(chunk_indexes=[0], score=0.42)

    found = await store.search("alerts", SourceType.GUIDELINE, 1, expand=False)

    # The fake's conversion is the identity, so what `_evidence` received must
    # be exactly what the store reported rather than anything re-derived.
    assert found[0].raw_score == pytest.approx(0.42)
