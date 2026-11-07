"""Saved lists, deleting a questionnaire and how long each is kept, on the Workbench (plan 033, phase 2).

Typed questions, and a PDF's or a Word text's, were answered on the page and
kept nowhere a page could read: a reload lost them. They are kept as a list
questionnaire (`POST /api/forms/list`), answered, reopened and listed like a
file's, with nothing to fill. Each questionnaire can be deleted, after a
question that names it; one being answered is refused, and the page says why.
"Or pick up" and the open questionnaire say until when each is kept unused, and
"Or pick up" labels each by when it was last used, which is its order.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from src import batches, busy, identity, retention, service, tools
from src.config import settings
from src.models import AnsweredQuestion, Question
from tests import forms_fixtures as shapes
from tests.browser.choosing import choose_general

pytestmark = pytest.mark.browser

TEAM = settings.default_team
ANSWER = "Yes, backups are encrypted with a key per tenant."


@pytest.fixture
def answers_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def answered(questions, language=None, run_id=None, **extra):
        return [AnsweredQuestion(question=q, answer=ANSWER, confidence=0.9, needs_review=False) for q in questions]

    monkeypatch.setattr("src.tools.service.answer_questions", answered)


def posts(page: Page) -> list[str]:
    """Every POST the page makes to the API, by path."""
    sent: list[str] = []
    page.on(
        "request",
        lambda request: (
            sent.append(request.url.split("/api/", 1)[1])
            if request.method == "POST" and "/api/" in request.url
            else None
        ),
    )
    return sent


def answered_as_a_list(page: Page, cards: int) -> None:
    page.click("#answerBtn")
    expect(page.locator("#results .answer")).to_have_count(cards, timeout=15_000)


def the_list_works_like_a_questionnaire(page: Page, name: str, cards: int) -> None:
    """In the address, reopened by it, its cards "Ready to use", and nothing to fill."""
    [kept] = batches.recent(TEAM)
    assert kept["format"] == "list"
    expect(page).to_have_url(re.compile(r"/workbench\?q=" + kept["id"] + "$"))
    words = page.locator("#results .answer .status-word")
    expect(words).to_have_text(["Ready to use"] * cards)
    expect(page.locator("#fillFormBtn")).to_be_hidden()
    expect(page.locator("#exportPdf")).to_be_visible()  # the downloads are the way out
    expect(page.locator("#step2")).to_be_hidden()  # nothing was read from a sheet to check

    page.reload()

    expect(page.locator("#extractStatus")).to_contain_text("Reopened " + name)
    expect(page.locator("#stepTitle")).to_have_text(name)
    expect(words).to_have_text(["Ready to use"] * cards)
    expect(page.locator("#formProduct")).to_be_disabled()  # its product is fixed, as a file's is
    expect(page.locator("#fillFormBtn")).to_be_hidden()

    page.click("#closeForm")
    expect(page.locator("#formRecent .recent-item", has_text=name)).to_contain_text("list")


# --- a list is a questionnaire --------------------------------------------------


def test_typed_questions_are_kept_as_a_list_that_reopens_and_is_answered_like_a_file(
    page: Page, answers_yes: None
) -> None:
    sent = posts(page)
    page.goto("/workbench")
    for text in ("Do you encrypt backups?", "Do you test your restores?"):
        page.click("#addQuestionBtn")
        page.get_by_role("textbox", name="Type a question").last.fill(text)
    choose_general(page)
    assert sent == [], "nothing is kept before Answer"

    answered_as_a_list(page, 2)

    [kept] = batches.recent(TEAM)
    assert sent[:2] == ["forms/list", f"forms/{kept['id']}/answer"]
    assert "assessments/answer-questions" not in sent
    loaded = batches.load(kept["id"])
    assert loaded and [q.text for q in loaded.form.questions] == [
        "Do you encrypt backups?",
        "Do you test your restores?",
    ]
    expect(page.locator("#stepTitle")).to_have_text("Typed questions")
    the_list_works_like_a_questionnaire(page, "Typed questions", 2)


def test_a_pdfs_questions_are_kept_as_a_list_the_same_way(
    page: Page, tmp_path: Path, answers_yes: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def text_of(path):
        return "1. Do you encrypt data at rest?\n2. How long are logs kept?"

    async def questions_in(text):
        return "en", [
            Question(id="1", text="Do you encrypt data at rest?"),
            Question(id="2", text="How long are logs kept?"),
        ]

    monkeypatch.setattr(service, "extracted_document_text", text_of)
    monkeypatch.setattr(service, "extract_questions", questions_in)
    pdf = tmp_path / "policy questions.pdf"
    pdf.write_bytes(b"%PDF-1.4 questions")
    sent = posts(page)

    page.goto("/workbench")
    choose_general(page)
    page.set_input_files("#assessmentInput", str(pdf))

    expect(page.locator("#extractStatus")).to_contain_text("Found 2 question(s) in policy questions.pdf")
    expect(page.locator("#extractStatus")).to_contain_text("downloaded instead")
    expect(page.get_by_role("textbox", name="Type a question")).to_have_count(2)
    assert sent == ["forms/list"], "read and kept in one request, not /api/assessments/extract"
    answered_as_a_list(page, 2)
    the_list_works_like_a_questionnaire(page, "policy questions.pdf", 2)


# --- deleting ---------------------------------------------------------------------


def two_questionnaires(tmp_path: Path):
    """vendor.xlsx, with one answer, and other.xlsx, with none; vendor.xlsx used last."""
    user = identity.local_user()
    other = tools.open_form(user, shapes.simple(tmp_path / "other.xlsx"))
    vendor = tools.open_form(user, shapes.simple(tmp_path / "vendor.xlsx"))
    tools.set_answer(user, vendor.id, vendor.form.questions[0].id, "We do.")
    return vendor, other


def test_deleting_from_pick_up_asks_first_naming_it_and_can_be_cancelled(page: Page, tmp_path: Path) -> None:
    vendor, other = two_questionnaires(tmp_path)
    page.goto("/workbench")
    row = page.locator("#formRecent .recent-item", has_text="vendor.xlsx")
    delete = row.get_by_role("button", name="Delete vendor.xlsx")
    expect(delete).to_have_text("Delete")  # in words, its own button, last in the row
    expect(row.locator("button").last).to_have_text("Delete")
    row.locator("button.pick-up").focus()
    page.keyboard.press("Tab")
    expect(delete).to_be_focused()  # reached from the keyboard

    asked: list[str] = []
    page.once("dialog", lambda dialog: (asked.append(dialog.message), dialog.dismiss()))
    delete.click()
    assert asked and "Delete “vendor.xlsx”?" in asked[0]
    assert "Its 1 answer goes with it" in asked[0] and "This cannot be undone." in asked[0]
    expect(row).to_be_visible()
    assert batches.load(vendor.id) is not None, "cancelled: nothing is deleted"

    page.once("dialog", lambda dialog: dialog.accept())
    delete.click()
    expect(page.locator("#extractStatus")).to_have_text("Deleted vendor.xlsx, with its 1 answer.")
    expect(row).to_have_count(0)
    expect(page.locator("#formRecent button.pick-up")).to_have_text([re.compile("other.xlsx")])
    assert batches.load(vendor.id) is None and batches.load(other.id) is not None


def test_deleting_the_open_questionnaire_goes_back_to_step_1_and_leaves_the_address(page: Page, tmp_path: Path) -> None:
    vendor, other = two_questionnaires(tmp_path)
    page.goto(f"/workbench?q={vendor.id}")
    expect(page.locator("#results .answer")).to_have_count(1)
    delete = page.locator("#deleteForm")
    expect(delete).to_have_text("Delete questionnaire")

    asked: list[str] = []
    page.once("dialog", lambda dialog: (asked.append(dialog.message), dialog.accept()))
    delete.click()

    assert asked and "Delete “vendor.xlsx”?" in asked[0] and "cannot be undone" in asked[0]
    expect(page).to_have_url(re.compile(r"/workbench$"))
    expect(page.locator("#extractStatus")).to_have_text("Deleted vendor.xlsx, with its 1 answer.")
    expect(page.locator("#stepList button[data-step='1']")).to_have_attribute("aria-current", "step")
    expect(page.locator("#step1Body")).to_be_visible()
    expect(page.locator("#resultsCard")).to_be_hidden()
    expect(delete).to_be_hidden()
    expect(page.locator("#closeForm")).to_be_hidden()
    expect(page.locator("#formProduct")).to_be_enabled()
    expect(page.locator("#formRecent button.pick-up")).to_have_text([re.compile("other.xlsx")])
    assert batches.load(vendor.id) is None


def test_a_questionnaire_being_answered_is_not_deleted_and_the_page_says_why(
    page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vendor, _ = two_questionnaires(tmp_path)
    monkeypatch.setitem(busy._HELD, vendor.id, busy._Hold(run_id="elsewhere", started_at="2026-11-07T09:00:00+00:00"))
    page.on("dialog", lambda dialog: dialog.accept())
    page.goto("/workbench")

    page.locator("#formRecent .recent-item", has_text="vendor.xlsx").get_by_role("button", name="Delete").click()
    said = page.locator("#extractStatus")
    expect(said).to_have_text(
        "vendor.xlsx was not deleted. This questionnaire is being answered right now. "
        "Wait until it finishes, then try again."
    )
    expect(said).to_have_class(re.compile(r"\berror\b"))
    expect(page.locator("#formRecent .recent-item", has_text="vendor.xlsx")).to_be_visible()

    page.goto(f"/workbench?q={vendor.id}")  # open, and being answered on the server
    expect(page.locator("#formReadOnly")).to_contain_text("Being answered on the server")
    page.click("#deleteForm")
    expect(said).to_contain_text("vendor.xlsx was not deleted. This questionnaire is being answered right now")
    expect(page).to_have_url(re.compile(r"\?q=" + vendor.id + "$"))
    assert batches.load(vendor.id) is not None


# --- how long each is kept, and when each was used ------------------------------------


def kept_until_as_said(page: Page, day: str) -> str:
    year, month, date = (int(part) for part in day.split("-"))
    return "Kept until " + page.evaluate(
        "([y, m, d]) => new Date(y, m - 1, d).toLocaleDateString(undefined,"
        " { day: 'numeric', month: 'long', year: 'numeric' })",
        [year, month, date],
    )


def test_kept_until_is_shown_on_pick_up_and_the_open_questionnaire_and_not_when_nothing_is_deleted(
    page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vendor = tools.open_form(identity.local_user(), shapes.simple(tmp_path / "vendor.xlsx"))
    [listed] = batches.recent(TEAM)
    day = retention.kept_until(listed["used_at"])
    assert day, "kept for RETENTION_DAYS (180) by default"

    page.goto("/workbench")
    said = kept_until_as_said(page, day)
    expect(page.locator("#formRecent .recent-item", has_text="vendor.xlsx").locator(".recent-kept")).to_have_text(said)

    page.locator("#formRecent button.pick-up", has_text="vendor.xlsx").click()
    expect(page.locator("#stepTitle")).to_have_text("vendor.xlsx")
    opened = retention.kept_until(batches.recent(TEAM)[0]["used_at"])  # opening is using it
    assert opened
    expect(page.locator("#keptUntil")).to_have_text(kept_until_as_said(page, opened))
    expect(page.locator("#keptUntil")).to_be_visible()

    monkeypatch.setattr(settings, "retention_days", 0)  # nothing is deleted: nothing is said
    page.goto(f"/workbench?q={vendor.id}")
    expect(page.locator("#stepTitle")).to_have_text("vendor.xlsx")
    expect(page.locator("#keptUntil")).to_be_hidden()
    page.click("#closeForm")
    expect(page.locator("#formRecent .recent-item", has_text="vendor.xlsx")).to_be_visible()
    expect(page.locator("#formRecent .recent-kept")).to_have_count(0)
    expect(page.locator("#formRecent")).not_to_contain_text("Kept until")


def test_pick_up_labels_each_by_when_it_was_last_used(
    page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sorted by use since plan 033, and labelled by what it was sorted by: "changed" said otherwise."""
    from datetime import datetime, timedelta, timezone
    from itertools import count

    user = identity.local_user()
    start, ticks = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc), count()
    with monkeypatch.context() as clocked:
        clocked.setattr(
            "src.batches.store.utcnow", lambda: (start + timedelta(hours=next(ticks))).isoformat(timespec="seconds")
        )
        older = tools.open_form(user, shapes.simple(tmp_path / "older.xlsx"))
        newer = tools.open_form(user, shapes.simple(tmp_path / "newer.xlsx"))
        tools.set_answer(user, newer.id, newer.form.questions[0].id, "We do.")  # changed later
        batches.touch(older.id)  # and the older one opened after that

    [first, second] = batches.recent(TEAM)
    assert (first["id"], second["id"]) == (older.id, newer.id), "most recently used first"
    assert first["updated_at"] < second["updated_at"], "though the other changed later"

    page.goto("/workbench")
    offered = page.locator("#formRecent button.pick-up")
    expect(offered).to_contain_text(["older.xlsx", "newer.xlsx"])
    for button, row in zip(offered.all(), (first, second), strict=True):
        shown = page.evaluate(
            "(iso) => new Date(iso).toLocaleString(undefined,"
            " { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })",
            row["used_at"],
        )
        expect(button.locator(".recent-when")).to_have_text("used " + shown)
        expect(button).to_have_attribute("title", re.compile("^Last used "))
