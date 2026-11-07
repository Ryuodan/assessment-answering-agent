"""An answer card leads with its status, in a real browser (plan 030).

The card coloured the score by band, with 0.6 written into the page, so an
answer the gate held could read "High confidence 90%" beside "needs review".
It now says first whether the answer will be written, or needs review and why,
coloured by that status, with the score after it. The threshold is the
server's, read from the session.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from src import service
from src.agents import assistant
from src.config import settings
from src.models import AnsweredQuestion
from src.verification import INCONSISTENT, MEMORY_ALONE, PARTIAL_SOURCE, UNGROUNDED, UNSUPPORTED_CLAUSES
from tests import forms_fixtures as shapes
from tests.browser.choosing import choose_general
from tests.test_assistant import _graph

pytestmark = pytest.mark.browser

ANSWER = "Yes, multi-factor authentication is enforced."
ARABIC = "نعم، يتم فرض المصادقة متعددة العوامل على جميع الحسابات."

# The simple workbook's four questions, each held by a different check at a score
# the models rated well: an answer drafted before the cap, or any held answer.
HELD_BY = [
    ([INCONSISTENT + "a 2023 answer said otherwise"], "Sources disagree"),
    ([UNGROUNDED], "Not backed by our documents"),
    ([MEMORY_ALONE], "Only from previous answers"),
    ([PARTIAL_SOURCE, UNSUPPORTED_CLAUSES + "9.9"], "Partial source"),
]


def answering(monkeypatch: pytest.MonkeyPatch, make) -> None:
    async def answered(questions, language=None, run_id=None, **extra):
        return [make(index, q) for index, q in enumerate(questions)]

    monkeypatch.setattr("src.tools.service.answer_questions", answered)


def answered_on_the_workbench(page: Page, tmp_path: Path) -> None:
    page.goto("/workbench")
    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))
    choose_general(page)
    page.click("#answerBtn")
    expect(page.locator("#reviewBar")).to_be_visible(timeout=15_000)
    page.locator("#reviewTabs").get_by_role("button", name="All (4)").click()
    expect(page.locator("#results .answer")).to_have_count(4)


def test_a_held_answer_says_needs_review_first_whatever_its_score(
    page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answering(
        monkeypatch,
        lambda index, q: AnsweredQuestion(
            question=q, answer=ANSWER, confidence=0.9, needs_review=True, review_reasons=HELD_BY[index][0]
        ),
    )
    answered_on_the_workbench(page, tmp_path)

    for index, (_, chip) in enumerate(HELD_BY):
        card = page.locator("#results .answer").nth(index)
        status = card.locator(":scope > .answer-status")
        expect(card.locator(":scope > :first-child")).to_have_class("answer-status review")  # the status first
        expect(status.locator(".status-word")).to_have_text("Needs review")
        expect(status.locator(".reason-chip").first).to_have_text(chip)
        expect(status.locator(".status-score")).to_have_text("90% confidence")
        expect(card).not_to_contain_text("High")
        expect(card).to_have_class("answer review")

    last = page.locator("#results .answer").nth(3).locator(".reason-chip")
    expect(last).to_have_text(["Partial source", "Cites clauses not in its sources"])
    expect(last.first).to_have_attribute("title", PARTIAL_SOURCE)


def test_a_released_answer_says_it_will_be_written(page: Page, tmp_path: Path, monkeypatch) -> None:
    """And one held for its score alone says so: no check spoke, so the chip is the score."""
    answering(
        monkeypatch,
        lambda index, q: AnsweredQuestion(
            question=q, answer=ANSWER, confidence=0.45 if index == 1 else 0.9, needs_review=False
        ),
    )
    answered_on_the_workbench(page, tmp_path)

    released = page.locator("#results .answer").first
    expect(released.locator(".answer-status")).to_have_class("answer-status ready")
    expect(released.locator(".status-word")).to_have_text("Will be written")
    expect(released.locator(".reason-chip")).to_have_count(0)
    expect(released.locator(".status-score")).to_have_text("90% confidence")
    expect(released).not_to_have_class("answer review")

    low = page.locator("#results .answer").nth(1)
    expect(low.locator(".status-word")).to_have_text("Needs review")
    expect(low.locator(".reason-chip")).to_have_text(["Low confidence"])

    released.get_by_role("button", name="Approve", exact=True).click()
    approved = page.locator("#results .answer", has=page.get_by_role("button", name="Approved ✓"))
    expect(approved.locator(".status-word")).to_have_text("Done by a person")


def test_the_page_holds_by_the_servers_threshold(page: Page, monkeypatch: pytest.MonkeyPatch) -> None:
    """Typed questions go into no file, so the card judges them itself: with the server's threshold, not 0.6."""
    monkeypatch.setattr(settings, "review_confidence_threshold", 0.7)
    answering(
        monkeypatch,
        lambda index, q: AnsweredQuestion(
            question=q, answer=ANSWER, confidence=0.65 if "backups" in q.text else 0.75, needs_review=False
        ),
    )
    page.goto("/workbench")
    for text in ("Do you encrypt backups?", "Do you enforce MFA?"):
        page.click("#addQuestionBtn")
        page.get_by_role("textbox", name="Type a question").last.fill(text)
    choose_general(page)
    page.click("#answerBtn")

    under = page.locator("#results .answer", has_text="backups")
    expect(under.locator(".status-word")).to_have_text("Needs review", timeout=15_000)
    expect(under.locator(".reason-chip")).to_have_text(["Low confidence"])
    above = page.locator("#results .answer", has_text="MFA")
    expect(above.locator(".status-word")).to_have_text("Ready to use")
    assert page.evaluate("Cards.reviewThreshold") == 0.7


