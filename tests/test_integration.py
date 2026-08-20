"""Integration — the whole Step 1-4 chain, without an LLM or an API key.

Runs: chunk a document -> index it -> retrieve a single fragment -> expand to the
whole unit -> merge across two retrieval rounds -> format the sources block.

This is the test that would have caught the original bug, because the original
bug only appeared when the pieces ran together: chunking split a series,
retrieval returned one part, the retry replaced rather than accumulated, and the
prompt showed a fragment with no indication it was one.
"""

from __future__ import annotations

from src.graph.state import merge_evidence
from src.models import SourceType
from src.prompts import format_sources_block
from tests.conftest import build_store

SERIES_ITEMS = [f"7.2.{n}" for n in range(1, 13)]


async def test_fragment_hit_becomes_a_complete_series_in_the_prompt(series_doc):
    """A retrieval hit on one part must reach the drafter as the whole series."""
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=400)

    split = [r for r in fake.records if r["metadata"]["parts"] > 1]
    assert split, "fixture must split the series at chunk_size=400"
    last = max(split, key=lambda r: r["metadata"]["part"])
    fake.stage(chunk_indexes=[last["metadata"]["chunk"]], score=0.58)

    evidence = await store.search("certificate expiry", SourceType.GUIDELINE, k=1)
    merged = merge_evidence([], evidence)
    block = format_sources_block(merged)

    missing = [item for item in SERIES_ITEMS if item not in block]
    assert not missing, f"the drafter would not see {missing}"
    assert "[part 1 of" in block, "fragments must be labelled so confidence can react"


async def test_two_retrieval_rounds_union_into_one_prompt(series_doc):
    """The Step 3 bug reproduced: without the reducer, round 1 is lost."""
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=400)
    first = next(r for r in fake.records if "7.2.1" in r["text"])
    second = next(r for r in fake.records if "| Critical |" in r["text"])

    fake.stage(chunk_indexes=[first["metadata"]["chunk"]], score=0.72)
    round_one = await store.search("soc alert conditions", SourceType.GUIDELINE, k=1, expand=False)

    fake.stage(chunk_indexes=[second["metadata"]["chunk"]], score=0.66)
    round_two = await store.search("remediation windows", SourceType.GUIDELINE, k=1, expand=False)

    replaced = round_two                      # old behaviour
    accumulated = merge_evidence(round_one, round_two)  # new behaviour

    assert len(replaced) == 1
    assert len(accumulated) == 2

    block = format_sources_block(accumulated)
    assert "7.2.1" in block and "Critical" in block


async def test_every_source_in_the_prompt_carries_a_clause_or_page(series_doc):
    """Step 4's acceptance condition: no bare filenames in the sources block."""
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=1800)
    fake.stage(chunk_indexes=[r["metadata"]["chunk"] for r in fake.records], score=0.7)

    evidence = await store.search("alerts", SourceType.GUIDELINE, k=len(fake.records))
    locators = [item.locator for item in evidence if item.kind in ("series", "table")]
    assert locators, "expected structural units in the corpus"
    # The file name leads, with the document code beside it; both must be there
    # for a reader to find the source and for an assessor to quote it.
    assert all(locator.startswith("std.pdf") for locator in locators)
    assert all("[MDS-CS-STD-003]" in locator for locator in locators)


async def test_arabic_document_survives_the_full_chain(arabic_doc):
    store, fake = build_store(arabic_doc, source_name="std-ar.pdf", chunk_size=1800)
    series = next(r for r in fake.records if r["metadata"]["kind"] == "series")
    fake.stage(chunk_indexes=[series["metadata"]["chunk"]], score=0.7)

    evidence = await store.search("\u0634\u0631\u0648\u0637 \u0627\u0644\u062a\u0646\u0628\u064a\u0647", SourceType.GUIDELINE, k=1)
    block = format_sources_block(merge_evidence([], evidence))

    assert "[MDS-CS-STD-003] \u00a77" in block, "Arabic clause not folded into the locator"
    assert "\u200f" not in block, "bidi control reached the prompt"
    for digit in "\u0661\u0662\u0663\u0664\u0665":
        assert f"\u0667.\u0662.{digit}" in block


async def test_prior_answers_lead_the_prompt_over_guidelines(series_doc):
    from src.models import Evidence

    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=1800)
    fake.stage(chunk_indexes=[fake.records[0]["metadata"]["chunk"]], score=0.9)
    guidelines = await store.search("alerts", SourceType.GUIDELINE, k=1)

    priors = [
        Evidence(
            source_type=SourceType.PRIOR_ANSWER,
            source_name="bank.pdf",
            snippet="We alert on failed logins.",
            chunk=0,
            score=0.4,
        )
    ]
    block = format_sources_block(merge_evidence(priors, guidelines))
    assert block.startswith("[1] PREVIOUS ANSWER")


async def test_chain_is_stable_when_retrieval_returns_nothing(series_doc):
    store, fake = build_store(series_doc, source_name="std.pdf", chunk_size=1800)
    fake.stage(chunk_indexes=[])

    evidence = await store.search("unrelated topic", SourceType.GUIDELINE, k=5)
    block = format_sources_block(merge_evidence([], evidence))
    assert evidence == []
    assert "no relevant sources" in block