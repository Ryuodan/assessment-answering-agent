"""One chat turn at a time in a conversation, and what a page needs to draw it again (plan 031).

A turn runs inside its request and is saved only when it ends. A page that
opened another conversation, or was reloaded, showed neither the message that
had been sent nor its progress, and nothing stopped a second message, or
Forget, while the first was still being answered. The routes now hold the
conversation for the length of the turn, and say so.

The model is never called: `assistant.say` is stubbed with a turn that waits
until the test lets it finish. Without a `with` block a `TestClient` serves
each request on its own event loop, so a request sent from another thread is
served while the turn waits.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src import chat_running, conversations, identity
from src.agents import assistant
from src.api import app
from src.config import settings
from src.errors import Conflict
from tests import forms_fixtures as shapes


@pytest.fixture(autouse=True)
def nothing_running(monkeypatch: pytest.MonkeyPatch) -> None:
    """In memory, so per test: a turn a failed test left held cannot refuse the next test's."""
    monkeypatch.setattr(chat_running, "_RUNNING", {})


# --- the registry ---------------------------------------------------------------------


def test_a_second_turn_in_the_same_conversation_is_refused() -> None:
    with chat_running.hold("c1", run_id="run-1", message="Answer everything"):
        with pytest.raises(Conflict) as refused:
            with chat_running.hold("c1", run_id="run-2", message="And again"):
                pass
        assert chat_running.running("c1")["run_id"] == "run-1", "the refused turn took nothing over"

    assert (refused.value.status, refused.value.code) == (409, "conversation_busy")
    assert "still working on your last message" in refused.value.message


def test_what_is_held_is_what_a_page_draws_again() -> None:
    with chat_running.hold("c1", run_id="run-1", message="Read HR.xlsx", file="HR.xlsx"):
        held = chat_running.running("c1")

    assert held is not None
    assert {key: held[key] for key in ("run_id", "message", "file")} == {
        "run_id": "run-1",
        "message": "Read HR.xlsx",
        "file": "HR.xlsx",
    }
    assert held["at"].endswith("+00:00"), "when it was sent, in UTC, as the transcript's stamps are"
    assert chat_running.running("c1") is None


def test_a_turn_that_fails_lets_its_conversation_go() -> None:
    with pytest.raises(RuntimeError):
        with chat_running.hold("c1", run_id="run-1", message="hello"):
            raise RuntimeError("the model fell over")

    assert chat_running.running("c1") is None
    chat_running.refuse("c1")
    with chat_running.hold("c1", run_id="run-2", message="hello again"):
        pass


def test_another_conversation_is_free() -> None:
    with chat_running.hold("c1", run_id="run-1", message="hello"):
        chat_running.refuse("c2")
        with chat_running.hold("c2", run_id="run-2", message="hello"):
            assert chat_running.running("c2")["run_id"] == "run-2"
        with pytest.raises(Conflict):
            chat_running.refuse("c1")


# --- the routes ---------------------------------------------------------------------


class Turns:
    """`assistant.say`, stubbed. A turn held back by its run id, or by what was said, waits until the test lets it go."""

    def __init__(self) -> None:
        self.gates: dict[str, threading.Event] = {}
        self.said: list[tuple[str, str, str]] = []
        self.run_ids: list[str] = []

    def hold_back(self, run_id_or_message: str) -> None:
        self.gates[run_id_or_message] = threading.Event()

    def let_go(self) -> None:
        for gate in self.gates.values():
            gate.set()

    async def say(self, user, conversation, message, *, upload=None, run_id=""):
        self.said.append((conversation.id, message, upload.name if upload else ""))
        self.run_ids.append(run_id)
        gate = self.gates.get(run_id) or self.gates.get(message)
        if gate is not None:
            await asyncio.to_thread(gate.wait, 10)
        return assistant.Turn(conversation_id=conversation.id, batch_id=conversation.batch_id, reply="Done.")


