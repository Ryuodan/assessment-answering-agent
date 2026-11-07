"""The chat's answers panel has the Workbench's review tabs (plan 037).

The panel listed every answer, in the file's order, with the set-aside ones at
its foot: finding the few a person has to look at meant reading all of them.
It now has the same five tabs as the Workbench, from the same code, counted
the same way, and opens on what needs a person after a turn that answered.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from src import service
from src.agents import assistant
from src.config import settings
from src.models import AnsweredQuestion
from tests import forms_fixtures as shapes
from tests.test_assistant import _graph

pytestmark = pytest.mark.browser

SURE = "Yes, it is documented and reviewed every year."


def answered_in_the_chat(page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, held: bool = True) -> None:
    """Four questions answered by the assistant: two confident, one flagged and one under the threshold."""

    async def answer_one(question, language, *, run_id="", team_id=None):
        if held and "awareness training" in question.text:
            return AnsweredQuestion(
                question=question,
                answer="Partly.",
                confidence=0.45,
                needs_review=True,
                review_reasons=["the sources disagree"],
            )
        if held and "background checks" in question.text:
            return AnsweredQuestion(question=question, answer="Probably.", confidence=0.30, needs_review=False)
        return AnsweredQuestion(question=question, answer=SURE, confidence=0.9, needs_review=False)

    monkeypatch.setattr(settings, "groq_api_key", "not-a-real-key")  # the model itself is scripted below
    monkeypatch.setattr(service, "answer_one_question", answer_one)
    script = [("open_questionnaire", {"file_name": ""}), ("answer_questions", {})]
    monkeypatch.setattr(assistant, "_agent", lambda tools: _graph(script)(tools))

    page.goto("/")
    page.set_input_files("#fileInput", str(shapes.status_and_comment(tmp_path / "HR.xlsx")))
    page.fill("#prompt", "Answer it")
    page.select_option("#productPick", "general")  # a new chat's first message waits for a choice (plan 029)
    page.click("#send")
    expect(page.locator("#answerTabs")).to_be_visible(timeout=30_000)
    expect(page.locator(".working")).to_have_count(0, timeout=30_000)  # the turn is over: nothing redraws the pane


def tab(page: Page, name: str):
    return page.locator("#answerTabs").get_by_role("button", name=re.compile("^" + re.escape(name) + " \\("))


def cards(page: Page):
    return page.locator("#answers .answer")


def test_the_panel_opens_on_what_needs_a_person_with_the_workbenchs_tabs(
    page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answered_in_the_chat(page, tmp_path, monkeypatch)

    expect(tab(page, "Needs review")).to_have_text("Needs review (2)")
    expect(tab(page, "Needs review")).to_have_attribute("aria-pressed", "true")
    expect(tab(page, "Will be written")).to_have_text("Will be written (2)")
    expect(tab(page, "Done by a person")).to_have_text("Done by a person (0)")
    expect(tab(page, "Blank or set aside")).to_have_text("Blank or set aside (0)")
    expect(tab(page, "All")).to_have_text("All (4)")
    expect(cards(page)).to_have_count(2)
    expect(cards(page).filter(has_text=SURE)).to_have_count(0)
    # The count above the tabs is the tab's: the one under the threshold is held too, unflagged.
    expect(page.locator("#answers .stat", has_text="need review").locator(".value")).to_have_text("2")

    tab(page, "Will be written").click()
    expect(cards(page)).to_have_count(2)
    expect(cards(page).filter(has_text=SURE)).to_have_count(2)
    tab(page, "All").click()
    expect(cards(page)).to_have_count(4)
    expect(tab(page, "All")).to_have_attribute("aria-pressed", "true")


def test_a_confident_questionnaire_opens_on_all(page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    answered_in_the_chat(page, tmp_path, monkeypatch, held=False)

    expect(tab(page, "All")).to_have_attribute("aria-pressed", "true")
    expect(tab(page, "Needs review")).to_have_text("Needs review (0)")
    expect(cards(page)).to_have_count(4)


def test_approving_moves_an_answer_and_the_tab_stays(
    page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answered_in_the_chat(page, tmp_path, monkeypatch)
    flagged = cards(page).filter(has_text="Partly.")

    flagged.get_by_role("button", name="Approve", exact=True).click()

    expect(tab(page, "Needs review")).to_have_text("Needs review (1)")
    expect(tab(page, "Done by a person")).to_have_text("Done by a person (1)")
    expect(tab(page, "Needs review")).to_have_attribute("aria-pressed", "true")  # the reviewer stays in the queue
    expect(flagged).to_have_count(0)
    expect(page.locator("#answersStatus")).to_contain_text("Approved")

    tab(page, "Done by a person").click()
    expect(cards(page)).to_have_count(1)
    expect(cards(page).first).to_contain_text("Partly.")


def test_a_set_aside_answer_is_under_blank_or_set_aside(
    page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answered_in_the_chat(page, tmp_path, monkeypatch)
    tab(page, "All").click()

    cards(page).filter(has_text="Probably.").get_by_role("button", name="Set aside", exact=True).click()

    expect(tab(page, "Blank or set aside")).to_have_text("Blank or set aside (1)")
    expect(tab(page, "Needs review")).to_have_text("Needs review (1)")
    expect(tab(page, "All")).to_have_attribute("aria-pressed", "true")
    tab(page, "Blank or set aside").click()
    expect(page.locator("#answers .aside-head")).to_contain_text("Set aside")
    expect(cards(page)).to_have_count(1)
    expect(cards(page).first).to_contain_text("Probably.")

    tab(page, "Done by a person").click()
    expect(page.locator("#answers .tab-empty")).to_have_text("No answers here. 1 need review, 2 will be written.")


def test_choosing_a_tab_from_the_keyboard_keeps_the_keyboards_place(
    page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answered_in_the_chat(page, tmp_path, monkeypatch)
    tab(page, "All").focus()

    page.keyboard.press("Enter")

    expect(tab(page, "All")).to_have_attribute("aria-pressed", "true")
    expect(tab(page, "All")).to_be_focused()
    expect(cards(page)).to_have_count(4)


def test_the_choice_is_kept_until_another_conversation(
    page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answered_in_the_chat(page, tmp_path, monkeypatch)
    tab(page, "All").click()

    page.reload()  # the conversation reopens: a fresh default, what needs a person
    page.locator("#historyList .convo").first.click()
    expect(tab(page, "Needs review")).to_have_attribute("aria-pressed", "true", timeout=15_000)
    expect(cards(page)).to_have_count(2)
