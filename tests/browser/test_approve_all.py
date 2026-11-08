"""Approve all, and the card's layout, in a real browser (plan 041).

Approve all asks first, in the page, and says what it will and will not do.
What it writes is decided on the server (`tests/test_approve_all.py`).

The card asks one thing, whether the answer is right: the reasons, the
reasoning and the rarer actions are one click away, not on every card.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from src.models import AnsweredQuestion
from tests import forms_fixtures as shapes
from tests.browser.test_chat_review_tabs import answered_in_the_chat, cards
from tests.browser.test_chat_review_tabs import tab as chat_tab
from tests.browser.test_review_filter import answered, mixed, tab  # noqa: F401

pytestmark = pytest.mark.browser

REASON = "the sources disagree"


def dialog(page: Page):
    return page.locator("dialog.card-dialog")


def test_approve_all_asks_first_and_cancelling_changes_nothing(page: Page, tmp_path: Path, mixed: None) -> None:  # noqa: F811
    answered(page, shapes.simple(tmp_path / "vendor.xlsx"), 4)
    button = page.locator("#approveAllBtn")
    expect(button).to_have_text("Approve all (2)")  # the flagged one and the unsure one, not the failed one

    button.click()

    expect(dialog(page)).to_contain_text("Approve every answer that needs review?")
    expect(dialog(page)).to_contain_text("Answers to approve: 2")
    expect(dialog(page)).to_contain_text("They go into the file under your name")
    expect(dialog(page)).to_contain_text("They are not added to the answer memory.")
    expect(dialog(page)).to_contain_text("Questions that could not be answered stay under Needs review: 1")
    expect(
        dialog(page).get_by_role("button", name="Cancel")
    ).to_be_focused()  # Enter on a dialog nobody read does nothing
    box = dialog(page).bounding_box()
    assert box and box["height"] < 400, "as tall as what it says, not the page's document viewer"

    dialog(page).get_by_role("button", name="Cancel").click()

    expect(dialog(page)).to_have_count(0)
    expect(tab(page, "Needs review")).to_have_text("Needs review (3)")
    expect(tab(page, "Done by a person")).to_have_text("Done by a person (0)")


def test_confirming_approves_them_and_leaves_the_failed_one(page: Page, tmp_path: Path, mixed: None) -> None:  # noqa: F811
    answered(page, shapes.simple(tmp_path / "vendor.xlsx"), 4)

    page.click("#approveAllBtn")
    dialog(page).get_by_role("button", name="Approve all (2)").click()

    expect(tab(page, "Needs review")).to_have_text("Needs review (1)")
    expect(tab(page, "Done by a person")).to_have_text("Done by a person (2)")
    expect(page.locator("#reviewStatus")).to_contain_text("None were added to the answer memory.")
    expect(page.locator("#approveAllBtn")).to_be_hidden()  # nothing left it could approve
    expect(page.locator("#results .answer .status-word")).to_have_text(["Could not be answered"])


def test_the_chat_has_it_too(page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    answered_in_the_chat(page, tmp_path, monkeypatch)
    button = page.locator("#approveAllBtn")
    expect(button).to_have_text("Approve all (2)")

    button.click()
    dialog(page).get_by_role("button", name="Approve all (2)").click()

    expect(chat_tab(page, "Needs review")).to_have_text("Needs review (0)")
    expect(chat_tab(page, "Done by a person")).to_have_text("Done by a person (2)")
    expect(page.locator("#answersStatus")).to_contain_text("None were added to the answer memory.")
    expect(button).to_be_hidden()
    expect(cards(page)).to_have_count(0)


def test_a_read_only_questionnaire_has_no_approve_all(page: Page) -> None:
    """A deleted product's answers are kept to read (plan 027); the server refuses too."""
    page.goto("/workbench")
    hidden = page.evaluate(
        """() => {
             Cards.readOnly = true;
             const button = document.createElement("button");
             Cards.paintApproveAll(button, [{ will_be_written: false, answer: "Partly." }], 1, () => {});
             Cards.readOnly = false;
             return button.hidden;
           }"""
    )
    assert hidden is True


@pytest.fixture
def explained(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every answer flagged, with all there is to say about it."""

    async def made(questions, language=None, run_id=None, **extra):
        return [
            AnsweredQuestion(
                question=q,
                answer="Partly.",
                confidence=0.45,
                needs_review=True,
                review_reasons=[REASON],
                confidence_reason="the retrieved sources only partly cover this question",
                rationale="Clause 7.1 covers part of it.",
            )
            for q in questions
        ]

    monkeypatch.setattr("src.tools.service.answer_questions", made)


def test_a_card_says_why_once_and_the_rest_is_one_click_away(page: Page, tmp_path: Path, explained: None) -> None:
    answered(page, shapes.simple(tmp_path / "vendor.xlsx"), 4)
    card = page.locator("#results .answer").first

    expect(card.locator(".reason-chip")).to_have_text(["Sources disagree"])
    for hidden in (REASON, "Clause 7.1 covers part of it.", "the retrieved sources only partly cover"):
        expect(card.get_by_text(hidden)).to_be_hidden()

    card.get_by_role("button", name="Why this answer").click()

    expect(card.get_by_text(REASON)).to_be_visible()
    expect(card.get_by_text("Clause 7.1 covers part of it.")).to_be_visible()
    expect(card.get_by_role("button", name="Why this answer")).to_have_attribute("aria-expanded", "true")


def test_the_two_actions_come_after_the_answer_and_the_rest_are_under_more(
    page: Page, tmp_path: Path, explained: None
) -> None:
    answered(page, shapes.simple(tmp_path / "vendor.xlsx"), 4)
    card = page.locator("#results .answer").first

    expect(card.locator(".card-controls > button:visible")).to_have_text(["Approve", "Edit"])
    assert card.evaluate(
        "c => c.querySelector('.card-actions').getBoundingClientRect().top >= c.querySelector('.rendered').getBoundingClientRect().bottom"
    ), "the actions come after what they act on"

    blank = card.get_by_role("button", name="Leave blank")
    expect(blank).to_be_hidden()
    card.locator(".card-more summary").click()
    expect(blank).to_be_visible()
    expect(card.get_by_role("button", name="Remove this question and its answer")).to_be_visible()

    page.locator("#stepList").click(position={"x": 1, "y": 1})  # anywhere else
    expect(blank).to_be_hidden()

    card.locator(".card-more summary").click()
    expect(blank).to_be_visible()
    page.keyboard.press("Escape")
    expect(blank).to_be_hidden()


def test_a_card_with_no_answer_offers_no_approve(page: Page, tmp_path: Path, mixed: None) -> None:  # noqa: F811
    answered(page, shapes.simple(tmp_path / "vendor.xlsx"), 4)
    failed = page.locator("#results .answer", has=page.locator(".answer-status.failed"))

    expect(failed.locator(".card-controls > button:visible")).to_have_text(["Try this question again", "Edit"])
    expect(failed).to_contain_text("the model was unavailable")


def test_the_answer_step_folds_once_every_question_has_a_card(page: Page, tmp_path: Path, mixed: None) -> None:  # noqa: F811
    answered(page, shapes.simple(tmp_path / "vendor.xlsx"), 4)

    expect(page.locator("#step3Body")).to_be_hidden()
    expect(page.locator("#step3Held")).to_contain_text("answered")

    page.click("#step3Toggle")
    expect(page.locator("#questionListPanel")).to_be_visible()
