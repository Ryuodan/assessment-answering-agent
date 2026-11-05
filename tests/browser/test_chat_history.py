"""The chat page's history list in a real browser: forgetting a conversation (plan 029, 0.4).

Forget was a span inside the row's button: invalid nesting, out of the
keyboard's reach, and one click deleted the conversation for good, with no
question and no error handling.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from src import conversations, identity

pytestmark = pytest.mark.browser

KEPT = "Do you have a documented incident response plan?"
FORGOTTEN = "Do we encrypt backups?"


@pytest.fixture
def two_conversations() -> dict[str, str]:
    user = identity.local_user()
    return {title: conversations.create(user, title).id for title in (KEPT, FORGOTTEN)}


def row_of(page: Page, title: str):
    return page.locator("#historyList .convo-row", has=page.locator(".label", has_text=title))


def test_forgetting_a_conversation_asks_first_and_names_it(page: Page, two_conversations) -> None:
    asked: list[str] = []
    page.goto("/")
    expect(page.locator("#historyList .convo")).to_have_count(2)
    forget = row_of(page, FORGOTTEN).locator(".forget")

    page.once("dialog", lambda dialog: (asked.append(dialog.message), dialog.dismiss()))
    row_of(page, FORGOTTEN).hover()
    forget.click()
    expect(page.locator("#historyList .convo")).to_have_count(2)
    assert asked and f"Forget “{FORGOTTEN}”" in asked[0] and "cannot be recovered" in asked[0]
    assert conversations.load(two_conversations[FORGOTTEN]) is not None

    page.once("dialog", lambda dialog: dialog.accept())
    forget.click()
    expect(page.locator("#historyList .convo")).to_have_count(1)
    expect(page.locator("#historyList")).not_to_contain_text(FORGOTTEN)
    listed = page.evaluate("async () => (await (await fetch('/api/chat')).json()).conversations.map((c) => c.title)")
    assert listed == [KEPT]


def test_the_forget_control_is_a_button_of_its_own(page: Page, two_conversations) -> None:
    page.goto("/")
    expect(page.locator("#historyList .convo")).to_have_count(2)

    assert page.locator("#historyList button button").count() == 0, "a button inside a button"
    forget = row_of(page, FORGOTTEN).locator(".forget")
    assert forget.evaluate("el => el.tagName") == "BUTTON"
    expect(row_of(page, FORGOTTEN).get_by_role("button", name=f"Forget “{FORGOTTEN}”")).to_have_count(1)


def test_forget_can_be_reached_and_used_with_the_keyboard(page: Page, two_conversations) -> None:
    asked: list[str] = []
    page.goto("/")
    expect(page.locator("#historyList .convo")).to_have_count(2)
    page.mouse.move(0, 0)  # nothing hovered: only the keyboard shows it

    row_of(page, FORGOTTEN).locator(".convo").focus()
    page.keyboard.press("Tab")
    focused = page.evaluate("() => document.activeElement.getAttribute('aria-label')")
    assert focused == f"Forget “{FORGOTTEN}”"
    forget = row_of(page, FORGOTTEN).locator(".forget")
    assert forget.evaluate("el => getComputedStyle(el).opacity") == "1"

    page.once("dialog", lambda dialog: (asked.append(dialog.message), dialog.dismiss()))
    page.keyboard.press("Enter")
    expect(page.locator("#historyList .convo")).to_have_count(2)
    assert asked and FORGOTTEN in asked[0]
