"""The Assistant page while a turn is running, and its panels, in a real browser (plan 031).

Moving to another conversation during a turn threw its working bubble away:
coming back showed neither the message sent nor its progress, the reply was
then drawn into whichever conversation was on screen -- its id and its answers
panel with it -- and nothing else could be sent until it came. Here a turn is
kept apart from the screen, and drawn where it belongs.

Also the page's other two changes in the plan: the "Documents" drawer is gone
(the Knowledge base page does that job), and the conversation list can be
resized by its edge, as the answers panel can.

The model is stubbed. A turn the test holds back waits, with a sentence for its
progress, until the test lets it go; then the real `assistant.say` runs, with an
agent that replies "Reply to: <what was asked>", and saves the conversation.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from playwright.sync_api import Page, expect

from src import batches, chat_running, conversations, identity, progress, tools
from src.agents import assistant
from src.config import settings
from tests import forms_fixtures as shapes

pytestmark = pytest.mark.browser

WORKING = "Reading the questions…"


class Echo:
    """The agent, stubbed: it replies to what it was asked, and does nothing else."""

    def __init__(self, tool_list: list) -> None:
        self.tools = tool_list

    async def astream(self, payload, config=None, stream_mode=None):
        messages = list(payload["messages"])
        messages.append(AIMessage(f"Reply to: {assistant.spoken(str(messages[-1].content))}"))
        yield {"messages": messages}


class Turns:
    """Turns the test holds back, by what was asked, until it lets them go."""

    def __init__(self) -> None:
        self.gates: dict[str, threading.Event] = {}
        self.changing: set[str] = set()

    def hold(self, message: str, *, changes_answers: bool = False) -> None:
        self.gates[message] = threading.Event()
        if changes_answers:
            self.changing.add(message)

    def release(self, message: str) -> None:
        self.gates[message].set()

    def release_all(self) -> None:
        for gate in self.gates.values():
            gate.set()


@pytest.fixture
def turns(monkeypatch: pytest.MonkeyPatch) -> Iterator[Turns]:
    held = Turns()
    real = assistant.say

    async def say(user, conversation, message, *, upload=None, run_id=""):
        gate = held.gates.get(message)
        if gate is not None:
            progress.start(run_id, stage=WORKING)  # what the page shows while the turn waits
            await asyncio.to_thread(gate.wait, 30)
        turn = await real(user, conversation, message, upload=upload, run_id=run_id)
        if message in held.changing:
            turn.refreshed = True  # as answering or rewording would: the reply carries the answers
        return turn

    monkeypatch.setattr(settings, "groq_api_key", "not-a-real-key")
    monkeypatch.setattr(chat_running, "_RUNNING", {})
    monkeypatch.setattr(assistant, "_agent", lambda tool_list, **named: Echo(tool_list))
    monkeypatch.setattr(assistant, "say", say)
    yield held
    held.release_all()  # no request left waiting when the server stops


def chat(title: str, reply: str, batch: batches.Batch | None = None) -> str:
    """A conversation with one exchange in it, and a questionnaire if given one."""
    conversation = assistant.start(identity.local_user(), title)
    conversation.messages = [HumanMessage(title), AIMessage(reply)]
    if batch is not None:
        conversation.batch_id = batch.id
    conversations.save(conversation)
    return conversation.id


def row_of(page: Page, title: str):
    return page.locator("#historyList .convo-row", has=page.locator(".label", has_text=title))


def said_by_you(page: Page):
    return page.locator("#thread .turn.you .bubble")


def reply_on_screen(page: Page):
    return page.locator("#thread .turn.assistant:not(.working) .bubble").last


def working(page: Page):
    return page.locator("#thread .turn.working")


def send(page: Page, message: str) -> None:
    page.fill("#prompt", message)
    page.click("#send")


def spoken_in(conversation_id: str) -> list[str]:
    saved = conversations.load(conversation_id)
    assert saved is not None
    return [str(m.content) for m in saved.messages]


# --- a turn, while the person moves about -------------------------------------------


def test_switching_away_mid_turn_and_back_shows_the_message_and_its_progress(page: Page, turns: Turns) -> None:
    chat("Do we log access?", "Yes, access is logged.")
    chat("Do we encrypt backups?", "Yes, with AES-256.")
    asked = "Answer the governance questions"
    turns.hold(asked)

    page.goto("/")
    row_of(page, "Do we log access?").locator(".convo").click()
    expect(page.locator("#thread")).to_contain_text("Yes, access is logged.")
    send(page, asked)
    expect(working(page)).to_contain_text(WORKING)

    row_of(page, "Do we encrypt backups?").locator(".convo").click()
    expect(page.locator("#thread")).to_contain_text("Yes, with AES-256.")
    expect(page.locator("#thread")).not_to_contain_text(asked)
    expect(working(page)).to_have_count(0)
    expect(page.locator("#prompt")).to_be_enabled()  # this conversation is not the one working
    expect(row_of(page, "Do we log access?").locator(".working-now")).to_have_text("Working…")

    row_of(page, "Do we log access?").locator(".convo").click()
    expect(page.locator("#thread")).to_contain_text("Yes, access is logged.")
    expect(said_by_you(page).last).to_have_text(asked)
    expect(working(page)).to_contain_text(WORKING)
    expect(page.locator("#prompt")).to_be_disabled()

    turns.release(asked)
    expect(reply_on_screen(page)).to_have_text(f"Reply to: {asked}", timeout=15_000)
    expect(working(page)).to_have_count(0)
    expect(said_by_you(page).filter(has_text=asked)).to_have_count(1)  # drawn once, not twice
    expect(page.locator("#prompt")).to_be_enabled()


def test_a_reply_lands_in_its_own_conversation_not_the_one_on_screen(page: Page, turns: Turns, tmp_path: Path) -> None:
    user = identity.local_user()
    on_screen = chat(
        "Open vendor.xlsx", "It has 4 questions.", tools.open_form(user, shapes.simple(tmp_path / "vendor.xlsx"))
    )
    running = chat(
        "Open other.xlsx", "It has 4 questions.", tools.open_form(user, shapes.simple(tmp_path / "other.xlsx"))
    )
    asked = "Reword them"
    turns.hold(asked, changes_answers=True)

    page.goto("/")
    row_of(page, "Open other.xlsx").locator(".convo").click()
    expect(page.locator("#answerTitle")).to_have_text("other.xlsx")
    send(page, asked)
    expect(working(page)).to_contain_text(WORKING)

    row_of(page, "Open vendor.xlsx").locator(".convo").click()
    expect(page.locator("#answerTitle")).to_have_text("vendor.xlsx")
    turns.release(asked)
    expect(row_of(page, "Open other.xlsx").locator(".new-reply")).to_have_text("New reply", timeout=15_000)

    # Nothing on screen moved: not the thread, not the answers beside it, not which chat is open.
    expect(page.locator("#thread")).not_to_contain_text(f"Reply to: {asked}")
    expect(page.locator("#thread")).to_contain_text("Open vendor.xlsx")
    expect(page.locator("#answerTitle")).to_have_text("vendor.xlsx")
    expect(row_of(page, "Open vendor.xlsx")).to_have_class(re.compile(r"\bon\b"))
    send(page, "And this one?")
    expect(reply_on_screen(page)).to_have_text("Reply to: And this one?")
    assert "And this one?" in spoken_in(on_screen)
    assert "And this one?" not in spoken_in(running), "the next message went to the conversation on screen"

    row_of(page, "Open other.xlsx").locator(".convo").click()
    expect(reply_on_screen(page)).to_have_text(f"Reply to: {asked}")
    expect(page.locator("#answerTitle")).to_have_text("other.xlsx")
    expect(row_of(page, "Open other.xlsx").locator(".new-reply")).to_have_count(0)  # read now


def test_a_new_chat_can_be_used_while_another_runs(page: Page, turns: Turns) -> None:
    chat("Do we log access?", "Yes, access is logged.")
    asked = "Answer everything"
    turns.hold(asked)

    page.goto("/")
    row_of(page, "Do we log access?").locator(".convo").click()
    send(page, asked)
    expect(working(page)).to_contain_text(WORKING)

    page.click("#newChat")
    expect(page.locator("#thread .turn")).to_have_count(0)
    expect(page.locator("#prompt")).to_be_enabled()
    page.select_option("#productPick", "general")
    send(page, "Do we encrypt backups?")
    expect(reply_on_screen(page)).to_have_text("Reply to: Do we encrypt backups?")
    expect(row_of(page, "Do we log access?").locator(".working-now")).to_be_visible()

    turns.release(asked)
    expect(row_of(page, "Do we log access?").locator(".new-reply")).to_be_visible(timeout=15_000)
    expect(page.locator("#thread")).not_to_contain_text(f"Reply to: {asked}")
    expect(reply_on_screen(page)).to_have_text("Reply to: Do we encrypt backups?")


def test_a_new_chats_first_turn_can_be_left_and_found_again(page: Page, turns: Turns) -> None:
    """Its id is not known when it is sent: the page finds it in the list by the run it named."""
    asked = "Do we have an incident response plan?"
    turns.hold(asked)

    page.goto("/")
    page.select_option("#productPick", "general")
    send(page, asked)
    expect(working(page)).to_contain_text(WORKING)
    row = row_of(page, asked)
    expect(row.locator(".working-now")).to_be_visible()
    expect(row).to_have_class(re.compile(r"\bon\b"))  # the chat on screen

    page.click("#newChat")
    pick = page.locator("#productPick")
    expect(page.locator("#thread .turn")).to_have_count(0)
    expect(pick).to_be_enabled()
    expect(pick).to_have_value("")  # chooses nothing (plan 029, 2)
    expect(page.locator("#chatLastUsed")).to_contain_text("Last used: General")

    row.locator(".convo").click()
    expect(said_by_you(page).last).to_have_text(asked)
    expect(working(page)).to_contain_text(WORKING)
    expect(pick).to_be_disabled()

    turns.release(asked)
    expect(reply_on_screen(page)).to_have_text(f"Reply to: {asked}", timeout=15_000)
    assert len(conversations.recent(identity.local_user().team_id)) == 1, "one chat, not two"


def test_after_a_reload_the_running_conversation_shows_its_message_and_then_its_reply(page: Page, turns: Turns) -> None:
    chat("Do we log access?", "Yes, access is logged.")
    asked = "Answer the governance questions"
    turns.hold(asked)

    page.goto("/")
    row_of(page, "Do we log access?").locator(".convo").click()
    send(page, asked)
    expect(working(page)).to_contain_text(WORKING)

    page.reload()
    row = row_of(page, "Do we log access?")
    expect(row.locator(".working-now")).to_be_visible()
    row.locator(".convo").click()
    expect(page.locator("#thread")).to_contain_text("Yes, access is logged.")
    expect(said_by_you(page).last).to_have_text(asked)
    expect(working(page)).to_contain_text(WORKING)
    expect(page.locator("#prompt")).to_be_disabled()

    turns.release(asked)
    expect(reply_on_screen(page)).to_have_text(f"Reply to: {asked}", timeout=15_000)
    expect(working(page)).to_have_count(0)
    expect(said_by_you(page).filter(has_text=asked)).to_have_count(1)
    expect(page.locator("#prompt")).to_be_enabled()


# --- the review of plan 031: the races it found ----------------------------------------


def until_caught(page: Page, caught: list, what: str) -> None:
    for _ in range(200):
        if caught:
            return
        page.wait_for_timeout(50)
    raise AssertionError(f"the page never asked for {what}")


def test_a_reply_that_arrives_while_its_conversation_is_opening_is_drawn(page: Page, turns: Turns) -> None:
    """The conversation was read while the turn ran, and the reply reached the page before
    that reading was drawn: the page knew the turn had ended, dropped the server's word that
    it was running, and drew neither the message nor its reply."""
    running = chat("Do we log access?", "Yes, access is logged.")
    chat("Do we encrypt backups?", "Yes, with AES-256.")
    asked = "Answer the governance questions"
    turns.hold(asked)
    page.goto("/")
    row_of(page, "Do we log access?").locator(".convo").click()
    send(page, asked)
    expect(working(page)).to_contain_text(WORKING)
    row_of(page, "Do we encrypt backups?").locator(".convo").click()
    expect(page.locator("#thread")).to_contain_text("Yes, with AES-256.")

    caught: list = []

    def answered_while_running(route) -> None:
        if caught:
            route.continue_()
            return
        caught.append((route, route.fetch()))  # read now, while the turn still runs; drawn later

    page.route(f"**/api/chat/{running}", answered_while_running)
    row_of(page, "Do we log access?").locator(".convo").click()
    until_caught(page, caught, "the conversation")
    turns.release(asked)
    expect(row_of(page, "Do we log access?").locator(".new-reply")).to_be_visible(
        timeout=15_000
    )  # the reply came first
    route, response = caught[0]
    route.fulfill(response=response)

    expect(reply_on_screen(page)).to_have_text(f"Reply to: {asked}")
    expect(said_by_you(page).filter(has_text=asked)).to_have_count(1)
    expect(working(page)).to_have_count(0)


def test_a_turn_ending_in_the_background_does_not_undo_a_click(page: Page, turns: Turns) -> None:
    """The redraw of the conversation on screen, when its turn ended, counted as the latest
    open: the conversation the person had just clicked was never drawn."""
    chat("Do we log access?", "Yes, access is logged.")
    clicked = chat("Do we encrypt backups?", "Yes, with AES-256.")
    asked = "Answer the governance questions"
    turns.hold(asked)
    page.goto("/")
    row_of(page, "Do we log access?").locator(".convo").click()
    send(page, asked)
    expect(working(page)).to_contain_text(WORKING)
    page.reload()
    row_of(page, "Do we log access?").locator(".convo").click()
    expect(working(page)).to_contain_text(WORKING)

    caught: list = []
    page.route(f"**/api/chat/{clicked}", lambda route: caught.append(route))  # its answer waits
    row_of(page, "Do we encrypt backups?").locator(".convo").click()
    until_caught(page, caught, "the conversation clicked")
    turns.release(asked)
    expect(row_of(page, "Do we log access?").locator(".working-now")).to_have_count(0, timeout=15_000)
    caught[0].continue_()

    expect(page.locator("#thread")).to_contain_text("Yes, with AES-256.")
    expect(page.locator("#thread")).not_to_contain_text(f"Reply to: {asked}")
    expect(row_of(page, "Do we encrypt backups?")).to_have_class(re.compile(r"\bon\b"))


def lose_the_reply(page: Page, server: str, *, and_the_next_list: bool = False) -> list:
    """The page's message reaches the server, which runs the turn; the page is told 504, as a
    proxy that gave up waiting would tell it. Optionally the list read after that is lost too."""
    lost: list = []

    def proxy(route) -> None:
        request = route.request
        if request.method == "GET" and lost and and_the_next_list and len(lost) == 1:
            lost.append("list")
            route.abort()
            return
        if request.method != "POST":
            route.continue_()
            return
        body = request.post_data or ""
        threading.Thread(
            target=lambda: httpx.post(
                server + "/api/chat", content=body, headers={"content-type": "application/json"}, timeout=60
            ),
            daemon=True,
        ).start()
        run_id = json.loads(body)["run_id"]
        for _ in range(200):
            if any(held["run_id"] == run_id for held in chat_running._RUNNING.values()):
                break
            time.sleep(0.05)
        lost.append(run_id)
        route.fulfill(status=504, body="Gateway Timeout", content_type="text/plain")

    page.route("**/api/chat", proxy)
    return lost


def test_a_turn_whose_reply_was_lost_on_the_way_is_followed_not_failed(page: Page, turns: Turns, server: str) -> None:
    """A proxy's timeout said "That did not work" while the turn carried on."""
    chat("Do we log access?", "Yes, access is logged.")
    asked = "Answer everything"
    turns.hold(asked)
    lose_the_reply(page, server)
    page.goto("/")
    row_of(page, "Do we log access?").locator(".convo").click()
    send(page, asked)

    expect(working(page)).to_contain_text(WORKING)
    page.wait_for_timeout(1500)  # well past the 504 and the check that follows it
    expect(page.locator("#thread")).not_to_contain_text("That did not work")
    expect(working(page)).to_contain_text(WORKING)
    expect(page.locator("#prompt")).to_be_disabled()

    turns.release(asked)
    expect(reply_on_screen(page)).to_have_text(f"Reply to: {asked}", timeout=15_000)
    expect(working(page)).to_have_count(0)
    expect(said_by_you(page).filter(has_text=asked)).to_have_count(1)
    expect(page.locator("#prompt")).to_be_enabled()


