"""The preferences page, in a browser (TD-016: the one page tested only as a served file).

What a person sets here is saved, comes back after a reload, and is what the
server holds: the tone, the opening length, and the line they add.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from src import identity, preferences

pytestmark = pytest.mark.browser


def test_what_is_saved_comes_back_after_a_reload_and_is_what_the_server_holds(page: Page) -> None:
    page.goto("/preferences")
    page.locator("input[name=tone][value=formal]").check()
    page.locator("input[name=default_length][value=brief]").check()
    page.fill("#also", "Write “Not applicable”, never “N/A”.")
    page.click("#savePreferences")
    expect(page.locator("#preferencesStatus")).to_contain_text("Saved", timeout=10_000)

    page.reload()
    expect(page.locator("input[name=tone][value=formal]")).to_be_checked()
    expect(page.locator("input[name=default_length][value=brief]")).to_be_checked()
    expect(page.locator("#also")).to_have_value("Write “Not applicable”, never “N/A”.")

    held = preferences.load(identity.local_user().email)
    assert held.default_length == "brief"
    assert held.tone == "formal"


def test_the_page_says_what_the_choices_will_ask_for(page: Page) -> None:
    page.goto("/preferences")
    page.locator("input[name=tone][value=plain]").check()
    expect(page.locator("#asks")).not_to_contain_text("stay exactly as drafted")
