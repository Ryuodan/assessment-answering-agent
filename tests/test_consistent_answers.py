"""The same question gets the same answer more often, without copying (plan 034).

Measured before: in three identical runs of one NAC question the decision
flipped between held and released, and one run claimed "Network Access Control
(NAC)", a name no source used.
"""

from __future__ import annotations

import pytest

from src.formatting import same_wording
from src.graph.state import select_evidence
from src.models import Evidence, SourceType
from src.prompts import ANSWER_SYSTEM, REVIEW_SYSTEM, format_sources_block

ASKED = "Do you have a documented incident response plan, and how often is it tested?"


def prior(question: str, answer: str = "Yes.", score: float = 0.5, entry: str = "") -> Evidence:
    return Evidence(
        source_type=SourceType.PRIOR_ANSWER,
        source_name="Answer memory",
        snippet=f"Q: {question}\nA: {answer}",
        score=score,
        entry_id=entry or question[:12],
    )


def guideline(n: int, score: float = 0.6) -> Evidence:
    return Evidence(
        source_type=SourceType.GUIDELINE, source_name="Policy.pdf", snippet=f"Clause {n}.", chunk=n, score=score
    )


@pytest.mark.parametrize(
    ("stored", "asked", "same"),
    [
        ("Do you have an incident response plan?", "do you have an incident response plan", True),
        ("Is MFA enforced  for remote access?", "Is MFA enforced for remote access ?", True),
        ("هل لديكم خطةٌ للاستجابة للحوادث؟", "هل لديكم خطة للاستجابة للحوادث", True),
        ("Retained for 12 months?", "Retained for ١٢ months?", True),
        ("Is the incident response plan tested?", "Is the business continuity plan tested?", False),
        ("Do you have an incident response plan?", "Do you have an incident response plan and a BCP?", False),
        ("", "", False),
    ],
)
def test_the_same_words_are_the_same_question_and_nothing_looser_is(stored, asked, same):
    """Deliberately exact: neighbouring controls read alike and are not the same question."""
    assert same_wording(stored, asked) is same


def test_a_previous_answer_says_what_it_was_asked():
    assert prior("Do you?", "Yes, we do.").asked == "Do you?"
    assert guideline(1).asked == ""


def test_the_same_questions_earlier_answer_is_kept_first_whatever_its_score():
    """It is how we answered exactly this before. Ranked by this run's searches, it fell
    to the cap of earlier answers, so whether it was read at all depended on the run."""
    mine = prior(ASKED, "Yes, tested yearly.", score=0.31, entry="MEM-1")
    others = [prior(f"Neighbouring question {n}?", score=0.8 - n / 100, entry=f"MEM-{n + 10}") for n in range(4)]
    evidence = others + [mine] + [guideline(n) for n in range(12)]  # enough to fill the budget

    selected = select_evidence(evidence, limit=10, prior_cap=2, question=ASKED)
    assert selected[0] is mine
    assert sum(1 for item in selected if item.source_type is SourceType.PRIOR_ANSWER) == 3, "the cap, plus this one"

    without = select_evidence(evidence, limit=10, prior_cap=2)
    assert mine not in without, "without the question, as before: the cap keeps the two best"


def test_the_drafter_is_told_which_earlier_answer_is_to_this_same_question():
    mine, other = prior(ASKED), prior("Is the business continuity plan tested?")
    block = format_sources_block([mine, other, guideline(1)], question=ASKED)
    assert "[1] PREVIOUS ANSWER TO THIS SAME QUESTION —" in block
    assert "[2] PREVIOUS ANSWER —" in block
    assert "SAME QUESTION" not in format_sources_block([mine, other, guideline(1)]), "as before without the question"


def test_the_drafter_keeps_the_same_questions_position_and_facts():
    assert "A PREVIOUS ANSWER TO THIS SAME QUESTION answered these very words before" in ANSWER_SYSTEM
    assert "unless OUR POLICY now says otherwise" in ANSWER_SYSTEM


def test_a_name_from_the_question_is_not_claimed_unless_a_source_names_it():
    assert "Do not take a technology, product, tool or programme name from the question" in ANSWER_SYSTEM
    assert (
        "It claims a technology, product or programme by a name the question used and no source does." in REVIEW_SYSTEM
    )
