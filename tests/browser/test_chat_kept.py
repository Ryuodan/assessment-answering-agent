"""The Assistant page's list and retention, in a real browser (plan 033).

Since plan 033 opening a conversation is using it: the list comes most recently
used first, and a conversation not opened for `RETENTION_DAYS` is deleted. So
each row is dated by when it was last used, which is the order it is in, and
says until when it is kept. Opening one moves it to the top of the list, which
must not take the keyboard away or leave the conversation out of sight.

A questionnaire can be deleted now, and its conversation is kept: it opens with
no answers, and says once that its questionnaire went, when the page can tell.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from playwright.sync_api import Page, expect

from src import batches, conversations, identity, knowledge, products, questionnaire, retention, store, tools
from src.agents import assistant
from src.config import settings
from tests import forms_fixtures as shapes
from tests.conftest import FakeVectorStore, bare_store

pytestmark = pytest.mark.browser

TEAM = settings.default_team
GONE = "This chat's questionnaire was deleted, with its answers. The conversation is kept."
WRITTEN = "Yes, every backup is encrypted."

# The page's own ways of writing a moment, so these hold in any locale.
CLOCK = "(s) => new Date(s).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })"
EXACT = "(s) => 'Last used ' + new Date(s).toLocaleString()"
DAY = """(s) => {
  const at = new Date(s);
  const sameYear = at.getFullYear() === new Date().getFullYear();
  return at.toLocaleDateString([], sameYear
    ? { day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short', year: 'numeric' });
}"""
CALENDAR_DAY = """(iso) => {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' });
}"""


@pytest.fixture
def availo(monkeypatch: pytest.MonkeyPatch) -> products.Product:
    made: dict[tuple[str, str], knowledge.KnowledgeStore] = {}

    def get_store(team_id=None, *, product_id=""):
        key = (team_id or TEAM, product_id)
        if key not in made:
            made[key] = bare_store(FakeVectorStore([]))
            # So deleting a product drops its fake collection rather than reaching Chroma.
            made[key]._store.delete_collection = lambda key=key: made.pop(key, None)
        return made[key]

    monkeypatch.setattr("src.knowledge.get_store", get_store)
    identity.ensure_team(TEAM)
    return products.add(None, TEAM, "Availo", color="#16a34a")


def chat(title: str, *, batch: batches.Batch | None = None, changed: bool = False, product_id: str = "") -> str:
    """A conversation with one exchange in it; `changed` when its reply changed the answers."""
    conversation = assistant.start(identity.local_user(), title, product_id)
    said = {assistant.UI_KEY: {"changed": True, "steps": ["open_questionnaire('vendor.xlsx')"]}} if changed else {}
    conversation.messages = [HumanMessage(title), AIMessage("All four answered.", additional_kwargs=said)]
    if batch is not None:
        conversation.batch_id = batch.id
    conversations.save(conversation)
    return conversation.id


def ago(**since: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(**since)).isoformat(timespec="seconds")


def last_said(conversation_id: str, stamp: str) -> None:
    """Last said in at `stamp`, and not opened since."""
    conn = store.connect()
    with conn:
        conn.execute(
            "UPDATE conversations SET updated_at = ?, used_at = '' WHERE conversation_id = ?", (stamp, conversation_id)
        )


def row_of(page: Page, title: str):
    return page.locator("#historyList .convo-row", has=page.locator(".label", has_text=title))


def a_questionnaire(tmp_path: Path, product_id: str = "") -> batches.Batch:
    user = identity.local_user()
    batch = tools.open_form(user, shapes.simple(tmp_path / "vendor.xlsx"), product_id=product_id)
    question = next(q for q in batch.form.questions if q.writable)
    tools.set_answer(user, batch.id, question.id, WRITTEN)
    return batch


# --- 1. dated by when it was last used --------------------------------------------------


def test_each_row_is_dated_by_when_it_was_last_used_which_is_its_order(page: Page) -> None:
    talked = chat("Do we log access?")
    opened = chat("Do we encrypt backups?")
    last_said(talked, ago(days=20))
    last_said(opened, ago(days=60))
    conversations.touch(opened)  # opened today, on another computer
    used = {row["id"]: row["used_at"] for row in conversations.recent(TEAM)}

    page.goto("/")
    rows = page.locator("#historyList .convo")
    expect(rows).to_have_count(2)
    expect(rows.nth(0).locator(".label")).to_have_text("Do we encrypt backups?")
    expect(rows.nth(0).locator(".when")).to_have_text(page.evaluate(CLOCK, used[opened]))
    expect(rows.nth(0).locator(".when")).to_have_attribute(
        "title", re.compile("^" + re.escape(page.evaluate(EXACT, used[opened])))
    )
    expect(rows.nth(1).locator(".label")).to_have_text("Do we log access?")
    expect(rows.nth(1).locator(".when")).to_have_text(page.evaluate(DAY, used[talked]))


# --- 2. until when it is kept ------------------------------------------------------------


def test_each_row_says_until_when_it_is_kept_and_nothing_when_nothing_is_deleted(
    page: Page, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat("Do we log access?")
    [listed] = conversations.recent(TEAM)
    until = retention.kept_until(listed["used_at"])
    assert until

    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto("/")
    day = page.evaluate(CALENDAR_DAY, until)
    kept = page.locator("#historyList .convo .kept")
    expect(kept).to_have_text("Kept until " + day)
    expect(kept).to_have_attribute("title", re.compile("^Kept until " + re.escape(day)))
    expect(page.locator("#historyList .convo .when")).to_have_attribute(
        "title", re.compile(re.escape(" · Kept until " + day) + "$")
    )
    # One quiet line inside the row, not crowding it.
    line, row = kept.bounding_box(), page.locator("#historyList .convo").bounding_box()
    assert line and row
    assert line["height"] <= 20, f"the line wraps: {line}"
    assert line["x"] + line["width"] <= row["x"] + row["width"], (line, row)
    assert kept.evaluate("el => parseFloat(getComputedStyle(el).fontSize)") < page.locator(
        "#historyList .convo .label"
    ).evaluate("el => parseFloat(getComputedStyle(el).fontSize)"), "quieter than the title"

    monkeypatch.setattr(settings, "retention_days", 0)  # RETENTION_DAYS=0 keeps everything
    page.reload()
    expect(page.locator("#historyList .convo")).to_have_count(1)
    expect(page.locator("#historyList .convo .kept")).to_have_count(0)
    expect(page.locator("#historyList .convo .when")).not_to_have_attribute("title", re.compile("Kept"))


# --- 3. a questionnaire deleted since ----------------------------------------------------


def test_a_chat_whose_questionnaire_was_deleted_opens_without_answers_and_says_so(page: Page, tmp_path: Path) -> None:
    batch = a_questionnaire(tmp_path)
    chat("Answer the vendor file", batch=batch, changed=True)
    chat("Do we encrypt backups?")  # never had one
    questionnaire.delete(identity.local_user(), batch.id)

    page.goto("/")
    row_of(page, "Answer the vendor file").locator(".convo").click()
    expect(page.locator("#thread .turn")).to_have_count(2)
    note = page.locator("#composerNote")
    expect(note).to_have_text(GONE)
    expect(note).to_have_class("status calm composer-note")
    expect(page.locator("#answersPane")).to_be_hidden()
    expect(page.locator("#toggleAnswers")).to_be_hidden()
    expect(page.get_by_role("button", name="Show the answers →")).to_have_count(0)
    expect(page.locator("#prompt")).to_be_enabled()  # it can be carried on

    row_of(page, "Do we encrypt backups?").locator(".convo").click()
    expect(page.locator("#thread .turn.you .bubble")).to_have_text("Do we encrypt backups?")
    expect(note).to_be_hidden()  # one that never had a questionnaire says nothing about one

    row_of(page, "Answer the vendor file").locator(".convo").click()
    expect(note).to_have_text(GONE)  # said again each time it is opened


def test_a_deleted_products_chat_says_its_questionnaire_went_too(
    page: Page, tmp_path: Path, availo: products.Product
) -> None:
    batch = a_questionnaire(tmp_path, availo.id)
    chat("Answer the vendor file", batch=batch, changed=True, product_id=availo.id)
    products.delete(identity.local_user(), TEAM, availo.id, "confirm")
    questionnaire.delete(identity.local_user(), batch.id)

    page.goto("/")
    page.locator("#historyList .convo").click()
    note = page.locator("#composerNote")
    expect(note).to_have_text(
        "Availo was deleted. This chat is kept so you can read it; start a new chat to carry on. "
        "Its questionnaire was deleted too, with its answers."
    )
    expect(note).to_have_class("status calm composer-note")
    expect(page.locator("#answersPane")).to_be_hidden()
    expect(page.locator("#prompt")).to_be_disabled()


def test_answers_deleted_while_the_chat_is_open_go_when_the_person_comes_back(page: Page, tmp_path: Path) -> None:
    """No reply in it says it changed the answers: only this page saw it with a questionnaire."""
    batch = a_questionnaire(tmp_path)
    chat("Answer the vendor file", batch=batch)

    page.goto("/")
    page.locator("#historyList .convo").click()
    expect(page.locator("#answersPane .answer", has_text=WRITTEN)).to_be_visible()
    questionnaire.delete(identity.local_user(), batch.id)  # on the Workbench, in another tab
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")  # the person comes back to this one

    note = page.locator("#composerNote")
    expect(page.locator("#answersPane")).to_be_hidden()
    expect(page.locator("#toggleAnswers")).to_be_hidden()
    expect(note).to_have_text(GONE)
    expect(page.locator("#thread .turn")).to_have_count(2)

    page.click("#newChat")
    page.locator("#historyList .convo").click()
    expect(note).to_have_text(GONE)  # this page saw it with one

    # Read afresh, nothing tells it from a chat that never had a questionnaire: nothing is said.
    page.reload()
    page.locator("#historyList .convo").click()
    expect(page.locator("#thread .turn")).to_have_count(2)
    expect(page.locator("#answersPane")).to_be_hidden()
    expect(note).to_be_hidden()


def test_answers_put_away_and_deleted_since_are_not_shown_again(page: Page, tmp_path: Path) -> None:
    batch = a_questionnaire(tmp_path)
    chat("Answer the vendor file", batch=batch)

    page.goto("/")
    page.locator("#historyList .convo").click()
    expect(page.locator("#answersPane .answer", has_text=WRITTEN)).to_be_visible()
    page.click("#closeAnswers")
    expect(page.locator("#toggleAnswers")).to_be_visible()
    questionnaire.delete(identity.local_user(), batch.id)

    page.click("#toggleAnswers")
    expect(page.locator("#composerNote")).to_have_text(GONE)
    expect(page.locator("#answersPane")).to_be_hidden()
    expect(page.locator("#toggleAnswers")).to_be_hidden()


# --- 4. opening one moves it to the top -------------------------------------------------


@pytest.fixture
def a_long_list(page: Page) -> Page:
    """Twenty-four conversations, the newest first, in a window that shows a third of them."""
    for n in range(24):
        last_said(chat(f"Question number {n:02d}"), ago(minutes=n + 1))
    page.set_viewport_size({"width": 1280, "height": 560})
    page.goto("/")
    expect(page.locator("#historyList .convo")).to_have_count(24)
    expect(page.locator("#historyList .convo").first).to_have_text(re.compile("Question number 00"))
    return page


def test_opened_from_the_keyboard_it_moves_to_the_top_and_the_keyboard_goes_with_it(a_long_list: Page) -> None:
    page = a_long_list
    target = row_of(page, "Question number 18").locator(".convo")
    target.focus()  # the keyboard went down the list
    page.keyboard.press("Enter")

    first = page.locator("#historyList .convo-row").first
    expect(first.locator(".label")).to_have_text("Question number 18")
    expect(first.locator(".convo")).to_have_class(re.compile(r"\bon\b"))
    expect(first.locator(".convo")).to_be_focused()
    expect(first.locator(".convo")).to_be_in_viewport()
    page.keyboard.press("Tab")  # and on from there: its ✕, then the next one down
    expect(first.locator(".forget")).to_be_focused()
    page.keyboard.press("Tab")
    expect(page.locator("#historyList .convo-row").nth(1).locator(".convo")).to_be_focused()


def test_opened_without_the_keyboard_in_the_list_it_stays_in_sight(a_long_list: Page) -> None:
    """A click that leaves the keyboard where it was, as Safari's does: the list stayed
    scrolled where it was, and the conversation went to the top, out of sight."""
    page = a_long_list
    target = row_of(page, "Question number 18").locator(".convo")
    target.scroll_into_view_if_needed()
    assert page.locator("#historyList").evaluate("el => el.scrollTop") > 0, "the list is scrolled down"
    target.dispatch_event("click")

    opened = page.locator("#historyList .convo-row.on")
    expect(opened.locator(".label")).to_have_text("Question number 18")
    expect(page.locator("#historyList .convo-row").first).to_have_class(re.compile(r"\bon\b"))
    expect(opened).to_be_in_viewport()
