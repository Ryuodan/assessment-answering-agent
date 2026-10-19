"""What the workbench says about a questionnaire it found no questions in, in a real browser (TD-043).

The reader returns its reason -- which sheets it read, and as what -- and the
page said only "Found 0 question(s)", in green.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from src import identity, service, tools
from src.config import settings
from tests import forms_fixtures as shapes

pytestmark = pytest.mark.browser


def test_a_questionnaire_with_no_questions_says_why(page: Page, tmp_path: Path) -> None:
    user = identity.local_user()
    notes = shapes.build(tmp_path / "notes.xlsx", [shapes.SheetSpec("Security", {"A1": "Security review notes"})])
    path = service.save_upload("notes.xlsx", notes.read_bytes(), settings.default_team, owner=user.email)
    batch = tools.open_form(user, path, strategy="rules")  # the rules alone: no model call
    assert not batch.form.questions and batch.form.warnings

    page.goto("/workbench")
    page.locator("#formRecent button", has_text="notes.xlsx").click()
    status = page.locator("#extractStatus")
    expect(status).to_contain_text("No questions were read from notes.xlsx")
    expect(status).to_contain_text(batch.form.warnings[0])
    expect(status).to_have_class("status error")


def test_a_spreadsheet_uploaded_with_no_questions_says_why_and_nothing_false(page: Page, tmp_path: Path) -> None:
    """The main path, not only "Or pick up". A spreadsheet has no text path to
    fall back to, and trying one opened the status with "'notes.xlsx' is not
    supported. Upload .pdf or .docx." above the reader's real reason."""
    notes = shapes.build(tmp_path / "notes.xlsx", [shapes.SheetSpec("Security", {"A1": "Security review notes"})])

    page.goto("/workbench")
    page.set_input_files("#assessmentInput", str(notes))
    page.click("#extractBtn")

    status = page.locator("#extractStatus")
    expect(status).to_contain_text("No questions were read from notes.xlsx")
    expect(status).to_contain_text("No questions were found. The sheets were read as")
    expect(status).not_to_contain_text("not supported")
    expect(status).to_have_class("status error")
    expect(page.locator("#formReport")).to_be_visible()  # what was found, to check
