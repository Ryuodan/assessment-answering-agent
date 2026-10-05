"""Tests for citation support checking and coverage-aware confidence."""

from __future__ import annotations

import pytest

from src.models import Evidence, SourceType
from src.verification import (
    evidence_for,
    assess,
    explain_confidence,
    incomplete_units,
    mentioned_clauses,
    rests_on_memory_alone,
    unsupported_clauses,
)


def ev(**overrides) -> Evidence:
    base = dict(
        source_type=SourceType.GUIDELINE,
        source_name="std.pdf",
        snippet="body",
        doc_id="MDS-CS-STD-006",
    )
    base.update(overrides)
    return Evidence(**base)


# --- clause mentions -------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Per MDS-CS-STD-006 \u00a75.5, releases require all gates.", ["5.5"]),
        ("See \u00a7 7.2.1 and \u00a710.", ["7.2.1", "10"]),
        ("Covered by \u00a75.1\u20135.6 of the standard.", ["5.1", "5.6"]),
        ("No clause identifiers here at all.", []),
        ("Section 5.5 without the sign is not a claim.", []),
    ],
)
def test_mentioned_clauses(text, expected):
    assert mentioned_clauses(text) == expected


def test_clause_inside_the_span_is_supported():
    cited = [ev(clause_start="5.1", clause_end="5.6")]
    assert unsupported_clauses("Per \u00a75.5 the gates apply.", cited) == []


def test_clause_outside_the_span_is_flagged():
    """The Q43 failure: prose cites 5.5 while the evidence stops at 5.4."""
    cited = [ev(clause_start="5.1", clause_end="5.4")]
    assert unsupported_clauses("Per \u00a75.5 the gates apply.", cited) == ["5.5"]


def test_clause_supported_by_any_one_of_several_sources():
    cited = [ev(clause_start="5.1", clause_end="5.4"), ev(clause_start="8.1", clause_end="8.9")]
    assert unsupported_clauses("See \u00a75.2 and \u00a78.3.", cited) == []


def test_all_clauses_unsupported_when_nothing_was_cited():
    assert unsupported_clauses("Per \u00a75.5.", []) == ["5.5"]


def test_single_clause_chunk_supports_only_itself():
    cited = [ev(clause_start="7.2", clause_end="7.2")]
    assert unsupported_clauses("See \u00a77.2.", cited) == []
    assert unsupported_clauses("See \u00a77.3.", cited) == ["7.3"]


def test_clause_numbered_inside_the_body_is_supported():
    """The 95%-false-positive case: the label and the body number differently.

    A chunk headed "5.1.7 Data Deletion" whose bullets are 5.2.1 to 5.2.4 does
    cover 5.2.1. Matching only the chunk's own label reported all four as
    fabricated and capped confidence on 22 of 28 answers.
    """
    cited = [
        ev(
            clause_start="5.1.7",
            clause_end="5.1.7",
            snippet=(
                "## 5.1.7 Data Deletion:\n"
                "- 5.2.1. T2 will delete all customer data within 90 days of termination.\n"
                "- 5.2.4. Deletion covers backups, archives and disaster recovery systems."
            ),
        )
    ]
    assert unsupported_clauses("Deleted within 90 days (§5.2.1), backups included (§5.2.4).", cited) == []


def test_body_match_does_not_accept_a_neighbouring_number():
    """A mention of 5.2.1 must not be satisfied by 15.2.1 or 5.2.10 in the text."""
    cited = [ev(clause_start="", clause_end="", snippet="See 15.2.1 and 5.2.10 for detail.")]
    assert unsupported_clauses("Per §5.2.1 the data is deleted.", cited) == ["5.2.1"]


def test_body_match_tolerates_a_trailing_sentence_period():
    cited = [ev(clause_start="", clause_end="", snippet="- 5.2.1. Data is deleted within 90 days.")]
    assert unsupported_clauses("Per §5.2.1 the data is deleted.", cited) == []


# --- unit completeness -----------------------------------------------------


def test_all_parts_present_is_complete():
    cited = [ev(unit_id="u1", part=n, parts=3) for n in (1, 2, 3)]
    assert incomplete_units(cited) == []


def test_missing_part_is_detected():
    cited = [ev(unit_id="u1", part=1, parts=3), ev(unit_id="u1", part=2, parts=3)]
    assert incomplete_units(cited) == ["u1"]