def test_a_turn_found_running_on_screen_is_drawn_and_the_box_says_why_it_waits(
    page: Page, turns: Turns, server: str
) -> None:
    """When even the check after the 504 was lost, the next list found the turn and the box
    went disabled mid-typing with nothing on screen saying why."""
    chat("Do we log access?", "Yes, access is logged.")
    asked = "Answer everything"
    turns.hold(asked)
    lost = lose_the_reply(page, server, and_the_next_list=True)
    page.goto("/")
    row_of(page, "Do we log access?").locator(".convo").click()
    send(page, asked)
    for _ in range(200):
        if "list" in lost:
            break
        page.wait_for_timeout(50)
    assert "list" in lost, "the check after the 504 was not lost, so this tested nothing"
    page.wait_for_timeout(1500)  # the failure drawn, and the list read after it

    expect(page.locator("#thread")).not_to_contain_text("That did not work")
    expect(working(page)).to_contain_text(WORKING)
    expect(said_by_you(page).filter(has_text=asked)).to_have_count(1)
    expect(page.locator("#prompt")).to_be_disabled()

    turns.release(asked)
    expect(reply_on_screen(page)).to_have_text(f"Reply to: {asked}", timeout=15_000)
    expect(page.locator("#prompt")).to_be_enabled()


def test_a_turn_running_off_screen_is_watched_through_the_list(page: Page, turns: Turns) -> None:
    """Every running conversation was read whole, answers and all, every 2.4 s, on screen or not."""
    running = chat("Do we log access?", "Yes, access is logged.")
    chat("Do we encrypt backups?", "Yes, with AES-256.")
    asked = "Answer the governance questions"
    turns.hold(asked)
    page.goto("/")
    row_of(page, "Do we log access?").locator(".convo").click()
    send(page, asked)
    expect(working(page)).to_contain_text(WORKING)
    page.reload()
    expect(row_of(page, "Do we log access?").locator(".working-now")).to_be_visible()

    read: list[str] = []
    page.on(
        "request", lambda request: read.append(request.url) if request.url.endswith(f"/api/chat/{running}") else None
    )
    row_of(page, "Do we encrypt backups?").locator(".convo").click()
    expect(page.locator("#thread")).to_contain_text("Yes, with AES-256.")
    page.wait_for_timeout(5500)  # two of the page's checks, and more
    assert read == [], f"the conversation off screen was read whole: {read}"

    turns.release(asked)
    expect(row_of(page, "Do we log access?").locator(".new-reply")).to_be_visible(timeout=15_000)
    assert read == [], "its end was learned from the list"
    row_of(page, "Do we log access?").locator(".convo").click()
    expect(reply_on_screen(page)).to_have_text(f"Reply to: {asked}")
    assert len(read) == 1, f"read once, to draw it: {read}"


