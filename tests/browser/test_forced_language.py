""" "Force English" or "Force Arabic" reaches every question of a questionnaire (TD-077).

A spreadsheet's or Word form's own rows were answered in each question's own
language whatever "More options" said: the questionnaire's answer route took no
language. Plan 033 gave it one for lists; a file's rows now have it too.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from src.models import AnsweredQuestion
from tests import forms_fixtures as shapes
from tests.browser.choosing import choose_general

pytestmark = pytest.mark.browser


@pytest.fixture
def languages(monkeypatch: pytest.MonkeyPatch) -> list:
    asked: list = []

    async def answered(questions, language=None, run_id=None, **extra):
        asked.append(language)
        return [AnsweredQuestion(question=q, answer="Yes.", confidence=0.9, needs_review=False) for q in questions]

    monkeypatch.setattr("src.tools.service.answer_questions", answered)
    return asked


def test_a_spreadsheets_own_questions_are_answered_in_the_language_forced(
    page: Page, tmp_path: Path, languages: list
) -> None:
    page.goto("/workbench")
    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))
    choose_general(page)
    page.locator("#answerOptions summary").click()
    page.select_option("#languageSelect", "ar")
    expect(page.locator("#languageNote")).to_contain_text("every question in this questionnaire")
    page.click("#answerBtn")
    expect(page.locator("#results .answer")).to_have_count(4, timeout=15_000)
    assert languages == ["ar"], "the file's own rows, forced"


def test_left_as_it_is_each_question_keeps_its_own_language(page: Page, tmp_path: Path, languages: list) -> None:
    page.goto("/workbench")
    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))
    choose_general(page)
    page.click("#answerBtn")
    expect(page.locator("#results .answer")).to_have_count(4, timeout=15_000)
    assert languages == [None]
