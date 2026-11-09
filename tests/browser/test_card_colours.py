"""What the card's colours say, in a real browser (plan 042).

Colour says one thing each: green is fine, amber a person should look, red low
or failed, blue the knowledge base, plum the answer memory. The words say it
too, so nothing depends on seeing the colour.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Locator, Page, expect

from src.models import AnsweredQuestion, Evidence, SourceType
from tests import forms_fixtures as shapes
from tests.browser.test_review_filter import answered, tab

pytestmark = pytest.mark.browser

POLICY = Evidence(
    source_type=SourceType.GUIDELINE,
    source_name="Backup Policy.pdf",
    snippet="Backups are encrypted.",
    score=0.7,
    chunk=0,
    clause="4",
)
EARLIER = Evidence(
    source_type=SourceType.PRIOR_ANSWER,
    source_name="Answer memory",
    snippet="Q: Encrypted?\nA: Yes.",
    score=0.7,
    chunk=1,
    questionnaire="Answer memory",
    answered_date="2026-10-01",
)


def background(locator: Locator) -> str:
    return locator.evaluate("e => getComputedStyle(e).backgroundColor")


def colour(locator: Locator) -> str:
    return locator.evaluate("e => getComputedStyle(e).color")


@pytest.fixture
def varied(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sure and clear; above the line but not by much; held by a check though sure; held by its score."""

    async def made(questions, language=None, run_id=None, **extra):
        return [
            AnsweredQuestion(
                question=questions[0],
                answer="Yes.",
                confidence=0.9,
                needs_review=False,
                evidence=[POLICY, EARLIER],
                citations=[EARLIER.locator, POLICY.locator],
            ),
            AnsweredQuestion(question=questions[1], answer="Mostly.", confidence=0.7, needs_review=False),
            AnsweredQuestion(
                question=questions[2],
                answer="Partly.",
                confidence=0.9,
                needs_review=True,
                review_reasons=["the sources disagree"],
                confidence_reason="the reviewer could not trace every statement",
                rationale="Clause 7 covers part of it.",
            ),
            AnsweredQuestion(
                question=questions[3],
                answer="Probably.",
                confidence=0.4,
                needs_review=True,
                confidence_reason="the retrieved sources only partly cover this question",
            ),
        ]

    monkeypatch.setattr("src.tools.service.answer_questions", made)


@pytest.fixture
def cards(page: Page, tmp_path: Path, varied: None) -> Locator:
    answered(page, shapes.simple(tmp_path / "vendor.xlsx"), 4)
    tab(page, "All").click()
    return page.locator("#results .answer")


def test_the_confidence_is_coloured_from_the_servers_threshold(cards: Locator) -> None:
    scores = cards.locator(".status-score")

    expect(scores).to_have_text(["90% confidence", "70% confidence", "90% confidence", "40% confidence"])
    expect(scores.nth(0)).to_have_class("status-score high")
    expect(scores.nth(1)).to_have_class("status-score mid")
    expect(scores.nth(2)).to_have_class("status-score mid")  # a check held it: never green beside Needs review
    expect(scores.nth(3)).to_have_class("status-score low")
    assert len({background(scores.nth(i)) for i in (0, 1, 3)}) == 3


def test_a_persons_decision_leaves_the_score_uncoloured(page: Page, cards: Locator) -> None:
    held = cards.filter(has_text="Probably.")
    held.locator('[data-card-action="approve"]').click()

    expect(page.locator("#results .answer", has_text="Probably.").locator(".status-score")).to_have_class(
        "status-score plain"
    )


def test_with_no_threshold_the_card_invents_no_colour(page: Page, cards: Locator) -> None:
    tone = page.evaluate(
        """() => {
             Cards.setReviewThreshold(null);
             const item = { question: { id: "q", text: "Q", question_type: "free_text" }, answer: "Yes.", confidence: 0.9 };
             return Cards.render(item, 0).querySelector(".status-score").className;
           }"""
    )
    assert tone == "status-score plain"


def test_the_answer_stands_on_its_own_ground(page: Page, cards: Locator) -> None:
    card = cards.first

    assert background(card.locator(".rendered")) != background(card)


def test_a_note_in_place_of_an_answer_is_not_set_apart(page: Page, cards: Locator) -> None:
    card = cards.first
    card.locator(".card-more summary").click()
    card.get_by_role("button", name="Leave blank").click()

    blank = page.locator("#results .answer").first.locator(".rendered")
    expect(blank).to_contain_text("This answer will be left blank.")
    assert background(blank) == "rgba(0, 0, 0, 0)"


def test_each_source_says_where_it_came_from(cards: Locator) -> None:
    field = cards.first.locator(".sources-field")

    expect(field.locator(".cites-label")).to_have_text(["Knowledge base", "Answer memory"])
    kb, memory = field.locator(".cites.guideline"), field.locator(".cites.prior_answer")
    expect(kb.locator(".cite")).to_contain_text("Backup Policy.pdf §4")
    expect(memory.locator(".cite")).to_contain_text("Answer memory (2026-10-01)")
    assert background(kb.locator(".cite")) != background(memory.locator(".cite"))
    assert colour(kb.locator(".cites-label")) == colour(kb.locator(".cite"))

    memory.locator(".cite").click()  # the right source opens, though the rows reordered them
    panel = cards.first.locator(".cite-panel")
    expect(panel.locator(".tag.from")).to_have_text("Answer memory")
    expect(panel).to_contain_text("Yes.")
    kb.locator(".cite").click()
    expect(panel.locator(".tag.from")).to_have_text("Knowledge base")
    expect(panel).to_contain_text("Backups are encrypted.")


def test_what_is_wrong_is_coloured_and_the_reasoning_is_not(cards: Locator) -> None:
    sure = cards.filter(has_text="Partly.")
    sure.get_by_role("button", name="Why this answer").click()
    labels = sure.locator(".why-panel .field-label")

    expect(labels).to_have_text(["Why this is flagged", "Why the confidence is low", "Reasoning"])
    expect(sure.locator(".why-panel .why-warn .field-label")).to_have_text(
        ["Why this is flagged", "Why the confidence is low"]  # the score is fine; a check is what objected
    )
    assert colour(labels.nth(0)) != colour(labels.nth(2))

    low = cards.filter(has_text="Probably.")
    low.get_by_role("button", name="Why this answer").click()
    expect(low.locator(".why-panel .why-err .field-label")).to_have_text("Why the confidence is low")
    assert background(low.locator(".why-err")) != background(low.locator(".why-panel"))