@pytest.fixture
def turns(monkeypatch: pytest.MonkeyPatch) -> Iterator[Turns]:
    stub = Turns()
    monkeypatch.setattr(assistant, "configured", lambda: True)
    monkeypatch.setattr(assistant, "say", stub.say)
    yield stub
    stub.let_go()  # nothing left waiting, whatever the test did


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def background() -> Iterator[ThreadPoolExecutor]:
    with ThreadPoolExecutor(max_workers=2) as pool:
        yield pool


def until(condition: Callable[[], Any], what: str) -> Any:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        found = condition()
        if found:
            return found
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


def started(client: TestClient, turns: Turns, background: ThreadPoolExecutor, **body: str) -> Future:
    """Send a message from another thread, its turn held back; return once it is running."""
    run_id = body["run_id"]
    turns.hold_back(run_id)
    sent = background.submit(client.post, "/api/chat", json=body)
    until(lambda: any(r["run_id"] == run_id for r in chat_running._RUNNING.values()), f"turn {run_id}")
    return sent


def an_open_conversation(title: str = "Do we encrypt backups?") -> str:
    return conversations.create(identity.local_user(), title).id


def test_a_running_turn_is_shown_with_what_was_sent(client, turns, background) -> None:
    conversation_id = an_open_conversation()
    sent = started(
        client, turns, background, message="  Answer everything  ", conversation_id=conversation_id, run_id="r1"
    )

    shown = client.get(f"/api/chat/{conversation_id}").json()
    assert shown["messages"] == [], "the message is not stored until the turn ends"
    assert shown["running"]["run_id"] == "r1"
    assert (shown["running"]["message"], shown["running"]["file"]) == ("Answer everything", "")
    assert shown["running"]["at"]
    [row] = client.get("/api/chat").json()["conversations"]
    assert row["running"] == shown["running"], "the history list says which conversation is working"

    turns.let_go()
    assert sent.result(timeout=10).status_code == 200
    assert client.get(f"/api/chat/{conversation_id}").json()["running"] is None
    assert client.get("/api/chat").json()["conversations"][0]["running"] is None


def test_a_new_chat_can_be_found_by_the_run_id_of_its_first_message(client, turns, background) -> None:
    """The page learns a new chat's id this way, while its first turn is still running."""
    an_open_conversation("An older one")
    sent = started(client, turns, background, message="Do we log access?", product="", run_id="first-run")

    listed = client.get("/api/chat").json()["conversations"]
    working = [row for row in listed if row["running"]]
    assert [row["running"]["run_id"] for row in working] == ["first-run"]
    assert working[0]["title"] == "Do we log access?"

    turns.let_go()
    assert sent.result(timeout=10).json()["conversation_id"] == working[0]["id"]


def test_a_second_message_while_a_turn_runs_is_refused(client, turns, background) -> None:
    conversation_id = an_open_conversation()
    sent = started(client, turns, background, message="Answer everything", conversation_id=conversation_id, run_id="r1")

    again = client.post("/api/chat", json={"message": "And now?", "conversation_id": conversation_id, "run_id": "r2"})

    assert (again.status_code, again.json()["code"]) == (409, "conversation_busy")
    assert [said for _, said, _ in turns.said] == ["Answer everything"], "the second message never reached the model"
    assert chat_running.running(conversation_id)["run_id"] == "r1"
    turns.let_go()
    assert sent.result(timeout=10).status_code == 200


def test_a_file_sent_while_a_turn_runs_is_refused_before_it_is_kept(client, turns, background, tmp_path) -> None:
    conversation_id = an_open_conversation()
    sent = started(client, turns, background, message="Answer everything", conversation_id=conversation_id, run_id="r1")
    path = shapes.simple(tmp_path / "Vendor.xlsx")

    refused = client.post(
        "/api/chat/upload",
        data={"message": "", "conversation_id": conversation_id, "run_id": "r2"},
        files={"file": (path.name, path.read_bytes(), "application/octet-stream")},
    )

    assert (refused.status_code, refused.json()["code"]) == (409, "conversation_busy")
    kept = list(settings.upload_dir.rglob("*.xlsx")) if settings.upload_dir.exists() else []
    assert kept == [], f"the file was kept anyway: {kept}"
    assert len(turns.said) == 1
    turns.let_go()
    assert sent.result(timeout=10).status_code == 200


