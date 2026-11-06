"""Honest confidence (plan 030): a held answer's score never reads above "needs review".

Measured on the evaluations on file, one held answer in eight showed "High
confidence 85%+", and those contradicted the team about ten times as often as
released ones. When a check holds an answer, the score it shows is now capped at
the review threshold, and at the reviewer's own ceiling for an ungrounded
answer. The release decision does not move: these answers were already held.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import verification
from src.api import app
from src.config import settings
from src.graph import nodes
from src.models import AnsweredQuestion, Evidence, Question, SourceType
from src.prompts import REVIEW_SYSTEM, REVIEW_UNGROUNDED_CEILING
from src.schemas import AnswerReview, DraftedAnswer
from src.selection import held_by_the_review, ready_to_write
from src.verification import assess, held_by_score, held_confidence

THRESHOLD = 0.6


def policy(**overrides) -> Evidence:
    defaults = dict(source_type=SourceType.GUIDELINE, source_name="policy.pdf", snippet="7.2 Access is reviewed.")
    defaults.update(overrides)
    return Evidence(**defaults)


def remembered() -> Evidence:
    return Evidence(source_type=SourceType.PRIOR_ANSWER, source_name="Answer memory", snippet="Q: ...\nA: Yes.")


def checked(answer: str, cited: list[Evidence], confidence: float, **options):
    defaults = dict(grounded=True, review_threshold=THRESHOLD, incomplete_cap=0.5)
    defaults.update(options)
    return assess(answer, cited, confidence, retrieved=cited, **defaults)


# --- the cap, rule by rule -------------------------------------------------------


def test_a_released_answer_is_never_capped():
    assert held_confidence(0.95, held=False, grounded=True, review_threshold=THRESHOLD) == 0.95


def test_a_held_answer_shows_no_more_than_the_threshold():
    assert held_confidence(0.95, held=True, grounded=True, review_threshold=THRESHOLD) == THRESHOLD


def test_an_ungrounded_answer_shows_no_more_than_the_reviewers_ceiling():
    assert held_confidence(0.95, held=True, grounded=False, review_threshold=THRESHOLD) == 0.3


def test_the_cap_only_ever_lowers():
    assert held_confidence(0.2, held=True, grounded=False, review_threshold=THRESHOLD) == 0.2
    assert held_confidence(0.45, held=True, grounded=True, review_threshold=THRESHOLD) == 0.45


def test_a_threshold_under_the_ceiling_caps_an_ungrounded_answer_at_the_threshold():
    assert held_confidence(0.95, held=True, grounded=False, review_threshold=0.2) == 0.2


def test_the_ceiling_is_the_review_prompts_own_scale():
    """The 0.3 is the reviewer's instruction for an ungrounded answer; the two must move together."""
    assert f"- 0.0 to {REVIEW_UNGROUNDED_CEILING}: The sources do not actually cover" in REVIEW_SYSTEM


# --- every check that holds an answer caps it -----------------------------------


def test_a_clause_its_sources_do_not_hold_is_capped_at_the_threshold():
    """The incomplete cap is a setting, and can sit above the threshold; the hold cap still applies."""
    result = checked("Per §9.9.", [policy(clause_start="7.2", clause_end="7.4")], 0.9, incomplete_cap=0.8)
    assert result.needs_review and result.reasons[0].startswith(verification.UNSUPPORTED_CLAUSES)
    assert (result.confidence, result.scored) == (THRESHOLD, 0.8)


def test_a_partial_source_is_capped_at_the_threshold():
    cited = [policy(unit_id="u1", part=1, parts=3)]
    result = checked("The conditions are three.", cited, 0.9, incomplete_cap=0.8)
    assert result.reasons == [verification.PARTIAL_SOURCE]
    assert result.confidence == THRESHOLD


def test_an_answer_resting_only_on_previous_answers_is_capped():
    result = checked("All data stays in the Kingdom.", [remembered()], 0.9)
    assert result.reasons == [verification.MEMORY_ALONE]
    assert (result.confidence, result.scored) == (THRESHOLD, 0.9)


def test_an_ungrounded_answer_is_capped_at_the_reviewers_ceiling():
    result = checked("Yes.", [policy()], 0.95, grounded=False)
    assert result.reasons == [verification.UNGROUNDED]
    assert (result.confidence, result.scored) == (0.3, 0.95)


def test_sources_that_disagree_are_capped():
    result = checked("Yes.", [policy()], 0.95, inconsistency="A 2023 answer said annual; the policy says quarterly.")
    assert result.needs_review
    assert result.reasons == [verification.INCONSISTENT + "A 2023 answer said annual; the policy says quarterly."]
    assert result.confidence == THRESHOLD


def test_a_low_score_with_no_reason_is_held_and_unchanged():
    result = checked("Yes.", [policy()], 0.45)
    assert (result.confidence, result.needs_review, result.reasons) == (0.45, True, [])


def test_a_score_at_the_threshold_is_held_and_one_above_it_is_not():
    assert checked("Yes.", [policy()], THRESHOLD).needs_review is True
    above = checked("Yes.", [policy()], 0.61)
    assert (above.confidence, above.needs_review) == (0.61, False)


# --- the pipeline's last step goes through the same cap --------------------------


def state(*, draft: DraftedAnswer, review: AnswerReview, evidence: list[Evidence] | None = None) -> dict:
    return {
        "question": Question(id="1", text="Do you review access?", language="en"),
        "language": "en",
        "search_queries": ["Do you review access?"],
        "attempt": 1,
        "evidence": evidence if evidence is not None else [policy()],
        "draft": draft,
        "review": review,
    }


