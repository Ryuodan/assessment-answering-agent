"""The pages' language and look, chosen in Preferences, and the person's choice followed (plans 038 and 040)."""

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
def test_the_top_bar_has_no_language_or_theme_button(page: Page, path: str) -> None:
    page.goto(path)
    expect(page.locator(".topbar a").first).to_be_visible()
    expect(page.locator("#languageToggle")).to_have_count(0)
    expect(page.locator("#themeToggle")).to_have_count(0)


def test_arabic_chosen_in_preferences_reaches_every_page(page: Page) -> None:
    page.goto("/preferences")
    page.locator("#languagePanel").get_by_text("العربية").click()
    expect(page.locator("html")).to_have_attribute("dir", "rtl")
    assert page.evaluate(f"localStorage.getItem('{STORED}')") == "ar"
    assert chosen() == "ar", "kept with the person, not only on this device"

    for path, title in PAGES.items():
        page.goto(path)
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        expect(page.locator("html")).to_have_attribute("lang", "ar")
        expect(page).to_have_title(title)


def test_the_appearance_is_chosen_in_preferences_and_kept_on_every_page(page: Page) -> None:
    page.emulate_media(color_scheme="light")
    page.goto("/preferences")
    panel = page.locator("#languagePanel")
    expect(page.locator("input[name=theme][value=light]")).to_be_checked()

    panel.get_by_text("Dark mode").click()

    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    expect(page.locator("input[name=theme][value=dark]")).to_be_checked()
    expect(page.locator("#preferencesStatus")).not_to_have_text("Not saved yet.")  # not one of the answer preferences

    for path in PAGES:
        page.goto(path)
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")

    page.goto("/preferences")
    expect(page.locator("input[name=theme][value=dark]")).to_be_checked()
    panel.get_by_text("Light mode").click()
    expect(page.locator("html")).to_have_attribute("data-theme", "light")


def test_a_new_device_takes_the_persons_choice(page: Page) -> None:
    """This browser has never chosen: the session says Arabic, and the page is drawn again in it."""
    interface_language.choose(identity.local_user().email, "ar")

    page.goto("/knowledge")

    expect(page.locator("html")).to_have_attribute("dir", "rtl", timeout=10_000)


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