def test_a_turn_already_in_the_transcript_is_not_drawn_twice(page: Page) -> None:
    """TD-075: the conversation is saved a moment before its turn is let go, and opening it
    then drew the person's message twice, once stored and once pending."""
    asked, at = "Do we log access?", "2026-11-06T09:00:00+00:00"
    conversation = assistant.start(identity.local_user(), asked)
    conversation.messages = [HumanMessage(asked, additional_kwargs={"at": at}), AIMessage("Yes, access is logged.")]
    conversations.save(conversation)
    told: list[bool] = []

    def still_running(route) -> None:
        response = route.fetch()
        body = response.json()
        if not told:  # once: the next reading is the server's own
            told.append(True)
            body["running"] = {"run_id": "saved-a-moment-ago", "message": asked, "file": "", "at": at}
        route.fulfill(response=response, json=body)

    page.route(f"**/api/chat/{conversation.id}", still_running)
    page.goto("/")
    page.locator("#historyList .convo").click()

    expect(page.locator("#thread")).to_contain_text("Yes, access is logged.")
    assert told, "the reading was not the one that says it is still running"
    # Counted as drawn, not waited for: the page reads the conversation again a few seconds
    # later, and that drawing would hide a duplicate drawn now. A pending turn is drawn with
    # the transcript, in the same moment.
    assert said_by_you(page).filter(has_text=asked).count() == 1, "the message drawn twice"
    assert working(page).count() == 0, "a working bubble for a turn the transcript holds"
    page.wait_for_timeout(3000)  # past the page's next check: still once, and nothing working
    expect(said_by_you(page).filter(has_text=asked)).to_have_count(1)
    expect(working(page)).to_have_count(0)


