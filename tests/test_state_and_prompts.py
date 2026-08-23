"""Steps 3 and 4 — evidence accumulation across retries, and clause citations.

The Step 3 bug was silent: `QuestionState.evidence` had no reducer, so a second
retrieval round replaced the first. These tests pin the union semantics.
"""

from __future__ import annotations

import pytest

from src.config import settings
from src.graph.state import agreement_bonus, merge_evidence, order_evidence, select_evidence
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
    assert "std.pdf [MDS-CS-STD-003] \u00a77.2.1" in block
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
    assert citations == ["std.pdf [MDS-CS-STD-003] \u00a77.2.1", "std.pdf [MDS-CS-STD-003] \u00a77.4"]

# --- what actually fits in the prompt --------------------------------------
#
# Ordering and selection used to be the same operation: prior answers sort
# first, and the prompt was filled from the top of that list. On the real
# corpus that meant twelve prior answers scoring 0.20-0.48 crowded out policy
# clauses scoring 0.60, and a retrieval retry pushed the guideline count to
# zero — the same question answering correctly or "not documented" depending
# on whether a retry happened.


def test_prior_answers_cannot_take_the_whole_prompt():
    """The reported bug, in miniature: 12 weak prior answers, one strong clause."""
    evidence = order_evidence(
        [prior(n, score=0.2 + n / 100) for n in range(12)]
        + [guideline(90 + n, score=0.9) for n in range(4)]
    )

    selected = select_evidence(evidence, limit=6, prior_cap=4)
    priors = [item for item in selected if item.source_type is SourceType.PRIOR_ANSWER]

    assert len(priors) == 4
    assert len(selected) - len(priors) == 2, "no guideline reached the prompt"


def test_the_prior_answers_kept_are_the_best_scoring_ones():
    """Which four survive matters as much as how many."""
    evidence = order_evidence(
        [prior(1, score=0.2), prior(2, score=0.9), prior(3, score=0.5)]
        + [guideline(n) for n in range(90, 99)]
    )

    selected = select_evidence(evidence, limit=10, prior_cap=1)
    priors = [item for item in selected if item.source_type is SourceType.PRIOR_ANSWER]

    assert [item.chunk for item in priors] == [2]


def test_the_budget_is_filled_when_there_are_few_guidelines():
    """A cap on prior answers must not shrink the prompt."""
    evidence = order_evidence([prior(n) for n in range(8)] + [guideline(99)])

    selected = select_evidence(evidence, limit=6, prior_cap=2)

    assert len(selected) == 6


def test_spare_room_goes_back_to_prior_answers_in_score_order():
    evidence = order_evidence(
        [prior(1, score=0.9), prior(2, score=0.8), prior(3, score=0.1)] + [guideline(99)]
    )

    selected = select_evidence(evidence, limit=3, prior_cap=1)
    chunks = {item.chunk for item in selected}

    assert 99 in chunks and 1 in chunks
    assert 3 not in chunks, "the weakest prior answer was preferred to a better one"


def test_guidelines_alone_still_fill_the_prompt():
    evidence = order_evidence([guideline(n) for n in range(10)])
    assert len(select_evidence(evidence, limit=6, prior_cap=4)) == 6


def test_selection_preserves_the_order_it_was_given():
    """Reranked order is relevance order; selection must not reshuffle it."""
    evidence = [guideline(3), prior(1, score=0.9), guideline(1), guideline(2)]

    selected = select_evidence(evidence, limit=4, prior_cap=4)

    assert [item.chunk for item in selected] == [3, 1, 1, 2]


def test_a_cap_of_zero_prefers_every_available_guideline():
    evidence = order_evidence([prior(1)] + [guideline(n) for n in range(2, 8)])

    selected = select_evidence(evidence, limit=5, prior_cap=0)

    assert all(item.source_type is SourceType.GUIDELINE for item in selected)