def test_unsplit_units_are_never_incomplete():
    assert incomplete_units([ev(unit_id="u1", part=1, parts=1)]) == []


def test_evidence_without_a_unit_id_is_ignored():
    assert incomplete_units([ev(part=1, parts=4)]) == []


def test_several_units_reported_independently():
    cited = [
        ev(unit_id="u1", part=1, parts=2),
        ev(unit_id="u2", part=1, parts=2),
        ev(unit_id="u2", part=2, parts=2),
    ]
    assert incomplete_units(cited) == ["u1"]


# --- assess ----------------------------------------------------------------


def clean(**kwargs):
    defaults = dict(grounded=True, review_threshold=0.6, incomplete_cap=0.5)
    defaults.update(kwargs)
    return defaults


def test_a_clean_answer_passes_untouched():
    cited = [ev(clause_start="7.2", clause_end="7.4", unit_id="u1", part=1, parts=1)]
    confidence, review, reasons = assess("Per \u00a77.3.", cited, 0.9, **clean())
    assert (confidence, review, reasons) == (0.9, False, [])


def test_unsupported_citation_caps_confidence_and_forces_review():
    """The dangerous case: a wrong answer wearing a precise citation."""
    cited = [ev(clause_start="5.1", clause_end="5.4")]
    confidence, review, reasons = assess("Per \u00a75.5.", cited, 0.85, **clean())
    assert confidence == 0.5 and review is True
    assert "5.5" in reasons[0]


def test_partial_series_caps_confidence_and_forces_review():
    cited = [ev(unit_id="u1", part=1, parts=4, clause_start="7.2", clause_end="7.2.3")]
    confidence, review, reasons = assess("The conditions are three.", cited, 0.85, **clean())
    assert confidence == 0.5 and review is True
    assert "incomplete" in reasons[0]


def test_ungrounded_always_needs_review():
    _, review, reasons = assess("text", [ev(clause_start="1")], 0.95, **clean(grounded=False))
    assert review is True and reasons


def test_threshold_is_inclusive():
    """An answer at exactly 0.60 was shipping unflagged on a strict comparison."""
    cited = [ev(clause_start="7.2", clause_end="7.2")]
    _, review, _ = assess("no clause claims", cited, 0.60, **clean())
    assert review is True


def test_just_above_threshold_passes():
    cited = [ev(clause_start="7.2", clause_end="7.2")]
    _, review, _ = assess("no clause claims", cited, 0.61, **clean())
    assert review is False


def test_confidence_is_never_raised():
    cited = [ev(clause_start="5.1", clause_end="5.6")]
    confidence, _, _ = assess("Per \u00a75.2.", cited, 0.3, **clean())
    assert confidence == 0.3


def test_reasons_accumulate():
    cited = [ev(clause_start="5.1", clause_end="5.4", unit_id="u1", part=1, parts=3)]
    _, _, reasons = assess("Per \u00a75.9.", cited, 0.9, **clean(grounded=False))
    assert len(reasons) == 3


# --- completeness, judged on cited x retrieved -----------------------------


def _part(unit: str, part: int, parts: int, chunk: int = 0) -> Evidence:
    return Evidence(
        source_type=SourceType.GUIDELINE,
        source_name="std.pdf",
        snippet=f"{unit} part {part}",
        unit_id=unit,
        part=part,
        parts=parts,
        chunk=chunk,
    )


def test_citing_one_part_of_a_fully_retrieved_unit_is_not_flagged():
    """The drafter read all four parts; referencing one is not a gap."""
    retrieved = [_part("u1", n, 4, chunk=n) for n in (1, 2, 3, 4)]
    assert incomplete_units([retrieved[0]], retrieved) == []


def test_citing_a_part_whose_siblings_were_never_retrieved_is_flagged():
    retrieved = [_part("u1", 2, 4, chunk=2)]
    assert incomplete_units(retrieved, retrieved) == ["u1"]


def test_an_unused_partial_unit_does_not_flag_the_answer():
    """The failure that made the queue useless: 34 of 42 answers flagged."""
    used = _part("u1", 1, 1, chunk=1)
    unused_partial = _part("u2", 3, 5, chunk=9)

    assert incomplete_units([used], [used, unused_partial]) == []


def test_an_unsplit_unit_is_never_flagged():
    whole = _part("u1", 1, 1)
    assert incomplete_units([whole], [whole]) == []


