"""On a narrow screen the chat's conversation list can be closed, and starts closed (TD-076).

At 860 px wide and below the list is an overlay. It opened over the page when it
loaded and covered its own ☰ toggle, so at 375 px a phone user could not close it,
and it hid the left of the message box, Attach included.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from playwright.sync_api import Page, expect

from src import conversations, identity
from src.agents import assistant

pytestmark = pytest.mark.browser


def a_chat(title: str) -> None:
    conversation = assistant.start(identity.local_user(), title, "")
    conversation.messages = [HumanMessage(title), AIMessage("Hello again.")]
    conversations.save(conversation)


@pytest.fixture
def phone(page: Page) -> Page:
    page.set_viewport_size({"width": 375, "height": 740})
    a_chat("About backups")
    page.goto("/")
    expect(page.locator("#productPick option[value='general']")).to_have_count(1)
    return page


def test_on_a_phone_the_list_starts_closed_and_the_box_is_in_view(phone: Page) -> None:
    expect(phone.locator("#history")).to_be_hidden()
    expect(phone.locator("#attachBtn")).to_be_visible()
    expect(phone.locator("#toggleHistory")).to_be_visible()


def test_the_list_opens_from_its_toggle_and_closes_from_its_own_cross_or_escape(phone: Page) -> None:
    phone.click("#toggleHistory")
    expect(phone.locator("#history")).to_be_visible()
    expect(phone.locator("#closeHistory")).to_be_visible()
    phone.click("#closeHistory")
    expect(phone.locator("#history")).to_be_hidden()
    expect(phone.locator("#toggleHistory")).to_be_focused()

    phone.click("#toggleHistory")
    phone.keyboard.press("Escape")
    expect(phone.locator("#history")).to_be_hidden()


def test_choosing_a_conversation_closes_the_list_over_it(phone: Page) -> None:
    phone.click("#toggleHistory")
    phone.locator("#historyList .convo", has_text="About backups").click()
    expect(phone.locator("#history")).to_be_hidden()
    expect(phone.locator("#thread")).to_contain_text("Hello again.")


def test_on_a_wide_screen_the_list_stays_and_has_no_cross(page: Page) -> None:
    page.set_viewport_size({"width": 1280, "height": 800})
    a_chat("About backups")
    page.goto("/")
    expect(page.locator("#history")).to_be_visible()
    expect(page.locator("#closeHistory")).to_be_hidden()
    page.locator("#historyList .convo", has_text="About backups").click()
    expect(page.locator("#history")).to_be_visible(), "beside the page, choosing one leaves it open"
