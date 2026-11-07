"""Attaching a questionnaire on the Assistant page, in a real browser (plan 033).

The team did not find how to: the only control was a "＋" in the message box -- a
label for a hidden input, which no keyboard could reach -- and a file could be
dropped anywhere on the page with nothing to say so. Now there is a labelled
button beside the box, another in the empty chat, and a drop target while a file
is dragged over the page. A file of a kind the server would refuse is refused by
the box, by name, and a deleted product's chat offers none of it.

A file dragged from the desktop is played here as the events the browser fires
for one, carrying a `DataTransfer` with the file in it.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from playwright.sync_api import JSHandle, Page, expect

from src import conversations, identity, knowledge, products
from src.agents import assistant
from src.config import settings
from tests import forms_fixtures as shapes
from tests.conftest import FakeVectorStore, bare_store
from tests.test_assistant import _graph

pytestmark = pytest.mark.browser

TEAM = settings.default_team


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


def opened(page: Page) -> None:
    """The page, started: the products are listed, so every handler is in place."""
    page.goto("/")
    expect(page.locator("#productPick option[value='general']")).to_have_count(1)


def a_dragged_file(page: Page, name: str, content: bytes = b"not a real file") -> JSHandle:
    """What the browser hands the page while a file from the desktop is dragged over it.

    Chromium ignores `dropEffect` on a `DataTransfer` that no real drag made, so this one
    keeps what the page sets, and "" until it sets something: what the pointer shows over
    the page is the browser's default unless the page says otherwise."""
    return page.evaluate_handle(
        """([name, data]) => {
            const bytes = Uint8Array.from(atob(data), (c) => c.charCodeAt(0));
            const transfer = new DataTransfer();
            transfer.items.add(new File([bytes], name));
            let effect = "";
            Object.defineProperty(transfer, "dropEffect", { get: () => effect, set: (value) => { effect = value; } });
            return transfer;
        }""",
        [name, base64.b64encode(content).decode()],
    )


def drag(page: Page, event: str, selector: str, transfer: JSHandle) -> None:
    page.dispatch_event(selector, event, {"dataTransfer": transfer})


def test_the_labelled_button_beside_the_box_attaches_a_file_from_the_keyboard(page: Page, tmp_path: Path) -> None:
    page.set_viewport_size({"width": 1280, "height": 800})
    opened(page)
    button = page.locator(".composer-inner #attachBtn")
    expect(button).to_be_visible()
    expect(button).to_have_text("Attach a questionnaire", use_inner_text=True)
    expect(button).to_have_accessible_name("Attach a questionnaire")
    expect(button).to_have_accessible_description("XLSX, XLSM or DOCX")
    expect(page.locator("#attachTypes")).to_be_visible()

    # Beside the message, in the box, on the row with Send.
    inner, at, send = (page.locator(s).bounding_box() for s in (".composer-inner", "#attachBtn", "#send"))
    assert inner and at and send
    assert inner["x"] <= at["x"] and at["x"] + at["width"] < send["x"], (inner, at, send)
    assert inner["y"] <= at["y"] and at["y"] + at["height"] <= inner["y"] + inner["height"], (inner, at)
    assert abs((at["y"] + at["height"] / 2) - (send["y"] + send["height"] / 2)) <= 2, (at, send)

    # The next stop after the message, and Enter opens the file chooser. Listened for early:
    # Playwright turns interception on without waiting, and under a full run's load Enter
    # reached the page first and no chooser event came (flaky, 2 full runs in 3).
    page.on("filechooser", lambda chooser: None)
    page.focus("#prompt")
    page.keyboard.press("Tab")
    expect(button).to_be_focused()
    with page.expect_file_chooser() as chosen:
        page.keyboard.press("Enter")
    chosen.value.set_files(str(shapes.status_and_comment(tmp_path / "HR.xlsx")))
    expect(page.locator("#attached")).to_be_visible()
    expect(page.locator("#attachedName")).to_have_text("HR.xlsx")


