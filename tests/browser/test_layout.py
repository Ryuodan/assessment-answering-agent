"""The pages' layout at the widths people use, in a real browser (TD-041).

The chat page's header did not wrap: below about 1,000px the signed-in address
and Dark mode were cut off, with no way to scroll to them. And one long
conversation title took the history column from 250px to 500px. These check
what a person would see -- nothing cut off, no label broken over two lines, the
column at its width -- rather than pixel heights, which depend on the fonts.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from src import conversations, identity
from src.config import settings

pytestmark = pytest.mark.browser

CODE = "BROWSER-TEST-CODE"
# A long address without hyphens: the bar's widest likely occupant, and one
# that cannot break at a hyphen to make room.
EMAIL = "firstname.lastname.surname@example.test"
PAGES = ["/", "/workbench", "/memory", "/preferences", "/products"]

# Every visible control in the bar: its box, and whether its label may wrap.
MEASURE_THE_BAR = """() => {
  const width = document.documentElement.clientWidth;
  const shown = (el) => el.getClientRects().length > 0;
  const outside = [...document.querySelectorAll(".topbar > *, .topbar .whoami > *")]
    .filter(shown)
    .map((el) => ({ el, box: el.getBoundingClientRect() }))
    .filter(({ box }) => box.left < 0 || box.right > width + 0.5)
    .map(({ el, box }) => (el.id || el.textContent.trim()) + " at " + Math.round(box.left) + "-" + Math.round(box.right));
  const wrapping = [...document.querySelectorAll(".topbar .ghost, .topbar .whoami b")]
    .filter(shown)
    .filter((el) => getComputedStyle(el).whiteSpace !== "nowrap")
    .map((el) => el.id || el.textContent.trim());
  return { width, scrolls: document.documentElement.scrollWidth, outside, wrapping };
}"""


@pytest.fixture
def signed_in(page: Page) -> Page:
    identity.ensure_team(settings.default_team)
    identity.set_access_code(settings.default_team, CODE)
    identity.add_user(EMAIL)
    page.goto("/workbench")
    page.fill("#authEmail", EMAIL)
    page.fill("#authCode", CODE)
    page.click("#authSubmit")
    expect(page.locator("#authGate")).to_be_hidden()
    return page


@pytest.mark.parametrize("width", [1280, 900])
def test_every_header_fits_and_shows_who_is_signed_in(signed_in: Page, width: int) -> None:
    page = signed_in
    page.set_viewport_size({"width": width, "height": 800})
    for path in PAGES:
        page.goto(path)
        expect(page.locator("#whoamiEmail"), f"{path} at {width}px").to_have_text(EMAIL)
        expect(page.locator("#whoamiEmail"), f"{path} at {width}px").to_be_in_viewport(ratio=1)
        expect(page.locator("#signOut"), f"{path} at {width}px").to_be_in_viewport(ratio=1)
        expect(page.locator("#themeToggle"), f"{path} at {width}px").to_be_in_viewport(ratio=1)

        bar = page.evaluate(MEASURE_THE_BAR)
        assert bar["scrolls"] <= bar["width"], f"{path} at {width}px is wider than the window: {bar}"
        assert not bar["outside"], f"{path} at {width}px cuts off {bar['outside']}"
        assert not bar["wrapping"], f"{path} at {width}px lets these labels break: {bar['wrapping']}"


def test_the_chat_page_signs_out(signed_in: Page) -> None:
    page = signed_in
    page.goto("/")
    page.click("#signOut")
    expect(page.locator("#gate")).to_be_visible()
    expect(page.locator("#whoami")).to_be_hidden()


def test_a_long_conversation_title_does_not_widen_the_history(page: Page) -> None:
    long = "Do you have a documented incident response plan that is tested at least once a year with your vendors?"
    conversations.create(identity.local_user(), long)
    conversations.create(identity.local_user(), "Do we encrypt backups?")

    for width in (1280, 900, 768):
        page.set_viewport_size({"width": width, "height": 800})
        page.goto("/")
        expect(page.locator("#historyList .convo")).to_have_count(2)
        history = page.locator("#history").bounding_box()
        assert history and abs(history["width"] - 250) <= 1, f"at {width}px the history column is {history}"
        label = page.locator("#historyList .convo .label", has_text="incident response")
        cut = label.evaluate("el => el.scrollWidth > el.clientWidth")
        assert cut, f"at {width}px the long title is not cut short with an ellipsis"
        if width > 860:  # side by side, not floating over the conversation
            middle = page.locator(".middle").bounding_box()
            assert middle and middle["width"] >= width - 251, f"at {width}px the conversation is {middle}"


def test_the_product_chip_leaves_the_message_box_its_room(page: Page) -> None:
    """The chip sat in the box and was as wide as its longest option, "General (shared
    policies only)": a third of the box went to it, not to the message (the user's
    test of plan 029). It is on its own line above the box now."""
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto("/")
    expect(page.locator("#productPick option[value='general']")).to_have_count(1)
    chip, box, inner = page.locator("#productChip"), page.locator("#prompt"), page.locator(".composer-inner")

    for choice in ("", "general"):
        if choice:
            page.select_option("#productPick", choice)
        assert chip.bounding_box()["y"] + chip.bounding_box()["height"] <= inner.bounding_box()["y"], "above the box"
        assert box.bounding_box()["width"] >= inner.bounding_box()["width"] - 100, "the message has the box"
        assert chip.bounding_box()["width"] <= 280, f"the chip is {chip.bounding_box()['width']}px wide"
