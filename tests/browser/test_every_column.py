"""Writing the answers to any column of the file, from the Workbench (plan 043).

A file whose answer column detection took for a status was filled with
statuses and no answers, and the Workbench offered only the columns detection
had chosen: there was no way to the right one, and a column set to "do not
write here" left the list. "Write to another column" lists them all.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests import forms_fixtures as shapes
from tests.browser.arabic import expect_arabic, in_arabic
from tests.browser.choosing import choose_general

pytestmark = pytest.mark.browser


def opened(page: Page, tmp_path: Path) -> None:
    page.goto("/workbench")
    choose_general(page)
    page.set_input_files("#assessmentInput", str(shapes.status_and_comment(tmp_path / "hr.xlsx")))
    expect(page.locator("#formColumns .every-column")).to_have_count(1)  # read, in either language
    if page.locator("#step2Body").is_hidden():
        page.click("#step2Toggle")


def every(page: Page):
    return page.locator("#formColumns .every-column")


def test_every_column_is_offered_with_its_heading(page: Page, tmp_path: Path) -> None:
    opened(page, tmp_path)
    expect(page.locator("#formColumns > .adm-add select")).to_have_count(2)  # where answers go now: C and D

    every(page).locator("summary").click()

    grid = every(page).locator(".column-grid")
    expect(grid).to_contain_text("column B — HR Security")
    expect(grid).to_contain_text("column D — Additional Comments")
    expect(grid).to_contain_text("column E")
    expect(grid).to_contain_text("the questions — never written")
    expect(grid.locator("select")).to_have_count(4)  # A, C, D and the blank E; never the questions
    expect(grid.get_by_label("column A")).to_have_value("ignore")
    expect(grid.get_by_label("column C")).to_have_value("status")


def test_the_answers_go_where_a_person_points_them_and_the_list_stays(page: Page, tmp_path: Path) -> None:
    opened(page, tmp_path)
    every(page).locator("summary").click()

    every(page).locator(".column-grid").get_by_label("column C").select_option("answer")

    expect(page.locator("#extractStatus")).to_have_text("Column C on Human Resources now holds answer.")
    expect(every(page)).to_have_attribute("open", "")  # still open, to choose the next one
    expect(page.locator("#formColumns > .adm-add")).to_contain_text("column C — Compliance Status")
    expect(page.locator("#formColumns > .adm-add select")).to_have_count(1)  # D gave the answers up
    expect(every(page).locator(".column-grid").get_by_label("column D")).to_have_value("ignore")  # and is still here

    every(page).locator(".column-grid").get_by_label("column D").select_option("evidence")

    expect(page.locator("#formColumns > .adm-add select")).to_have_count(2)
    expect(page.locator("#formColumns > .adm-add").get_by_label("column D")).to_have_value("evidence")


def test_it_reads_in_arabic(page: Page, tmp_path: Path) -> None:
    in_arabic(page)
    opened(page, tmp_path)

    every(page).locator("summary").click()

    expect(every(page).locator(".column-grid")).to_contain_text("الأسئلة — لا يُكتب فيه أبداً")
    expect(every(page).locator(".column-grid")).to_contain_text(
        "العمود D — Additional Comments"
    )  # the file's own words
    expect_arabic(page, "every column", within="#formColumns")


def test_on_a_phone_nothing_scrolls_sideways(page: Page, tmp_path: Path) -> None:
    page.set_viewport_size({"width": 375, "height": 800})
    opened(page, tmp_path)

    every(page).locator("summary").click()

    expect(every(page).locator(".column-grid select")).to_have_count(4)
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