def test_dragging_a_file_over_the_page_shows_where_to_drop_it_and_dropping_attaches_it(page: Page) -> None:
    opened(page)
    target = page.locator("#dropTarget")
    expect(target).to_be_hidden()
    transfer = a_dragged_file(page, "vendor.xlsx")

    drag(page, "dragenter", "#thread", transfer)
    drag(page, "dragover", "#thread", transfer)
    expect(target).to_be_visible()
    expect(target).to_contain_text("Drop the questionnaire to attach it")
    expect(target).to_contain_text("XLSX, XLSM or DOCX")
    assert transfer.evaluate("t => t.dropEffect") == "copy", "the pointer says the file will be copied in"

    # Into the box: the box is entered before the conversation is left, and the page is still under the file.
    drag(page, "dragenter", "#prompt", transfer)
    drag(page, "dragleave", "#thread", transfer)
    expect(target).to_be_visible()
    # Out of the window: the last element it was over is left.
    drag(page, "dragleave", "#prompt", transfer)
    expect(target).to_be_hidden()
    expect(page.locator("#attached")).to_be_hidden()  # a file that went away is not attached

    # Back, and dropped on the conversation.
    drag(page, "dragenter", "#thread", transfer)
    expect(target).to_be_visible()
    drag(page, "drop", "#thread", transfer)
    expect(target).to_be_hidden()
    expect(page.locator("#attached")).to_be_visible()
    expect(page.locator("#attachedName")).to_have_text("vendor.xlsx")

    # A second file says what it replaces, and does.
    second = a_dragged_file(page, "next.docx")
    drag(page, "dragenter", "#thread", second)
    expect(target).to_contain_text("In place of vendor.xlsx")
    drag(page, "drop", "#prompt", second)
    expect(page.locator("#attachedName")).to_have_text("next.docx")


def test_the_drop_target_goes_away_when_a_drag_ends_without_saying_so(page: Page) -> None:
    """The conversation is drawn again under a drag while a turn runs, and the element the
    file was over is taken off the page: it never says the drag left it."""
    opened(page)
    target = page.locator("#dropTarget")
    transfer = a_dragged_file(page, "vendor.xlsx")

    drag(page, "dragenter", "#thread", transfer)
    drag(page, "dragenter", "#starters button >> nth=0", transfer)
    page.evaluate("document.querySelector('#starters button').remove()")
    drag(page, "dragleave", "#thread", transfer)
    expect(target).to_be_hidden()

    drag(page, "dragenter", "#thread", transfer)
    expect(target).to_be_visible()
    page.dispatch_event("body", "dragend")
    expect(target).to_be_hidden()

    # A drag that ended where the page heard nothing of it: the next movement of the mouse.
    drag(page, "dragenter", "#thread", transfer)
    expect(target).to_be_visible()
    page.mouse.move(300, 300)
    page.mouse.move(320, 310)
    expect(target).to_be_hidden()
    expect(page.locator("#attached")).to_be_hidden()


def test_a_file_of_another_kind_is_refused_by_name_and_not_attached(page: Page, tmp_path: Path) -> None:
    opened(page)
    note = page.locator("#composerNote")
    pdf = a_dragged_file(page, "report.pdf")
    drag(page, "dragenter", "#thread", pdf)
    drag(page, "drop", "#thread", pdf)
    expect(page.locator("#dropTarget")).to_be_hidden()
    expect(page.locator("#attached")).to_be_hidden()
    expect(note).to_be_visible()
    expect(note).to_contain_text("“report.pdf” was not attached")
    expect(note).to_contain_text("XLSX, XLSM or DOCX")
    expect(note).to_contain_text("A PDF's questions can be read on the Workbench")

    # Chosen with "All files" in the browser's dialog: the same.
    notes = tmp_path / "notes.csv"
    notes.write_text("question,answer\n", encoding="utf-8")
    page.set_input_files("#fileInput", str(notes))
    expect(note).to_contain_text("“notes.csv” was not attached")
    expect(note).not_to_contain_text("PDF")
    expect(page.locator("#attached")).to_be_hidden()

    # A questionnaire, in capitals: attached, and the refusal is gone.
    upper = a_dragged_file(page, "VENDOR.XLSX")
    drag(page, "drop", "#thread", upper)
    expect(page.locator("#attachedName")).to_have_text("VENDOR.XLSX")
    expect(note).to_be_hidden()

    # Refused while another is attached: that one stays.
    drag(page, "drop", "#thread", pdf)
    expect(note).to_contain_text("“report.pdf” was not attached")
    expect(page.locator("#attachedName")).to_have_text("VENDOR.XLSX")