def test_completeness_falls_back_to_cited_when_nothing_retrieved_is_given():
    cited = [_part("u1", 2, 3, chunk=2)]
    assert incomplete_units(cited) == ["u1"]


def test_assess_does_not_cap_confidence_for_an_unused_partial_unit():
    used = _part("u1", 1, 1, chunk=1)
    unused_partial = _part("u2", 3, 5, chunk=9)

    confidence, needs_review, reasons = assess(
        "A grounded answer with no clause citations.",
        [used],
        0.9,
        retrieved=[used, unused_partial],
        grounded=True,
        review_threshold=0.6,
        incomplete_cap=0.5,
    )

    assert confidence == 0.9
    assert needs_review is False
    assert reasons == []


# --- support judged on what the drafter read -------------------------------


def _chunk(snippet: str, chunk: int, unit: str = "", part: int = 1, parts: int = 1) -> Evidence:
    return Evidence(
        source_type=SourceType.GUIDELINE,
        source_name="pentest.pdf",
        snippet=snippet,
        chunk=chunk,
        unit_id=unit,
        part=part,
        parts=parts,
    )


PART_ONE = _chunk("3.1.4 Testing every six months. 3.1.7 A qualified team.", 1, "u3", 1, 2)
PART_TWO = _chunk("3.1.20 Approved Penetration Testing Tools: NCA-approved tools.", 2, "u3", 2, 2)
ANSWER = "Testing runs every six months (§3.1.4) using NCA-approved tools (§3.1.20)."


def test_a_clause_the_drafter_read_but_did_not_cite_is_not_unsupported():
    """The reported false positive: 3.1.20 exists, was retrieved, was correct."""
    assert unsupported_clauses(ANSWER, [PART_ONE], [PART_ONE, PART_TWO]) == []


def test_a_clause_in_no_retrieved_chunk_is_still_flagged():
    """Fabrication is the case worth keeping."""
    invented = "Testing follows §9.9.9, which nothing covers."
    assert unsupported_clauses(invented, [PART_ONE], [PART_ONE, PART_TWO]) == ["9.9.9"]


def test_the_sibling_part_is_attached_to_the_answer_evidence():
    """The reader saw '1 supporting source' under an answer built on two."""
    chosen = evidence_for(ANSWER, [PART_ONE], [PART_ONE, PART_TWO])
    assert [item.chunk for item in chosen] == [1, 2]


def test_a_chunk_supporting_a_named_clause_is_attached_even_from_another_unit():
    other = _chunk("5.5.5 An unrelated but cited clause.", 9, "u9")
    chosen = evidence_for("See §5.5.5.", [PART_ONE], [PART_ONE, other])
    assert other.chunk in [item.chunk for item in chosen]


def test_evidence_recovery_adds_nothing_when_the_citation_is_complete():
    chosen = evidence_for("Testing every six months (§3.1.4).", [PART_ONE], [PART_ONE])
    assert [item.chunk for item in chosen] == [1]


def test_the_q4_case_end_to_end_is_no_longer_flagged():
    confidence, needs_review, reasons = assess(
        ANSWER,
        evidence_for(ANSWER, [PART_ONE], [PART_ONE, PART_TWO]),
        0.85,
        retrieved=[PART_ONE, PART_TWO],
        grounded=True,
        review_threshold=0.6,
        incomplete_cap=0.5,
    )
    assert reasons == []
    assert needs_review is False
    assert confidence == 0.85


# --- why the score came out low --------------------------------------------
#
# The mechanical checks stay silent unless something is demonstrably wrong, so
# an answer flagged purely for scoring low reached the interface with nothing
# to show. These cover the sentence that fills that gap.


def _why(confidence, cited, **kwargs):
    options = dict(grounded=True, review_threshold=0.6, verdict_reason="")
    options.update(kwargs)
    return explain_confidence(confidence, cited, **options)


def test_a_confident_grounded_answer_needs_no_explanation():
    assert _why(0.9, [ev()]) == ""


def test_a_low_score_always_carries_an_explanation():
    """The reported gap: flagged, but with nothing said about why."""
    assert _why(0.55, [ev()]) != ""


def test_no_sources_is_named_as_the_cause():
    text = _why(0.2, [])
    assert "Nothing in the knowledge base matched" in text


