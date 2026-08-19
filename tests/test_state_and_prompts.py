"""Steps 3 and 4 — evidence accumulation across retries, and clause citations.

The Step 3 bug was silent: `QuestionState.evidence` had no reducer, so a second
retrieval round replaced the first. These tests pin the union semantics.
"""

from __future__ import annotations

import pytest

from src.graph.state import merge_evidence, order_evidence
from src.models import Evidence, SourceType
from src.prompts import format_sources_block


def guideline(chunk: int, score: float = 0.7, **overrides) -> Evidence:
    base = dict(
        source_type=SourceType.GUIDELINE,
        source_name="std.pdf",
        snippet=f"chunk {chunk}",
        chunk=chunk,
        score=score,
    )
    base.update(overrides)
    return Evidence(**base)


def prior(chunk: int, score: float = 0.5, **overrides) -> Evidence:
    base = dict(
        source_type=SourceType.PRIOR_ANSWER,
        source_name="bank.pdf",
        snippet=f"prior {chunk}",
        chunk=chunk,
        score=score,
    )
    base.update(overrides)
    return Evidence(**base)


# --- Step 3: accumulation --------------------------------------------------


def test_second_round_adds_rather_than_replaces():
    """The original bug: attempt 2 discarded everything attempt 1 found."""
    first = [guideline(1), guideline(2)]
    second = [guideline(3), guideline(4)]
    merged = merge_evidence(first, second)
    assert {item.chunk for item in merged} == {1, 2, 3, 4}


def test_identical_rounds_do_not_duplicate():
    first = [guideline(1), guideline(2)]
    assert len(merge_evidence(first, list(first))) == 2


def test_duplicate_keeps_the_higher_score():
    merged = merge_evidence([guideline(1, score=0.4)], [guideline(1, score=0.9)])
    assert len(merged) == 1 and merged[0].score == 0.9


def test_duplicate_does_not_downgrade_an_existing_score():
    merged = merge_evidence([guideline(1, score=0.9)], [guideline(1, score=0.4)])
    assert merged[0].score == 0.9


def test_same_chunk_index_in_different_documents_is_not_a_duplicate():
    """De-duplication keys on (source_name, chunk), not chunk alone."""
    merged = merge_evidence(
        [guideline(1, source_name="a.pdf")], [guideline(1, source_name="b.pdf")]
    )
    assert len(merged) == 2


@pytest.mark.parametrize(("left", "right"), [(None, None), ([], None), (None, [])])
def test_merge_handles_empty_rounds(left, right):
    assert merge_evidence(left, right) == []


def test_merge_is_idempotent():
    once = merge_evidence([guideline(1), guideline(2)], [guideline(3)])
    twice = merge_evidence(once, [])
    assert [item.chunk for item in once] == [item.chunk for item in twice]


def test_three_rounds_accumulate():
    merged = merge_evidence(merge_evidence([guideline(1)], [guideline(2)]), [guideline(3)])
    assert {item.chunk for item in merged} == {1, 2, 3}


# --- Step 3: ordering ------------------------------------------------------


def test_prior_answers_lead():
    ordered = order_evidence([guideline(1, score=0.9), prior(9, score=0.2)])
    assert ordered[0].source_type is SourceType.PRIOR_ANSWER


def test_units_rank_by_their_best_member_and_stay_contiguous():
    """A split series must not be scattered through the prompt by per-part score."""
    weak_unit = [
        guideline(10, score=0.30, unit_id="u1", part=1, parts=2),
        guideline(11, score=0.95, unit_id="u1", part=2, parts=2),
    ]
    other = guideline(20, score=0.60)
    ordered = order_evidence([*weak_unit, other])
    assert [item.chunk for item in ordered] == [10, 11, 20]


def test_parts_of_a_unit_are_in_part_order():
    scrambled = [
        guideline(3, score=0.7, unit_id="u1", part=3, parts=3),
        guideline(1, score=0.7, unit_id="u1", part=1, parts=3),
        guideline(2, score=0.7, unit_id="u1", part=2, parts=3),
    ]
    assert [item.part for item in order_evidence(scrambled)] == [1, 2, 3]


def test_higher_scoring_document_leads_among_guidelines():
    ordered = order_evidence([guideline(1, score=0.4), guideline(2, score=0.8)])
    assert ordered[0].chunk == 2


# --- Step 4: citations -----------------------------------------------------


def test_sources_block_shows_clause_locators():
    block = format_sources_block(
        [guideline(1, doc_id="MDS-CS-STD-003", clause_start="7.2.1", heading="7 Monitoring")]
    )
    assert "MDS-CS-STD-003 \u00a77.2.1" in block
    assert "(7 Monitoring)" in block
    assert block.startswith("[1] GUIDELINE")


def test_sources_block_numbers_from_one_and_matches_citation_indexes():
    """The drafter returns `used_source_ids`; those are 1-based into this block."""
    block = format_sources_block([guideline(1), guideline(2), guideline(3)])
    assert "[1] " in block and "[2] " in block and "[3] " in block
    assert "[0] " not in block


def test_sources_block_flags_fragments():
    block = format_sources_block([guideline(1, unit_id="u1", part=2, parts=4)])
    assert "[part 2 of 4]" in block


def test_sources_block_does_not_flag_whole_units():
    assert "part 1 of 1" not in format_sources_block([guideline(1)])


def test_sources_block_labels_prior_answers_distinctly():
    block = format_sources_block([prior(1, questionnaire="SAMA CSF", answered_date="1446H")])
    assert "PREVIOUS ANSWER \u2014 SAMA CSF (1446H)" in block


def test_sources_block_handles_no_sources():
    assert "no relevant sources" in format_sources_block([])


def test_sources_block_includes_the_snippet_text():
    block = format_sources_block([guideline(1, snippet="RSA modulus floor is 3072 bits")])
    assert "3072 bits" in block


def test_citation_list_is_deduplicated_and_ordered():
    """Mirrors `finalize`: dict.fromkeys preserves order and drops repeats."""
    cited = [
        guideline(1, doc_id="MDS-CS-STD-003", clause_start="7.2.1"),
        guideline(2, doc_id="MDS-CS-STD-003", clause_start="7.2.1"),
        guideline(3, doc_id="MDS-CS-STD-003", clause_start="7.4"),
    ]
    citations = list(dict.fromkeys(item.locator for item in cited))
    assert citations == ["MDS-CS-STD-003 \u00a77.2.1", "MDS-CS-STD-003 \u00a77.4"]