def test_a_dropped_questionnaire_goes_with_the_message(
    page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "groq_api_key", "not-a-real-key")  # the model itself is scripted below
    monkeypatch.setattr(assistant, "_agent", lambda tools, **named: _graph([])(tools))
    opened(page)
    content = shapes.status_and_comment(tmp_path / "HR.xlsx").read_bytes()
    transfer = a_dragged_file(page, "HR.xlsx", content)
    drag(page, "dragenter", "#thread", transfer)
    expect(page.locator("#dropTarget")).to_be_visible()
    drag(page, "drop", "#thread", transfer)
    expect(page.locator("#attachedName")).to_have_text("HR.xlsx")

    page.select_option("#productPick", "general")  # a new chat's first message waits for a product (plan 029)
    page.fill("#prompt", "What is in it?")
    with page.expect_request("**/api/chat/upload"):
        page.click("#send")
    expect(page.locator("#thread .turn.you .attachment")).to_contain_text("HR.xlsx")
    expect(page.locator("#thread .turn.assistant:not(.working)")).to_have_count(1)
    expect(page.locator("#attached")).to_be_hidden()

    [chat] = conversations.recent(TEAM)
    saved = conversations.load(chat["id"])
    assert saved is not None
    said = [m for m in saved.messages if isinstance(m, HumanMessage)]
    assert [assistant.uploaded_name(m) for m in said] == ["HR.xlsx"], "the server kept the file with the message"


def test_the_empty_chat_offers_to_attach_a_questionnaire_beside_the_starters(page: Page, tmp_path: Path) -> None:
    page.set_viewport_size({"width": 1280, "height": 800})
    opened(page)
    offer = page.locator("#empty #emptyAttach")
    expect(offer).to_be_visible()
    expect(offer).to_contain_text("drop it on this page")
    expect(offer).to_contain_text("XLSX, XLSM or DOCX")

    # Not crowding the starters: above them, apart, and every one of them still there.
    starters = page.locator("#starters button")
    expect(starters).to_have_count(6)
    area = offer.bounding_box()
    assert area
    for index in range(6):
        box = starters.nth(index).bounding_box()
        assert box and box["y"] >= area["y"] + area["height"] + 8, f"starter {index} at {box}, the offer at {area}"

    with page.expect_file_chooser() as chosen:
        offer.get_by_role("button", name="Attach a questionnaire").click()
    chosen.value.set_files(str(shapes.status_and_comment(tmp_path / "HR.xlsx")))
    expect(page.locator("#attachedName")).to_have_text("HR.xlsx")


def test_a_deleted_products_chat_offers_no_way_to_attach(page: Page, availo: products.Product) -> None:
    conversation = assistant.start(identity.local_user(), "Hello", availo.id)
    conversation.messages = [HumanMessage("Hello"), AIMessage("Hello again.")]
    conversations.save(conversation)
    products.delete(identity.local_user(), TEAM, availo.id, "confirm")

    opened(page)
    page.locator("#historyList .convo").click()
    expect(page.locator("#composerNote")).to_contain_text("Availo was deleted")
    attaching = re.compile("attach", re.IGNORECASE)
    expect(page.get_by_role("button", name=attaching).filter(visible=True)).to_have_count(0)
    expect(page.get_by_title(attaching).filter(visible=True)).to_have_count(0)

    transfer = a_dragged_file(page, "vendor.xlsx")
    drag(page, "dragenter", "#thread", transfer)
    drag(page, "dragover", "#thread", transfer)
    expect(page.locator("#dropTarget")).to_be_hidden()
    assert transfer.evaluate("t => t.dropEffect") == "none", "the pointer says it cannot go here"
    drag(page, "drop", "#thread", transfer)
    expect(page.locator("#attached")).to_be_hidden()
    expect(page.locator("#composerNote")).to_contain_text("This chat is kept so you can read it")

    page.click("#newChat")  # a new chat takes one again
    expect(page.locator("#attachBtn")).to_be_visible()
    expect(page.locator("#emptyAttach")).to_be_visible()


@pytest.mark.parametrize("width", [375, 560])
def test_on_a_narrow_screen_the_button_is_short_and_the_message_keeps_the_box(page: Page, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 740})
    opened(page)
    button = page.locator("#attachBtn")
    expect(button).to_be_visible()
    expect(button).to_have_text("Attach", use_inner_text=True)
    expect(button).to_have_accessible_name("Attach a questionnaire")
    expect(page.locator("#attachTypes")).to_be_hidden()

    inner, at, send, box = (
        page.locator(s).bounding_box() for s in (".composer-inner", "#attachBtn", "#send", "#prompt")
    )
    assert inner and at and send and box
    assert inner["x"] >= 0 and inner["x"] + inner["width"] <= width, f"the box runs off the screen: {inner}"
    assert box["width"] >= inner["width"] - 30, f"the message has {box['width']}px of the box's {inner['width']}px"
    assert at["height"] <= 36, f"the button's label is broken over lines: {at}"
    assert at["x"] + at["width"] < send["x"], (at, send)
    assert send["x"] + send["width"] <= inner["x"] + inner["width"], (send, inner)