async def finalized(**kwargs) -> AnsweredQuestion:
    return (await nodes.finalize(state(**kwargs)))["answered"]


async def test_finalize_caps_an_answer_whose_sources_disagree():
    """The conflict was added after `assess` and never capped: it showed 90% beside "needs review"."""
    answered = await finalized(
        draft=DraftedAnswer(
            answer="Yes, quarterly.", confidence=0.95, used_source_ids=[1], contradicts_memory="2023 said annual."
        ),
        review=AnswerReview(grounded=True, confidence=0.9),
    )
    assert answered.needs_review and answered.review_reasons == [verification.INCONSISTENT + "2023 said annual."]
    assert answered.confidence == THRESHOLD
    assert answered.confidence_reason == "", "rated 0.9: no sentence claims the evidence was weak"


async def test_finalize_caps_an_ungrounded_answer_and_keeps_the_reviewers_explanation():
    answered = await finalized(
        draft=DraftedAnswer(answer="Yes.", confidence=0.95, used_source_ids=[1]),
        review=AnswerReview(grounded=False, confidence=0.9, verdict_reason="Nothing says so."),
    )
    assert answered.confidence == 0.3
    assert answered.confidence_reason.startswith("A second model read the answer against the sources")


# --- the release decision does not move -------------------------------------------
#
# Each case runs through `finalize` twice: with the cap taken out, which is the
# pipeline before plan 030, and as it is. The fill gate must say the same of both.

CASES = {
    "clean, released": (DraftedAnswer(answer="Yes.", confidence=0.9, used_source_ids=[1]), True, None, 0.9),
    "just above the threshold": (DraftedAnswer(answer="Yes.", confidence=0.61, used_source_ids=[1]), True, None, 0.61),
    "borderline, at the threshold": (
        DraftedAnswer(answer="Yes.", confidence=0.6, used_source_ids=[1]),
        True,
        None,
        0.6,
    ),
    "low score, no reason": (DraftedAnswer(answer="Yes.", confidence=0.45, used_source_ids=[1]), True, None, 0.45),
    "flagged at 0.95: only previous answers": (
        DraftedAnswer(answer="Yes.", confidence=0.95, used_source_ids=[1]),
        True,
        [remembered()],
        0.6,
    ),
    "flagged at 0.95: sources disagree": (
        DraftedAnswer(answer="Yes.", confidence=0.95, used_source_ids=[1], contradicts_memory="2023 said no."),
        True,
        None,
        0.6,
    ),
    "flagged at 0.95: a clause not in its sources": (
        DraftedAnswer(answer="Per §9.9.", confidence=0.95, used_source_ids=[1]),
        True,
        None,
        0.5,
    ),
    "flagged at 0.95: a partial source": (
        DraftedAnswer(answer="The conditions are three.", confidence=0.95, used_source_ids=[1]),
        True,
        [policy(unit_id="u1", part=1, parts=3)],
        0.5,
    ),
    "ungrounded at 0.95": (DraftedAnswer(answer="Yes.", confidence=0.95, used_source_ids=[1]), False, None, 0.3),
    "ungrounded and low": (DraftedAnswer(answer="Yes.", confidence=0.2, used_source_ids=[1]), False, None, 0.2),
}


@pytest.mark.parametrize("case", sorted(CASES))
async def test_the_cap_changes_no_release_decision(case, monkeypatch):
    draft, grounded, evidence, shown = CASES[case]
    review = AnswerReview(grounded=grounded, confidence=0.95, verdict_reason="checked")
    with monkeypatch.context() as before_plan_030:
        before_plan_030.setattr(verification, "held_confidence", lambda confidence, **_: confidence)
        before = await finalized(draft=draft, review=review, evidence=evidence)
    after = await finalized(draft=draft, review=review, evidence=evidence)

    assert ready_to_write(after) == ready_to_write(before)
    assert held_by_the_review(after) == held_by_the_review(before)
    assert (after.needs_review, after.review_reasons) == (before.needs_review, before.review_reasons)
    assert after.confidence_reason == before.confidence_reason
    assert after.confidence == pytest.approx(shown)
    assert not after.needs_review or after.confidence <= THRESHOLD, "held, and showing more than the threshold"


# --- one threshold rule, everywhere -----------------------------------------------


def unflagged(confidence: float) -> AnsweredQuestion:
    """An answer stored unflagged: a threshold changed since, or an approval withdrawn before plan 029."""
    return AnsweredQuestion(
        question=Question(id="1", text="?", language="en"), answer="Yes.", confidence=confidence, needs_review=False
    )


def test_the_gate_holds_a_score_at_the_threshold_as_the_review_does():
    """The gate compared "under" and the review "at or under": at exactly 0.6 they disagreed."""
    ready, why = ready_to_write(unflagged(THRESHOLD))
    assert ready is False and why == "confidence 60%, not above the 60% needed to write without a person looking"
    assert held_by_the_review(unflagged(THRESHOLD)) is True
    assert ready_to_write(unflagged(0.61)) == (True, "")


def test_the_gate_reads_the_threshold_it_is_given():
    assert ready_to_write(unflagged(0.65), threshold=0.7)[0] is False
    assert ready_to_write(unflagged(0.65), threshold=0.6)[0] is True


def test_the_rule_itself():
    assert held_by_score(0.6, 0.6) and held_by_score(0.59, 0.6) and not held_by_score(0.61, 0.6)


def test_the_pages_read_the_threshold_from_the_server(monkeypatch):
    """The cards hard-coded 0.6; they now take it from the session, which every page asks for on load."""
    monkeypatch.setattr(settings, "review_confidence_threshold", 0.7)
    assert TestClient(app).get("/api/auth/session").json()["review_threshold"] == 0.7