def test_the_chats_answer_cards_lead_with_their_status(
    page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The chat's answers pane draws the same card. An Arabic answer still reads right to left."""

    async def answer_one(question, language, *, run_id="", team_id=None):
        if "human resources process" in question.text:  # the sheet's first row
            return AnsweredQuestion(
                question=question, answer=ARABIC, confidence=0.9, needs_review=True, review_reasons=[UNGROUNDED]
            )
        return AnsweredQuestion(question=question, answer=ANSWER, confidence=0.9, needs_review=False)

    script = [("open_questionnaire", {"file_name": ""}), ("answer_questions", {})]
    monkeypatch.setattr(settings, "groq_api_key", "not-a-real-key")  # the model itself is scripted below
    monkeypatch.setattr(service, "answer_one_question", answer_one)
    monkeypatch.setattr(assistant, "_agent", lambda tools: _graph(script)(tools))

    page.goto("/")
    page.set_input_files("#fileInput", str(shapes.status_and_comment(tmp_path / "HR.xlsx")))
    page.fill("#prompt", "Answer it")
    page.select_option("#productPick", "general")
    page.click("#send")
    cards = page.locator("#answersPane .answer")
    expect(cards).to_have_count(4, timeout=30_000)
    expect(page.locator(".working")).to_have_count(0, timeout=30_000)
    assert page.evaluate("Cards.reviewThreshold") == settings.review_confidence_threshold

    held = cards.filter(has_text=ARABIC)
    expect(held.locator(":scope > :first-child")).to_have_class("answer-status review")
    expect(held.locator(".status-word")).to_have_text("Needs review")
    expect(held.locator(".reason-chip")).to_have_text(["Not backed by our documents"])
    expect(held).not_to_contain_text("High")
    expect(held.locator(".rendered")).to_have_attribute("dir", "rtl")

    released = cards.filter(has_text=ANSWER).first
    expect(released.locator(".status-word")).to_have_text("Will be written")


def test_the_status_bar_has_no_room_for_high(page: Page) -> None:
    """Whatever the score, the card no longer has a band word: none of the old ones is drawn."""
    page.goto("/workbench")
    words = page.evaluate(
        """() => [0.95, 0.7, 0.3].map((confidence) => Cards.render({
             question: { id: "1", text: "Q?", question_type: "free_text" }, answer: "A.",
             confidence, needs_review: true, review_reasons: [], citations: [],
           }, 0).textContent)"""
    )
    for text in words:
        assert "High" not in text and "Moderate" not in text and text.startswith("Needs review")
