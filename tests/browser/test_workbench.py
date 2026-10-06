"""The workbench page (`/workbench`) in a real browser: signing in, reading and answering a questionnaire, the Access panel."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from src import access_codes, identity
from src.config import settings
from src.models import AnsweredQuestion
from tests import forms_fixtures as shapes

pytestmark = pytest.mark.browser

ALICE = "alice@example.test"
ADMIN = "admin@example.test"
CODE = "BROWSER-TEST-CODE"
ANSWER = "Yes, an approved policy is in place and reviewed annually."


@pytest.fixture
def answers_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(questions, language=None, run_id=None, **extra):
        return [AnsweredQuestion(question=q, answer=ANSWER, confidence=0.9, needs_review=False) for q in questions]

    monkeypatch.setattr("src.tools.service.answer_questions", fake)


def test_a_person_signs_in_with_the_team_code(page: Page) -> None:
    identity.ensure_team(settings.default_team)
    identity.set_access_code(settings.default_team, CODE)
    identity.add_user(ALICE)

    page.goto("/workbench")
    expect(page.locator("#authGate")).to_be_visible()
    page.fill("#authEmail", ALICE)
    page.fill("#authCode", CODE)
    page.click("#authSubmit")

    expect(page.locator("#authGate")).to_be_hidden()
    expect(page.locator("#whoamiEmail")).to_have_text(ALICE)
    expect(page.locator("#adminLink")).to_be_hidden()


def test_a_wrong_code_is_refused_on_the_page(page: Page) -> None:
    identity.ensure_team(settings.default_team)
    identity.set_access_code(settings.default_team, CODE)
    identity.add_user(ALICE)

    page.goto("/workbench")
    page.fill("#authEmail", ALICE)
    page.fill("#authCode", "NOT-THE-CODE")
    page.click("#authSubmit")

    expect(page.locator("#authError")).to_be_visible()
    expect(page.locator("#authGate")).to_be_visible()


def test_the_access_panel_shows_a_code_generated_at_startup(page: Page, monkeypatch: pytest.MonkeyPatch) -> None:
    """TD-029: the code generated on an upgrade is on the page for administrators, not in the log."""
    monkeypatch.setattr(settings, "admin_email", ADMIN)
    monkeypatch.setattr(settings, "admin_password", "browser-test-password")
    identity.bootstrap()  # what the next restart does
    generated = access_codes.waiting(settings.default_team)
    assert generated

    page.goto("/workbench")
    page.fill("#authEmail", ADMIN)
    page.fill("#authCode", "browser-test-password")
    page.click("#authSubmit")
    expect(page.locator("#adminLink")).to_be_visible()
    page.click("#adminLink")

    expect(page.get_by_text("Generated at startup:")).to_be_visible()
    expect(page.get_by_text(generated, exact=True)).to_be_visible()


def test_a_questionnaire_is_read_answered_and_shown_as_cards(page: Page, tmp_path: Path, answers_yes: None) -> None:
    workbook = shapes.simple(tmp_path / "vendor.xlsx")

    page.goto("/workbench")
    page.set_input_files("#assessmentInput", str(workbook))
    page.click("#extractBtn")
    # Each question is an editable box: the list can be corrected before anything is answered.
    listed = page.get_by_role("textbox", name="Type a question")
    expect(listed).to_have_count(4)
    expect(listed.first).to_have_value("Does the vendor have documented information security policies?")

    page.click("#answerBtn")
    expect(page.locator("#results").get_by_text(ANSWER).first).to_be_visible(timeout=15_000)
    expect(page.locator("#results").get_by_text(ANSWER)).to_have_count(4)


def test_a_file_name_is_shown_as_text_never_as_markup(page: Page) -> None:
    """TD-021: what the server says about a file reaches the status line as text."""
    name = '<img src=x onerror="window.__pwned=1">.txt'

    page.goto("/workbench")
    page.set_input_files("#assessmentInput", files=[{"name": name, "mimeType": "text/plain", "buffer": b"x"}])
    page.click("#extractBtn")

    status = page.locator("#extractStatus")
    expect(status).to_contain_text("not supported")
    expect(status).to_contain_text("<img")
    assert status.locator("img").count() == 0
    assert page.evaluate("window.__pwned") is None