def test_an_ungrounded_answer_says_the_review_failed():
    text = _why(0.8, [ev()], grounded=False)
    assert "could not trace every statement" in text


def test_the_reviewers_own_words_are_passed_through():
    text = _why(0.8, [ev()], grounded=False, verdict_reason="the retention period is not stated")
    assert "the retention period is not stated" in text


def test_a_very_low_score_says_the_sources_do_not_cover_it():
    assert "does not answer the question directly" not in _why(0.5, [ev()])
    assert "answers the question" in _why(0.25, [ev()])


def test_a_middling_score_says_it_was_inferred():
    assert "inferred by combining" in _why(0.5, [ev()])


def test_the_source_count_is_reported_and_agrees_in_number():
    assert "1 source." in _why(0.5, [ev()])
    assert "2 sources." in _why(0.5, [ev(), ev()])


def test_an_ungrounded_answer_is_explained_even_above_the_threshold():
    """Grounding failures are flagged whatever the score, so they must explain."""
    assert _why(0.95, [ev()], grounded=False) != ""


def test_the_explanation_avoids_internal_vocabulary():
    """Written for whoever fills in the form, not for whoever wrote the retriever."""
    for confidence in (0.1, 0.35, 0.55):
        text = _why(confidence, [ev()]).lower()
        assert "chunk" not in text
        assert "threshold" not in text
        assert "embedding" not in text


# --- the completeness check must not contradict the retriever ---------------


def _unit(part: int, parts: int, chunk: int = 0) -> Evidence:
    return Evidence(
        source_type=SourceType.GUIDELINE,
        source_name="std.pdf",
        snippet="body",
        unit_id="u1",
        part=part,
        parts=parts,
        chunk=chunk,
    )


def test_a_chapter_sized_unit_is_not_reported_incomplete():
    """The retriever never completes these, so demanding it did is a false alarm."""
    cited = [_unit(part=7, parts=113)]
    assert incomplete_units(cited, cited, completable_parts=6) == []


def test_a_series_sized_unit_is_still_reported_incomplete():
    """The behaviour the exemption must not swallow."""
    cited = [_unit(part=1, parts=4)]
    assert incomplete_units(cited, cited, completable_parts=6) == ["u1"]


def test_without_the_limit_the_old_behaviour_is_unchanged():
    cited = [_unit(part=7, parts=113)]
    assert incomplete_units(cited, cited) == ["u1"]


def test_assess_passes_the_limit_through():
    cited = [_unit(part=7, parts=113)]
    confidence, review, reasons = assess(
        "text",
        cited,
        0.9,
        retrieved=cited,
        grounded=True,
        review_threshold=0.6,
        incomplete_cap=0.5,
        completable_parts=6,
    )
    assert reasons == [] and review is False and confidence == 0.9


# --- an answer with nothing of ours behind it -------------------------------
#
# A previous answer is the best evidence of *how we answer* and no evidence at
# all of what is true. An answer built only from one looks exactly like an
# answer built from a policy, and the reported case -- "in which jurisdiction
# will you store the Personal Data" -- scored 0.90 and was on its way into a
# customer's file citing two remembered answers and no document.


def prior(**overrides):
    return ev(source_type=SourceType.PRIOR_ANSWER, source_name="Answer memory", **overrides)


def test_an_answer_citing_only_previous_answers_is_flagged():
    cited = [prior(), prior(snippet="another")]
    confidence, review, reasons = assess(
        "All personal data is stored within the Kingdom.",
        cited,
        0.9,
        retrieved=cited,
        grounded=True,
        review_threshold=0.6,
        incomplete_cap=0.5,
    )

    assert review is True
    assert any("rests only on what we told somebody before" in reason for reason in reasons)
    assert confidence == 0.9, "provenance is not a scoring problem"


def test_one_policy_among_them_is_enough():
    """The common case, and it must not be flagged: measured over nineteen real
    questions, eighteen cited at least one policy."""
    cited = [prior(), ev()]
    _, review, reasons = assess(
        "text",
        cited,
        0.9,
        retrieved=cited,
        grounded=True,
        review_threshold=0.6,
        incomplete_cap=0.5,
    )
    assert reasons == [] and review is False


def test_an_answer_with_no_sources_at_all_is_not_this_flag():
    """It is already flagged, and for a different reason: there was nothing to
    answer from, rather than the wrong kind of something."""
    assert rests_on_memory_alone([]) is False