def test_an_uploads_turn_is_shown_as_the_transcript_will_show_it(client, turns, background, tmp_path) -> None:
    """No words typed: what the turn is told, and the file under the name it was kept as."""
    path = shapes.simple(tmp_path / "Vendor.xlsx")
    turns.hold_back("up-1")
    sent = background.submit(
        client.post,
        "/api/chat/upload",
        data={"message": "", "conversation_id": "", "run_id": "up-1", "product": ""},
        files={"file": (path.name, path.read_bytes(), "application/octet-stream")},
    )
    until(lambda: chat_running._RUNNING, "the upload's turn")

    [row] = [row for row in client.get("/api/chat").json()["conversations"] if row["running"]]
    [(_, told, kept_as)] = turns.said
    assert row["running"]["run_id"] == "up-1"
    assert row["running"]["message"] == told == "Read Vendor.xlsx and tell me what is in it."
    assert row["running"]["file"] == kept_as and kept_as.endswith(".xlsx")
    turns.let_go()
    assert sent.result(timeout=10).status_code == 200


def test_a_running_conversation_cannot_be_forgotten(client, turns, background) -> None:
    conversation_id = an_open_conversation()
    sent = started(client, turns, background, message="Answer everything", conversation_id=conversation_id, run_id="r1")

    refused = client.delete(f"/api/chat/{conversation_id}")

    assert (refused.status_code, refused.json()["code"]) == (409, "conversation_busy")
    assert conversations.load(conversation_id) is not None
    turns.let_go()
    assert sent.result(timeout=10).status_code == 200
    assert client.delete(f"/api/chat/{conversation_id}").status_code == 200


def test_another_conversation_can_be_used_while_one_runs(client, turns, background) -> None:
    busy_one, free_one = an_open_conversation("First"), an_open_conversation("Second")
    sent = started(client, turns, background, message="Answer everything", conversation_id=busy_one, run_id="r1")

    other = client.post("/api/chat", json={"message": "Hello", "conversation_id": free_one, "run_id": "r2"})
    new = client.post("/api/chat", json={"message": "Hi", "product": "", "run_id": "r3"})

    assert other.status_code == 200 and other.json()["conversation_id"] == free_one
    assert new.status_code == 200 and new.json()["conversation_id"] not in (busy_one, free_one)
    assert chat_running.running(busy_one)["run_id"] == "r1", "the first is still running"
    turns.let_go()
    assert sent.result(timeout=10).status_code == 200


def test_a_turn_that_fails_lets_the_conversation_take_another_message(client, monkeypatch) -> None:
    async def fails(user, conversation, message, *, upload=None, run_id=""):
        raise RuntimeError("the model fell over")

    monkeypatch.setattr(assistant, "configured", lambda: True)
    monkeypatch.setattr(assistant, "say", fails)
    conversation_id = an_open_conversation()

    failed = client.post("/api/chat", json={"message": "hello", "conversation_id": conversation_id, "run_id": "r1"})

    assert failed.status_code == 500
    assert client.get(f"/api/chat/{conversation_id}").json()["running"] is None
    assert client.delete(f"/api/chat/{conversation_id}").status_code == 200


# --- the review of plan 031 ---------------------------------------------------------