# --- the Documents drawer is gone ---------------------------------------------------


def test_the_chat_has_no_documents_drawer_and_still_opens_a_cited_document(page: Page) -> None:
    source = {
        "source_name": "Backup Policy.pdf",
        "source_type": "guideline",
        "locator": "Backup Policy.pdf §4.2",
        "snippet": "Backups shall be encrypted at rest.",
        "chunk": 0,
    }
    conversation = assistant.start(identity.local_user(), "Do we encrypt backups?")
    drawn = {"steps": ["search_policies('backups')"], "sources": [source], "at": "2026-11-01T09:00:00Z"}
    conversation.messages = [
        HumanMessage("Do we encrypt backups?"),
        AIMessage("Yes, at rest.", additional_kwargs={assistant.UI_KEY: drawn}),
    ]
    conversations.save(conversation)

    page.goto("/")
    expect(page.locator("#historyList .convo")).to_have_count(1)
    for gone in ("#openKb", "#kb", "#scrim", ".drawer", "#kbScope", "#guidelinesInput"):
        expect(page.locator(gone), gone).to_have_count(0)
    expect(page.locator(".topbar a.ghost", has_text="Knowledge base")).to_have_attribute("href", "knowledge")

    page.locator("#historyList .convo").click()
    reply = page.locator(".turn.assistant").last
    reply.locator(".sources > summary").click()
    reply.locator(".cite", has_text="Backup Policy.pdf §4.2").click()
    reply.get_by_role("button", name="open document").click()
    expect(page.locator("#viewer")).to_be_visible()
    expect(page.locator("#viewerTitle")).to_have_text("Backup Policy.pdf")
    frame = page.locator("#viewerFrame").get_attribute("src") or ""
    assert frame.endswith("/Backup%20Policy.pdf/preview"), frame
    page.click("#viewerClose")
    expect(page.locator("#viewer")).to_be_hidden()


