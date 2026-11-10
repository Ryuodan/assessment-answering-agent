"""Acting on a card leaves the review where it was (plan 043).

Every approval draws the answers again. The chat's panel is its own scroller,
and when the conversation list had been given a width of its own, the redraw
measured the page while the panel was empty: the browser put the panel back at
its top, and the person had to find their place again before the next card.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Locator, Page, expect

from src import service
from src.agents import assistant
from src.config import settings
from src.models import AnsweredQuestion
from tests import forms_fixtures as shapes
from tests.browser.test_chat_review_tabs import cards
from tests.browser.test_chat_review_tabs import tab as chat_tab
from tests.browser.test_review_filter import answered, mixed, tab  # noqa: F401
from tests.test_assistant import _graph

pytestmark = pytest.mark.browser

LONG = "Yes. " + "The control is documented in the policy, approved by management and reviewed every year. " * 5


def long_questionnaire_in_the_chat(page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Twenty long answers, every other one held, so that the panel scrolls a long way."""

    async def answer_one(question, language, *, run_id="", team_id=None):
        held = int("".join(c for c in question.text if c.isdigit()) or 0) % 2 == 1
        return AnsweredQuestion(
            question=question,
            answer=LONG,
            confidence=0.45 if held else 0.9,
            needs_review=held,
            review_reasons=["the sources disagree"] if held else [],
        )

    monkeypatch.setattr(settings, "groq_api_key", "not-a-real-key")  # the model itself is scripted below
    monkeypatch.setattr(service, "answer_one_question", answer_one)
    script = [("open_questionnaire", {"file_name": ""}), ("answer_questions", {})]
    monkeypatch.setattr(assistant, "_agent", lambda tools: _graph(script)(tools))

    page.goto("/")
    page.set_input_files("#fileInput", str(shapes.numbered(tmp_path / "Long.xlsx", 20)))
    page.fill("#prompt", "Answer it")
    page.select_option("#productPick", "general")
    page.click("#send")
    expect(page.locator("#answerTabs")).to_be_visible(timeout=60_000)
    expect(page.locator(".working")).to_have_count(0, timeout=60_000)


def scrolled_to(panel: Locator, card: Locator) -> float:
    """The panel scrolled so that `card` is in view, a long way down."""
    card.get_by_role("button", name="Approve", exact=True).scroll_into_view_if_needed()
    panel.evaluate("p => { p.scrollTop += 40; }")
    return panel.evaluate("p => p.scrollTop")


@pytest.mark.parametrize("list_width", [None, "300"], ids=["list as drawn", "list given a width"])
def test_approving_in_the_chat_keeps_the_panels_place(
    page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, list_width: str | None
) -> None:
    if list_width:  # what dragging the list's edge leaves behind
        page.add_init_script(f"localStorage.setItem('assessment-history-width', '{list_width}')")
    long_questionnaire_in_the_chat(page, tmp_path, monkeypatch)
    chat_tab(page, "All").click()
    panel = page.locator("#answers")
    card = cards(page).nth(9)
    before = scrolled_to(panel, card)
    assert before > 1000, "far enough down that going back to the top shows"

    card.get_by_role("button", name="Approve", exact=True).click()

    expect(page.locator("#answersStatus")).to_contain_text("Approved")
    assert abs(panel.evaluate("p => p.scrollTop") - before) < 2


def test_in_needs_review_the_next_card_takes_the_approved_ones_place(
    page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page.add_init_script("localStorage.setItem('assessment-history-width', '300')")
    long_questionnaire_in_the_chat(page, tmp_path, monkeypatch)
    panel = page.locator("#answers")
    card = cards(page).nth(5)
    before = scrolled_to(panel, card)

    card.get_by_role("button", name="Approve", exact=True).click()

    expect(chat_tab(page, "Needs review")).to_have_text("Needs review (9)")
    assert abs(panel.evaluate("p => p.scrollTop") - before) < 2


def test_choosing_another_tab_starts_at_its_top(page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    long_questionnaire_in_the_chat(page, tmp_path, monkeypatch)
    chat_tab(page, "All").click()
    panel = page.locator("#answers")
    panel.evaluate("p => { p.scrollTop = p.scrollHeight; }")

    chat_tab(page, "Will be written").click()

    assert panel.evaluate("p => p.scrollTop") == 0


def test_approving_on_the_workbench_keeps_the_pages_place(page: Page, tmp_path: Path, mixed: None) -> None:  # noqa: F811
    page.set_viewport_size({"width": 1280, "height": 520})
    answered(page, shapes.simple(tmp_path / "vendor.xlsx"), 4)
    tab(page, "All").click()
    approve = page.locator("#results .answer", has_text="Probably.").get_by_role("button", name="Approve", exact=True)
    approve.scroll_into_view_if_needed()
    before = page.evaluate("() => window.scrollY")
    assert before > 100

    approve.click()

    expect(page.locator("#reviewStatus")).to_contain_text("Approved")
    assert abs(page.evaluate("() => window.scrollY") - before) < 2
