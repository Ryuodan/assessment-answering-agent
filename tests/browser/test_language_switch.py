"""The language switch in every page's top bar, and the person's choice followed (plan 038)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from src import identity, interface_language
from tests.browser.arabic import STORED, in_arabic

pytestmark = pytest.mark.browser

PAGES = {
    "/": "وكيل الإجابة عن الاستبيانات",
    "/workbench": "مساحة العمل — الإجابة عن الاستبيانات",
    "/knowledge": "قاعدة المعرفة — الإجابة عن الاستبيانات",
    "/memory": "ذاكرة الإجابات — الإجابة عن الاستبيانات",
    "/preferences": "التفضيلات — الإجابة عن الاستبيانات",
    "/products": "المنتجات — الإجابة عن الاستبيانات",
}


def chosen() -> str:
    return interface_language.get(identity.local_user().email)


@pytest.mark.parametrize("path", list(PAGES))
def test_every_page_has_the_switch_and_it_turns_the_page_arabic(page: Page, path: str) -> None:
    page.goto(path)
    expect(page.locator("html")).to_have_attribute("dir", "ltr")
    switch = page.locator(".topbar #languageToggle")
    expect(switch).to_have_text("العربية")

    switch.click()

    expect(page.locator("html")).to_have_attribute("dir", "rtl")
    expect(page.locator("html")).to_have_attribute("lang", "ar")
    expect(page.locator("#languageToggle")).to_have_text("English")
    expect(page).to_have_title(PAGES[path])
    assert page.evaluate(f"localStorage.getItem('{STORED}')") == "ar"
    assert chosen() == "ar", "kept with the person, not only on this device"


def test_english_back_from_arabic(page: Page) -> None:
    in_arabic(page)
    page.goto("/products")
    expect(page.locator("html")).to_have_attribute("dir", "rtl")

    page.locator("#languageToggle").click()

    expect(page.locator("html")).to_have_attribute("dir", "ltr")
    expect(page).to_have_title("Products — Assessment Answering")
    assert chosen() == "en"


def test_a_new_device_takes_the_persons_choice(page: Page) -> None:
    """This browser has never chosen: the session says Arabic, and the page is drawn again in it."""
    interface_language.choose(identity.local_user().email, "ar")

    page.goto("/knowledge")

    expect(page.locator("html")).to_have_attribute("dir", "rtl", timeout=10_000)
    expect(page.locator("#languageToggle")).to_have_text("English")


def test_the_devices_copy_gives_way_to_the_persons_choice(page: Page) -> None:
    """Arabic on this device, English chosen since on another: English."""
    in_arabic(page, person=False)
    page.goto("/memory")
    expect(page.locator("html")).to_have_attribute("dir", "ltr", timeout=10_000)
    assert page.evaluate(f"localStorage.getItem('{STORED}')") == "en"


def test_english_is_as_it_was(page: Page) -> None:
    """Nobody has chosen: English, left to right, and the pages' own words."""
    page.goto("/workbench")
    expect(page.locator("html")).to_have_attribute("lang", "en")
    expect(page).to_have_title("Workbench — Assessment Answering")
    expect(page.locator(".topbar a[href='./']")).to_have_text("Assistant")