# --- the conversation list's width ---------------------------------------------------


def width_of(page: Page, selector: str) -> float:
    box = page.locator(selector).bounding_box()
    assert box is not None, f"{selector} is not on the page"
    return box["width"]


def drag_the_edge(page: Page, by: float) -> None:
    handle = page.locator("#sideResizer").bounding_box()
    assert handle is not None
    x, y = handle["x"] + handle["width"] / 2, handle["y"] + 200
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + by, y, steps=6)
    page.mouse.up()


def test_the_conversation_list_is_resized_by_its_edge_and_keeps_its_width(page: Page) -> None:
    chat("Do we log access?", "Yes, access is logged.")
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto("/")
    expect(page.locator("#historyList .convo")).to_have_count(1)
    assert abs(width_of(page, "#history") - 250) <= 1

    drag_the_edge(page, 100)
    assert abs(width_of(page, "#history") - 350) <= 2
    page.reload()
    expect(page.locator("#historyList .convo")).to_have_count(1)
    assert abs(width_of(page, "#history") - 350) <= 2, "the width is remembered"

    page.locator("#sideResizer").dblclick()
    assert abs(width_of(page, "#history") - 250) <= 1
    page.reload()
    expect(page.locator("#historyList .convo")).to_have_count(1)
    assert abs(width_of(page, "#history") - 250) <= 1, "the reset is remembered too"

    page.locator("#sideResizer").focus()
    page.keyboard.press("ArrowRight")
    assert abs(width_of(page, "#history") - 270) <= 1
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("ArrowLeft")
    assert abs(width_of(page, "#history") - 230) <= 1
    expect(page.locator("#sideResizer")).to_have_attribute("aria-valuenow", "230")

    drag_the_edge(page, 600)
    assert abs(width_of(page, "#history") - 480) <= 1, "no wider than 480px"
    drag_the_edge(page, -600)
    assert abs(width_of(page, "#history") - 200) <= 1, "no narrower than 200px"

    page.click("#toggleHistory")
    expect(page.locator("#history")).to_be_hidden()
    expect(page.locator("#sideResizer")).to_be_hidden()
    page.click("#toggleHistory")
    expect(page.locator("#history")).to_be_visible()
    expect(page.locator("#sideResizer")).to_be_visible()
    assert abs(width_of(page, "#history") - 200) <= 1