def test_the_cap_binds_only_while_guidelines_are_competing():
    """It exists to stop displacement, not to shrink the prompt.

    With guidelines to spare the ceiling holds; with none to spare the unused
    room goes back rather than being left empty, because a prior answer in the
    prompt beats a blank line in it.
    """
    priors = [prior(n, score=0.5) for n in range(6)]

    contested = select_evidence(
        order_evidence(priors + [guideline(n) for n in range(90, 96)]), limit=6, prior_cap=2)
    uncontested = select_evidence(order_evidence(priors), limit=6, prior_cap=2)

    assert sum(1 for i in contested if i.source_type is SourceType.PRIOR_ANSWER) == 2
    assert sum(1 for i in uncontested if i.source_type is SourceType.PRIOR_ANSWER) == 6


def test_nothing_selected_from_nothing():
    assert select_evidence([], limit=5, prior_cap=4) == []
    assert select_evidence([guideline(1)], limit=0, prior_cap=4) == []


# --- query agreement -------------------------------------------------------
#
# Expanded queries are written to overlap, so a chunk several of them return
# independently is better evidence than one a single phrasing surfaced. The
# signal is free, but it must not fire where it means nothing: one query, one
# hit each, and the multiplier has to be exactly 1.


def test_agreement_lifts_a_chunk_several_queries_found():
    weak_but_agreed = guideline(1, score=0.60, query_hits=3)
    strong_but_alone = guideline(2, score=0.66, query_hits=1)

    ordered = order_evidence([strong_but_alone, weak_but_agreed])

    assert [item.chunk for item in ordered] == [1, 2]


def test_agreement_cannot_overturn_a_much_better_match():
    """A lift, not an override: three weak agreements must not beat a strong hit."""
    ordered = order_evidence([guideline(1, score=0.35, query_hits=4), guideline(2, score=0.72)])
    assert [item.chunk for item in ordered] == [2, 1]


def test_one_query_per_chunk_changes_nothing(monkeypatch):
    """Query expansion off: every chunk has one hit, so the ordering is the old one."""
    monkeypatch.setattr(settings, "query_expansion", False)
    items = [guideline(1, score=0.4), guideline(2, score=0.9), guideline(3, score=0.6)]

    assert [i.chunk for i in order_evidence(items)] == [2, 3, 1]


def test_the_weight_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(settings, "query_agreement_weight", 0.0)
    ordered = order_evidence([guideline(1, score=0.60, query_hits=4), guideline(2, score=0.66)])
    assert [item.chunk for item in ordered] == [2, 1]


@pytest.mark.parametrize(("hits", "expected"), [(0, 1.0), (1, 1.0), (2, 1.15), (4, 1.45)])
def test_the_bonus_scales_with_agreement(hits, expected, monkeypatch):
    monkeypatch.setattr(settings, "query_agreement_weight", 0.15)
    assert agreement_bonus(hits) == pytest.approx(expected)


def test_agreement_accumulates_across_retrieval_rounds():
    """A chunk two queries found, then the refined query found again, is a 3."""
    first = [guideline(1, score=0.5, query_hits=2)]
    second = [guideline(1, score=0.5, query_hits=1)]

    merged = merge_evidence(first, second)

    assert len(merged) == 1 and merged[0].query_hits == 3


def test_a_better_scoring_copy_keeps_the_accumulated_agreement():
    merged = merge_evidence(
        [guideline(1, score=0.4, query_hits=2)],
        [guideline(1, score=0.9, query_hits=1)],
    )
    assert merged[0].score == 0.9
    assert merged[0].query_hits == 3, "replacing the copy dropped the agreement history"


def test_prior_answers_still_lead_whatever_the_agreement():
    """Agreement reorders within a kind; it must not reorder the kinds."""
    ordered = order_evidence([guideline(1, score=0.9, query_hits=4), prior(2, score=0.2)])
    assert ordered[0].source_type is SourceType.PRIOR_ANSWER


def test_a_negative_score_does_not_collapse_into_a_tie():
    """The 0.0 seed used to flatten every below-zero group onto one value."""
    ordered = order_evidence([guideline(1, score=-0.30), guideline(2, score=-0.05)])
    assert [item.chunk for item in ordered] == [2, 1]