def test_a_turn_sent_without_a_run_id_is_held_and_watched_under_one(client, turns, background, tmp_path) -> None:
    """A script's turn was held under "": a page that opened the conversation took it for
    a different turn on every check, and drew the conversation again every few seconds."""
    conversation_id = an_open_conversation()
    turns.hold_back("No run id here")
    sent = background.submit(
        client.post, "/api/chat", json={"message": "No run id here", "conversation_id": conversation_id}
    )
    held = until(lambda: chat_running.running(conversation_id), "the turn")

    assert held["run_id"], "named, never empty"
    assert turns.run_ids == [held["run_id"]], "and its progress is reported under the same name"
    turns.let_go()
    assert sent.result(timeout=10).status_code == 200

    path = shapes.simple(tmp_path / "Vendor.xlsx")
    turns.hold_back("Read Vendor.xlsx and tell me what is in it.")
    uploaded = background.submit(
        client.post,
        "/api/chat/upload",
        data={"message": "", "conversation_id": conversation_id},
        files={"file": (path.name, path.read_bytes(), "application/octet-stream")},
    )
    held = until(lambda: chat_running.running(conversation_id), "the upload's turn")
    assert held["run_id"] and turns.run_ids[-1] == held["run_id"]
    turns.let_go()
    assert uploaded.result(timeout=10).status_code == 200


def test_a_file_for_an_open_conversation_is_kept_only_once_its_turn_is_held(
    client, turns, monkeypatch, tmp_path
) -> None:
    """The upload was refused after its file was saved when a message from another tab took
    the conversation between the check and the hold; now the hold comes first."""
    from src import service

    conversation_id = an_open_conversation()
    real = service.save_upload
    seen: list[dict[str, str] | None] = []

    def save_upload(*args, **kwargs):
        seen.append(chat_running.running(conversation_id))
        return real(*args, **kwargs)

    monkeypatch.setattr(service, "save_upload", save_upload)
    path = shapes.simple(tmp_path / "Vendor.xlsx")

    sent = client.post(
        "/api/chat/upload",
        data={"message": "Answer it", "conversation_id": conversation_id, "run_id": "up-2"},
        files={"file": (path.name, path.read_bytes(), "application/octet-stream")},
    )

    assert sent.status_code == 200
    assert seen and seen[0] is not None, "the file was kept before the conversation was held"
    assert (seen[0]["run_id"], seen[0]["message"]) == ("up-2", "Answer it")
    [(_, _, kept_as)] = turns.said
    assert kept_as.endswith(".xlsx")


def test_the_file_a_held_turn_shows_is_the_name_it_was_kept_under(client, turns, background, tmp_path) -> None:
    """Held before the file is saved, then told the name saving gave it, as the transcript will show it."""
    conversation_id = an_open_conversation()
    path = shapes.simple(tmp_path / "Vendor.xlsx")
    turns.hold_back("up-3")
    sent = background.submit(
        client.post,
        "/api/chat/upload",
        data={"message": "Answer it", "conversation_id": conversation_id, "run_id": "up-3"},
        files={"file": (path.name, path.read_bytes(), "application/octet-stream")},
    )
    until(lambda: turns.said, "the upload's turn")

    [(_, _, kept_as)] = turns.said
    assert chat_running.running(conversation_id)["file"] == kept_as
    turns.let_go()
    assert sent.result(timeout=10).status_code == 200


def test_a_turn_that_ends_while_its_conversation_is_read_is_still_reported(
    client, turns, background, monkeypatch
) -> None:
    """`running` was read last, after the answers: a turn that ended in between came back as
    an old transcript with no turn, and the page drew neither the message nor its reply."""
    conversation_id = an_open_conversation()
    sent = started(client, turns, background, message="Answer everything", conversation_id=conversation_id, run_id="r1")

    def answers_for(user, conversation):
        turns.let_go()  # the turn ends while the conversation is being read
        until(lambda: chat_running.running(conversation_id) is None, "the turn to end")
        return None

    monkeypatch.setattr(assistant, "answers_for", answers_for)
    shown = client.get(f"/api/chat/{conversation_id}").json()

    assert shown["messages"] == [], "read before the turn was saved"
    assert shown["running"] and shown["running"]["run_id"] == "r1", "so it comes with the turn it is missing"
    assert sent.result(timeout=10).status_code == 200