def test_the_list_never_squeezes_the_conversation_beside_the_answers(page: Page, tmp_path: Path) -> None:
    batch = tools.open_form(identity.local_user(), shapes.simple(tmp_path / "vendor.xlsx"))
    chat("Open vendor.xlsx", "It has 4 questions.", batch)
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto("/")
    page.locator("#historyList .convo").click()
    expect(page.locator("#answersPane")).to_be_visible()

    drag_the_edge(page, 400)
    assert width_of(page, ".middle") >= 360 - 1, "the conversation keeps room for its box"
    assert width_of(page, "#history") < 480

    page.click("#closeAnswers")
    drag_the_edge(page, 450 - width_of(page, "#history"))
    assert abs(width_of(page, "#history") - 450) <= 2
    page.click("#toggleAnswers")  # the answers come back: the list gives way for now
    expect(page.locator("#answersPane")).to_be_visible()
    assert width_of(page, ".middle") >= 360 - 1
    assert width_of(page, "#history") < 450
    page.click("#closeAnswers")  # and takes the width it was given back
    assert abs(width_of(page, "#history") - 450) <= 2


def test_the_list_is_not_resizable_where_it_floats_over_the_conversation(page: Page) -> None:
    chat("Do we log access?", "Yes, access is logged.")
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto("/")
    expect(page.locator("#historyList .convo")).to_have_count(1)
    drag_the_edge(page, 150)
    assert abs(width_of(page, "#history") - 400) <= 2

    page.set_viewport_size({"width": 800, "height": 800})
    expect(page.locator("#sideResizer")).to_have_count(1)
    expect(page.locator("#sideResizer")).to_be_hidden()
    assert abs(width_of(page, "#history") - 250) <= 1, "over the conversation, at its own width"

    page.set_viewport_size({"width": 1280, "height": 800})
    expect(page.locator("#sideResizer")).to_be_visible()
    assert abs(width_of(page, "#history") - 400) <= 2, "beside it again, at the width chosen"


def test_right_to_left_the_list_widens_leftwards(page: Page) -> None:
    chat("Do we log access?", "Yes, access is logged.")
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto("/")
    expect(page.locator("#historyList .convo")).to_have_count(1)
    page.evaluate("document.documentElement.dir = 'rtl'")
    side = page.locator("#history").bounding_box()
    assert side is not None and side["x"] > 1000, "the list is on the right"

    drag_the_edge(page, -100)
    assert abs(width_of(page, "#history") - 350) <= 2
    page.locator("#sideResizer").focus()
    page.keyboard.press("ArrowLeft")
    assert abs(width_of(page, "#history") - 370) <= 2
