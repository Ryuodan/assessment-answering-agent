"""Deleting a questionnaire, and saved work not kept for ever (plan 033).

Each questionnaire can be deleted by its owner, with its answers and files, and
not while it is being answered. Questionnaires, lists, chats and answered runs
nobody has used for `RETENTION_DAYS` are deleted by a pass at start-up and then
about daily; opening one is using it. The knowledge base, the answer memory,
products, people and the event log are never touched, and `inspect retention`
lists what would go without changing anything.

The pipeline is never called: answering is stubbed.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from src import answer_memory, batches, busy, chat_running, cli, conversations, events, identity, lists, products
from src import retention, runs, store, tools
from src.api import app
from src.config import settings
from src.models import AnsweredQuestion, AssessmentResult, Question
from tests import forms_fixtures as shapes

TEAM = settings.default_team
ANSWER = "Yes, every backup is encrypted with AES-256."
CODE = "TEAM-CODE-FOR-TESTS"
ALICE = "alice@example.com"
BOB = "bob@example.com"
OLD = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat(timespec="seconds")


@pytest.fixture(autouse=True)
def nothing_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_running, "_RUNNING", {})


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def drafted(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(questions: list[Question], language: Any = None, run_id: Any = None, **extra: Any):
        return [AnsweredQuestion(question=q, answer=ANSWER, confidence=0.9, needs_review=False) for q in questions]

    monkeypatch.setattr("src.tools.service.answer_questions", fake)


@pytest.fixture
def team() -> None:
    identity.ensure_team(TEAM, name="Cybersecurity")
    identity.set_access_code(TEAM, CODE)
    identity.add_user(ALICE)
    identity.add_user(BOB)


def as_person(email: str) -> TestClient:
    client = TestClient(app)
    assert client.post("/api/auth/session", json={"email": email, "code": CODE}).status_code == 200
    return client


def upload(client: TestClient, path: Path, **fields: str) -> dict[str, Any]:
    with open(path, "rb") as handle:
        response = client.post("/api/forms", files={"file": (path.name, handle.read())}, data=fields)
    assert response.status_code == 200, response.text
    return response.json()


def answered_and_filled(client: TestClient, tmp_path: Path, name: str = "vendor.xlsx") -> dict[str, Any]:
    opened = upload(client, shapes.simple(tmp_path / name))
    client.post(f"/api/forms/{opened['id']}/answer", json={})
    assert client.post(f"/api/forms/{opened['id']}/fill", json={}).json()["written"]
    return opened


def age_questionnaire(batch_id: str, stamp: str = OLD) -> None:
    conn = store.connect()
    with conn:
        conn.execute("UPDATE form_batches SET updated_at = ?, used_at = '' WHERE batch_id = ?", (stamp, batch_id))


def age_conversation(conversation_id: str, stamp: str = OLD) -> None:
    conn = store.connect()
    with conn:
        conn.execute(
            "UPDATE conversations SET updated_at = ?, used_at = '' WHERE conversation_id = ?", (stamp, conversation_id)
        )


def a_chat_about(batch_id: str, user: identity.User | None = None) -> conversations.Conversation:
    conversation = conversations.create(user or identity.local_user(), "Answer the vendor file")
    conversation.batch_id = batch_id
    conversation.messages = [HumanMessage(content="Answer the vendor file"), AIMessage(content="All four answered.")]
    conversations.save(conversation)
    return conversation


def a_run(run_id: str, created_at: str) -> None:
    runs.save(
        identity.local_user(),
        AssessmentResult(run_id=run_id, source_name="typed", language="en", questions_found=0, answers=[]),
    )
    conn = store.connect()
    with conn:
        conn.execute("UPDATE runs SET created_at = ? WHERE run_id = ?", (created_at, run_id))


def kept(stamp: str, days: int = 180) -> str:
    return (datetime.fromisoformat(stamp) + timedelta(days=days)).date().isoformat()


def from_today() -> str:
    """The day something used now is kept until, in UTC as the server counts it."""
    return (datetime.now(timezone.utc) + timedelta(days=180)).date().isoformat()


def files_under(folder: Path) -> list[str]:
    return (
        sorted(str(path.relative_to(folder)) for path in folder.rglob("*") if path.is_file()) if folder.exists() else []
    )


# --- deleting one --------------------------------------------------------------------------


def test_its_owner_deletes_a_questionnaire_with_its_answers_and_files(
    client: TestClient, tmp_path: Path, drafted: None
) -> None:
    opened = answered_and_filled(client, tmp_path)
    source = batches.load(opened["id"]).source_path
    filled = settings.filled_dir / opened["id"]
    assert source.is_file() and filled.is_dir()

    response = client.delete(f"/api/forms/{opened['id']}")

    assert response.json() == {"deleted": opened["id"], "answers": 4, "files": 2}
    assert client.get(f"/api/forms/{opened['id']}").status_code == 404
    assert client.get("/api/forms").json()["forms"] == []
    assert not source.exists() and not filled.exists()
    assert store.connect().execute("SELECT COUNT(*) FROM batch_answers").fetchone()[0] == 0
    [event] = events.recent(TEAM, kind=events.QUESTIONNAIRE_DELETED)
    assert event.subject_id == opened["id"]
    assert event.payload == {"format": "xlsx", "questions": 4, "answers": 4, "files": 2}, "counts, never content"


def test_somebody_else_cannot_delete_it(team: None, tmp_path: Path) -> None:
    alice, bob = as_person(ALICE), as_person(BOB)
    opened = upload(alice, shapes.simple(tmp_path / "vendor.xlsx"))

    refused = bob.delete(f"/api/forms/{opened['id']}")

    assert (refused.status_code, refused.json()["code"]) == (404, "questionnaire_not_found")
    assert alice.get(f"/api/forms/{opened['id']}").status_code == 200
    assert batches.load(opened["id"]).source_path.is_file()


def test_a_questionnaire_being_answered_is_not_deleted(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened = upload(client, shapes.simple(tmp_path / "vendor.xlsx"))
    with monkeypatch.context() as running:  # a run going on in another request
        running.setitem(busy._HELD, opened["id"], busy._Hold(run_id="run-x", started_at="2026-11-07T09:00:00+00:00"))
        refused = client.delete(f"/api/forms/{opened['id']}")

    assert (refused.status_code, refused.json()["code"]) == (409, "questionnaire_busy")
    assert batches.load(opened["id"]).source_path.is_file()
    assert client.delete(f"/api/forms/{opened['id']}").status_code == 200, "once the run is over"


def test_not_while_a_chat_turn_runs_about_it(client: TestClient, tmp_path: Path) -> None:
    opened = upload(client, shapes.simple(tmp_path / "vendor.xlsx"))
    chat = a_chat_about(opened["id"])

    with chat_running.hold(chat.id, run_id="turn-1", message="Make them shorter"):
        refused = client.delete(f"/api/forms/{opened['id']}")

    assert (refused.status_code, refused.json()["code"]) == (409, "questionnaire_busy")
    assert batches.load(opened["id"]) is not None


def test_a_chat_whose_questionnaire_was_deleted_still_opens(client: TestClient, tmp_path: Path, drafted: None) -> None:
    opened = answered_and_filled(client, tmp_path)
    chat = a_chat_about(opened["id"])
    assert client.get(f"/api/chat/{chat.id}").json()["answers"]["id"] == opened["id"]

    client.delete(f"/api/forms/{opened['id']}")
    shown = client.get(f"/api/chat/{chat.id}")

    assert shown.status_code == 200
    body = shown.json()
    assert [message["text"] for message in body["messages"]] == ["Answer the vendor file", "All four answered."]
    assert body["answers"] is None and body["batch_id"] == ""
    [listed] = client.get("/api/chat").json()["conversations"]
    assert listed["id"] == chat.id and listed["batch_id"] == ""


def test_a_file_another_questionnaire_reads_is_kept(client: TestClient, tmp_path: Path) -> None:
    """Identical content is saved under one name, so two questionnaires can read one file."""
    workbook = shapes.simple(tmp_path / "vendor.xlsx")
    first, second = upload(client, workbook), upload(client, workbook)
    source = batches.load(first["id"]).source_path
    assert batches.load(second["id"]).source_path == source

    assert client.delete(f"/api/forms/{first['id']}").json()["files"] == 0
    assert source.is_file(), "the other one still reads it"
    assert client.delete(f"/api/forms/{second['id']}").json()["files"] == 1
    assert not source.exists()


def test_a_list_is_deleted_like_a_file(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def extract(path: Path):
        return "en", [Question(id="q1", text="Are backups encrypted?")]

    monkeypatch.setattr("src.lists.service.extract_assessment_questions", extract)
    typed = client.post("/api/forms/list", data={"questions": ["Q?"]}).json()
    pdf = client.post("/api/forms/list", files={"file": ("vendor.pdf", b"%PDF-1.4 stand-in")}).json()
    kept_pdf = batches.load(pdf["id"]).source_path
    assert kept_pdf.is_file()

    assert client.delete(f"/api/forms/{typed['id']}").json() == {"deleted": typed["id"], "answers": 0, "files": 0}
    assert client.delete(f"/api/forms/{pdf['id']}").json()["files"] == 1
    assert not kept_pdf.exists() and client.get("/api/forms").json()["forms"] == []


def test_the_answer_memory_keeps_what_approving_taught(
    client: TestClient, tmp_path: Path, drafted: None, memory_index: Any
) -> None:
    opened = answered_and_filled(client, tmp_path)
    question = opened["questions"][0]["id"]
    client.post(f"/api/forms/{opened['id']}/answers", json={"question_id": question, "text": "Ours, by hand."})
    remembered = client.post(f"/api/forms/{opened['id']}/approve", json={"question_id": question}).json()
    entry_id = remembered["remembered"]
    assert answer_memory.get(entry_id, TEAM) is not None

    client.delete(f"/api/forms/{opened['id']}")

    assert answer_memory.get(entry_id, TEAM).answer == "Ours, by hand."


def test_a_deleted_products_questionnaire_can_be_deleted(client: TestClient, tmp_path: Path) -> None:
    availo = products.add(None, TEAM, "Availo")
    opened = upload(client, shapes.simple(tmp_path / "vendor.xlsx"), product=availo.id)
    products.delete(identity.local_user(), TEAM, availo.id, confirm="confirm")
    assert client.get(f"/api/forms/{opened['id']}").json()["read_only"] is True

    assert client.delete(f"/api/forms/{opened['id']}").status_code == 200


# --- opening is using -------------------------------------------------------------------


def test_opening_a_questionnaire_counts_as_using_it(client: TestClient, tmp_path: Path) -> None:
    opened = upload(client, shapes.simple(tmp_path / "vendor.xlsx"))
    age_questionnaire(opened["id"])
    assert [item.id for item in retention.due()] == [opened["id"]]
    [row] = client.get("/api/forms").json()["forms"]
    assert row["kept_until"] == kept(OLD), "listing it is not opening it"

    shown = client.get(f"/api/forms/{opened['id']}").json()

    assert shown["kept_until"] == kept(shown["used_at"]) == from_today()
    assert shown["updated_at"] == OLD, "opening changes nothing else"
    assert retention.due() == []


def test_opening_a_chat_counts_as_using_it(client: TestClient) -> None:
    chat = conversations.create(identity.local_user(), "What does our backup policy say?")
    age_conversation(chat.id)
    assert [item.kind for item in retention.due()] == ["conversation"]

    shown = client.get(f"/api/chat/{chat.id}").json()

    assert shown["kept_until"] == from_today()
    assert retention.due() == []
    assert conversations.load(chat.id).updated_at == OLD


def test_a_chat_in_use_keeps_its_questionnaire(client: TestClient, tmp_path: Path) -> None:
    """Its answers panel is the questionnaire: opening the chat is using both."""
    opened = upload(client, shapes.simple(tmp_path / "vendor.xlsx"))
    chat = a_chat_about(opened["id"])
    age_questionnaire(opened["id"])
    age_conversation(chat.id)

    client.get(f"/api/chat/{chat.id}")

    assert retention.due() == []
    assert client.get("/api/forms").json()["forms"][0]["kept_until"] == from_today()


def test_opening_moves_it_to_the_top_of_the_lists(client: TestClient, tmp_path: Path) -> None:
    """Most recently used first: opening is using (plan 033). Listed by last change, it stayed where it was."""
    older = upload(client, shapes.simple(tmp_path / "older.xlsx"))
    newer = upload(client, shapes.simple(tmp_path / "newer.xlsx"))
    age_questionnaire(older["id"], "2026-10-01T09:00:00+00:00")
    age_questionnaire(newer["id"], "2026-10-02T09:00:00+00:00")
    first_chat = conversations.create(identity.local_user(), "First")
    second_chat = conversations.create(identity.local_user(), "Second")
    age_conversation(first_chat.id, "2026-10-01T09:00:00+00:00")
    age_conversation(second_chat.id, "2026-10-02T09:00:00+00:00")
    assert [row["id"] for row in client.get("/api/forms").json()["forms"]] == [newer["id"], older["id"]]

    client.get(f"/api/forms/{older['id']}")
    client.get(f"/api/chat/{first_chat.id}")

    forms = client.get("/api/forms").json()["forms"]
    assert [row["id"] for row in forms] == [older["id"], newer["id"]]
    assert forms[0]["updated_at"] == "2026-10-01T09:00:00+00:00" and forms[0]["used_at"] > forms[1]["used_at"]
    chats = client.get("/api/chat").json()["conversations"]
    assert [row["id"] for row in chats] == [first_chat.id, second_chat.id]


def test_every_row_and_page_says_until_when_it_is_kept(client: TestClient, tmp_path: Path) -> None:
    opened = upload(client, shapes.simple(tmp_path / "vendor.xlsx"))
    chat = conversations.create(identity.local_user(), "Hello")
    age_questionnaire(opened["id"], "2026-06-01T09:00:00+00:00")
    age_conversation(chat.id, "2026-06-02T09:00:00+00:00")

    assert client.get("/api/forms").json()["forms"][0]["kept_until"] == "2026-11-28"
    assert client.get("/api/chat").json()["conversations"][0]["kept_until"] == "2026-11-29"
    today = from_today()
    assert client.get(f"/api/forms/{opened['id']}").json()["kept_until"] == today
    assert client.get(f"/api/chat/{chat.id}").json()["kept_until"] == today
    answered = client.post(f"/api/forms/{opened['id']}/blank", json={"question_id": opened["questions"][0]["id"]})
    assert answered.json()["kept_until"] == today, "every route that returns the questionnaire says so"


def test_retention_off_keeps_everything(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "retention_days", 0)
    opened = upload(client, shapes.simple(tmp_path / "vendor.xlsx"))
    chat = conversations.create(identity.local_user(), "Hello")
    age_questionnaire(opened["id"], "2001-01-01T00:00:00+00:00")
    age_conversation(chat.id, "2001-01-01T00:00:00+00:00")
    a_run("r-old", "2001-01-01T00:00:00+00:00")

    assert retention.sweep() == {}
    assert retention.due(within_days=10_000) == []

    assert batches.load(opened["id"]) is not None and conversations.load(chat.id) is not None
    assert runs.load("r-old") is not None
    assert client.get("/api/forms").json()["forms"][0]["kept_until"] is None
    assert client.get(f"/api/forms/{opened['id']}").json()["kept_until"] is None
    assert client.get("/api/chat").json()["conversations"][0]["kept_until"] is None
    assert client.get(f"/api/chat/{chat.id}").json()["kept_until"] is None
    assert events.recent(TEAM, kind=events.WORK_EXPIRED) == []


# --- the pass ------------------------------------------------------------------------------


def test_a_pass_deletes_only_what_is_older(client: TestClient, tmp_path: Path, drafted: None) -> None:
    old_file = answered_and_filled(client, tmp_path, "old.xlsx")
    new_file = upload(client, shapes.simple(tmp_path / "new.xlsx"))
    old_list = lists.open_list(identity.local_user(), [Question(id="1", text="Q?")], name="Old list")
    new_list = lists.open_list(identity.local_user(), [Question(id="1", text="Q?")], name="New list")
    old_chat = a_chat_about(old_file["id"])
    new_chat = conversations.create(identity.local_user(), "Hello")
    a_run("r-old", OLD)
    a_run("r-new", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    for batch_id in (old_file["id"], old_list.id):
        age_questionnaire(batch_id)
    age_conversation(old_chat.id)
    old_source = batches.load(old_file["id"]).source_path

    counts = retention.sweep()

    assert counts == {TEAM: {"questionnaires": 1, "lists": 1, "conversations": 1, "runs": 1, "files": 2}}
    assert batches.load(old_file["id"]) is None and batches.load(old_list.id) is None
    assert conversations.load(old_chat.id) is None and runs.load("r-old") is None
    assert not old_source.exists() and not (settings.filled_dir / old_file["id"]).exists()
    assert batches.load(new_file["id"]) is not None and batches.load(new_list.id) is not None
    assert conversations.load(new_chat.id) is not None and runs.load("r-new") is not None
    assert batches.load(new_file["id"]).source_path.is_file()


def test_a_pass_skips_what_is_in_use(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    answering = upload(client, shapes.simple(tmp_path / "answering.xlsx"))
    talked_about = upload(client, shapes.simple(tmp_path / "talked.xlsx"))
    chat = a_chat_about(talked_about["id"])
    talking = conversations.create(identity.local_user(), "Hello")
    for batch_id in (answering["id"], talked_about["id"]):
        age_questionnaire(batch_id)
    for conversation_id in (chat.id, talking.id):
        age_conversation(conversation_id)

    with monkeypatch.context() as running:
        running.setitem(busy._HELD, answering["id"], busy._Hold(run_id="run-x", started_at=OLD))
        with chat_running.hold(chat.id, run_id="t1", message="Shorter"):
            with chat_running.hold(talking.id, run_id="t2", message="Hello?"):
                assert retention.sweep() == {}

    assert all(batches.load(b) for b in (answering["id"], talked_about["id"]))
    assert all(conversations.load(c) for c in (chat.id, talking.id))
    assert retention.sweep()[TEAM]["questionnaires"] == 2, "the next pass, once nothing holds them"


def test_a_pass_never_touches_the_knowledge_base_memory_products_people_or_events(
    client: TestClient, tmp_path: Path, memory_index: Any
) -> None:
    opened = upload(client, shapes.simple(tmp_path / "vendor.xlsx"))  # before anybody is added: open access
    identity.add_user(ALICE)
    availo = products.add(None, TEAM, "Availo")
    entry = answer_memory.record("Do you encrypt backups?", "Yes.", team_id=TEAM, origin="approved", approved_by=ALICE)
    policy = settings.team_upload_dir(TEAM) / "Backup Standard.pdf"
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_bytes(b"%PDF-1.4 policy")
    product_file = settings.product_upload_dir(TEAM, availo.id) / "Availo fact sheet.pdf"
    product_file.parent.mkdir(parents=True, exist_ok=True)
    product_file.write_bytes(b"%PDF-1.4 product")
    age_questionnaire(opened["id"])
    conn = store.connect()
    with conn:
        for table in ("memory_entries", "products", "users", "events"):
            conn.execute(f"UPDATE {table} SET created_at = ?", (OLD,))

    def counted() -> dict[str, int]:
        tables = ("memory_entries", "products", "users", "teams", "events", "deleted_products")
        return {table: store.connect().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}

    before = counted()
    retention.sweep()

    assert batches.load(opened["id"]) is None
    assert counted() == {**before, "events": before["events"] + 1}, "only the pass's own event is new"
    assert policy.is_file() and product_file.is_file()
    assert answer_memory.get(entry.entry_id, TEAM) is not None


def test_each_pass_records_one_event_with_counts_never_content(client: TestClient, tmp_path: Path) -> None:
    opened = upload(client, shapes.simple(tmp_path / "Northwind vendor review.xlsx"))
    chat = conversations.create(identity.local_user(), "What did we tell Northwind?")
    age_questionnaire(opened["id"])
    age_conversation(chat.id)

    retention.sweep()
    retention.sweep()  # nothing left: no second event

    [event] = events.recent(TEAM, kind=events.WORK_EXPIRED)
    assert event.actor_email == retention.ACTOR
    assert event.payload == {
        "days": 180,
        "questionnaires": 1,
        "lists": 0,
        "conversations": 1,
        "runs": 0,
        "files": 1,
    }
    assert "Northwind" not in json.dumps(event.payload) + event.subject_id


def test_the_server_runs_a_pass_when_it_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    passes: list[bool] = []
    monkeypatch.setattr(retention, "sweep", lambda: passes.append(True) or {})

    with TestClient(app):
        for _ in range(100):
            if passes:
                break
            asyncio.run(asyncio.sleep(0.01))

    assert passes


def test_a_failed_pass_never_stops_the_next(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def failing() -> dict[str, Any]:
        calls.append(1)
        raise RuntimeError("disk went away")

    monkeypatch.setattr(retention, "sweep", failing)

    async def run_twice() -> None:
        task = asyncio.create_task(retention.keep_for_days(every=0.01))
        while len(calls) < 2:
            await asyncio.sleep(0.01)
        task.cancel()

    asyncio.run(run_twice())
    assert len(calls) >= 2


# --- what would go next ---------------------------------------------------------------------


def _everything() -> tuple[list[tuple[Any, ...]], list[str]]:
    conn = store.connect()
    tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    rows = [tuple(row) for table in tables for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
    people = settings.user_upload_dir(TEAM, identity.LOCAL_EMAIL).parent.parent
    return rows, files_under(settings.upload_dir) + files_under(people) + files_under(settings.filled_dir)


def test_inspect_retention_lists_what_would_go_and_changes_nothing(
    client: TestClient, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    soon = upload(client, shapes.simple(tmp_path / "Northwind vendor review.xlsx"))
    later = upload(client, shapes.simple(tmp_path / "later.xlsx"))
    chat = conversations.create(identity.local_user(), "What did we tell Northwind?")
    near = (datetime.now(timezone.utc) - timedelta(days=170)).isoformat(timespec="seconds")
    age_questionnaire(soon["id"], near)
    age_conversation(chat.id, OLD)
    a_run("r-old", OLD)
    capsys.readouterr()
    before = _everything()

    assert cli.main(["inspect", "retention"]) == 0
    out = capsys.readouterr().out
    assert cli.main(["inspect", "retention", "--days", "0", "--json"]) == 0
    now_only = json.loads(capsys.readouterr().out)

    assert _everything() == before, "nothing was written, deleted or touched"
    assert "Deleted within 30 day(s): 3" in out
    assert soon["id"] in out and chat.id in out and "r-old" in out and later["id"] not in out
    assert f"questionnaire {TEAM}/{identity.LOCAL_EMAIL}: 1" in " ".join(out.split())
    assert "Northwind" not in out, "ids, owners and dates; never a file's name or a chat's title"
    assert sorted(item["kind"] for item in now_only["due"]) == ["conversation", "run"]
    assert now_only["retention_days"] == 180


def test_inspect_retention_says_when_it_is_off(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(settings, "retention_days", 0)
    assert cli.main(["inspect", "retention"]) == 0
    assert "Retention is off (RETENTION_DAYS=0)" in capsys.readouterr().out


def test_a_version_14_database_upgrades_and_its_work_is_as_old_as_it_was() -> None:
    conn = store.connect()
    tables = [
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    ]
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript("".join(f"DROP TABLE IF EXISTS {name};" for name in tables))
    conn.execute("PRAGMA foreign_keys = ON")
    for index, step in enumerate(store.MIGRATIONS[:14]):
        getattr(store.migrations, step)(conn) if step.startswith("_") else conn.executescript(step)
        conn.execute(f"PRAGMA user_version = {index + 1}")
    conn.execute(
        "INSERT INTO form_batches (batch_id, team_id, actor_email, source_name, source_path, format, detected, "
        "created_at, updated_at) VALUES ('b1', ?, 'a@example.test', 'f.xlsx', 'f.xlsx', 'xlsx', "
        '\'{"source_name": "f.xlsx", "format": "xlsx"}\', ?, ?)',
        (TEAM, OLD, OLD),
    )
    conn.execute(
        "INSERT INTO conversations (conversation_id, team_id, actor_email, created_at, updated_at) "
        "VALUES ('c1', ?, 'a@example.test', ?, ?)",
        (TEAM, OLD, OLD),
    )
    conn.commit()
    store.reset_connection()

    upgraded = store.connect()
    assert upgraded.execute("PRAGMA user_version").fetchone()[0] == len(store.MIGRATIONS) >= 15
    assert batches.load("b1").used_at == OLD and conversations.load("c1").used_at == OLD
    assert {item.id for item in retention.due()} == {"b1", "c1"}


def test_a_list_kept_by_the_tools_is_the_same_questionnaire(drafted: None) -> None:
    """What the pages see, the assistant's `inspect` sees: one view of a list."""
    user = identity.local_user()
    batch = lists.open_list(user, [Question(id="1", text="Q?")], name="Follow-up")
    asyncio.run(tools.answer(user, batch.id))

    view = tools.inspect(user, batch.id)

    assert view["format"] == "list" and view["counts"]["answered"] == 1
    assert view["kept_until"] == from_today()
