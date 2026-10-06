"""Questionnaires and chats carry a product, and answering uses it (plan 023)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import answer_memory, batches, conversations, identity, knowledge, products, roles, service, store, tools
from src.agents import assistant
from src.agents.assistant_prompt import FOR_PRODUCT
from src.api import app
from src.config import settings
from src.errors import ProductNotFound
from src.graph import nodes, workflow
from src.models import AnsweredQuestion, Evidence, Question, SourceType
from src.prompts import PRODUCT_SOURCES_NOTE, format_sources_block
from tests import forms_fixtures as shapes
from tests.conftest import FakeDocument, FakeVectorStore, bare_store

TEAM = settings.default_team
CODE = "TEAM-CODE-FOR-TESTS"
ALICE = "alice@example.test"


@pytest.fixture
def stores(monkeypatch):
    """A fake index per (team, product), reached however the code asks for one."""
    made: dict[tuple[str, str], knowledge.KnowledgeStore] = {}

    def get_store(team_id=None, *, product_id=""):
        key = (team_id or TEAM, product_id)
        if key not in made:
            made[key] = bare_store(FakeVectorStore([]))
            made[key].team_id, made[key].product_id = key
            made[key]._store.delete_collection = lambda key=key: made.pop(key, None)
        return made[key]

    monkeypatch.setattr("src.knowledge.get_store", get_store)
    return made


@pytest.fixture
def availo():
    identity.ensure_team(TEAM)
    return products.add(None, TEAM, "Availo")


@pytest.fixture
def theirs():
    identity.ensure_team("privacy")
    return products.add(None, "privacy", "Theirs")


@pytest.fixture
def user():
    return identity.local_user()


@pytest.fixture
def answering(monkeypatch):
    """Stand in for the pipeline, and keep what each call was asked to answer for."""
    calls: list[dict] = []

    async def fake(questions, language=None, run_id=None, **extra):
        calls.append(extra)
        return [AnsweredQuestion(question=q, answer="Yes.", confidence=0.9) for q in questions]

    monkeypatch.setattr(tools.service, "answer_questions", fake)
    return calls


def staged(store: knowledge.KnowledgeStore, name: str, score: float) -> None:
    store._store._staged = [(FakeDocument(f"{name} text", {"source_name": name, "source_type": "guideline"}), score)]
    store._store.records.append(
        {"text": f"{name} text", "metadata": {"source_name": name, "source_type": "guideline"}, "id": name}
    )


def indexed(store: knowledge.KnowledgeStore) -> list[str]:
    return [record["metadata"]["entry_id"] for record in store._store.records]


# --- a questionnaire's product -------------------------------------------------------


@pytest.mark.asyncio
async def test_a_questionnaire_is_answered_for_its_product_which_can_change(
    stores, user, availo, theirs, answering, tmp_path
) -> None:
    path = shapes.simple(tmp_path / "vendor.xlsx")
    batch = tools.open_form(user, path, product_id=availo.id)
    assert batch.product_id == availo.id
    assert tools.inspect(user, batch.id)["product_id"] == availo.id
    assert batches.recent(TEAM, actor_email=user.email)[0]["product_id"] == availo.id

    await tools.answer(user, batch.id)
    assert answering[-1]["product_id"] == availo.id
    written = len(batches.answers(batch.id))

    tools.set_product(user, batch.id, "")
    assert tools.inspect(user, batch.id)["product_id"] == ""
    assert len(batches.answers(batch.id)) == written, "the answers already written stay"
    await tools.answer(user, batch.id, replace_existing=True)
    assert "product_id" not in answering[-1], "General answers as it always did"

    with pytest.raises(ProductNotFound):
        tools.set_product(user, batch.id, theirs.id)
    with pytest.raises(ProductNotFound):
        tools.open_form(user, path, product_id=theirs.id)


@pytest.mark.asyncio
async def test_a_products_questions_are_answered_from_its_material_and_the_shared(stores, availo) -> None:
    staged(knowledge.get_store(TEAM), "Shared policy.pdf", 0.9)
    staged(knowledge.get_store(TEAM, product_id=availo.id), "Availo policy.pdf", 0.8)
    question = Question(id="q1", text="Do you encrypt backups?")

    found = await nodes.retrieve(
        {"question": question, "team_id": TEAM, "product_id": availo.id, "search_queries": [question.text]}
    )
    assert {e.source_name: e.product_id for e in found["evidence"]} == {
        "Availo policy.pdf": availo.id,
        "Shared policy.pdf": "",
    }

    general = await nodes.retrieve({"question": question, "team_id": TEAM, "search_queries": [question.text]})
    assert {e.source_name: e.product_id for e in general["evidence"]} == {"Shared policy.pdf": ""}


@pytest.mark.asyncio
async def test_a_products_search_covers_its_material_first_then_the_shared(stores, availo) -> None:
    staged(knowledge.get_store(TEAM), "Shared policy.pdf", 0.9)
    staged(knowledge.get_store(TEAM, product_id=availo.id), "Availo policy.pdf", 0.8)

    found = await service.search_knowledge("backups", mode="semantic", team_id=TEAM, product_id=availo.id)
    assert [(r["source_name"], r["product_id"]) for r in found["results"]] == [
        ("Availo policy.pdf", availo.id),
        ("Shared policy.pdf", ""),
    ]
    assert found["documents"] == ["Availo policy.pdf", "Shared policy.pdf"]

    general = await service.search_knowledge("backups", mode="semantic", team_id=TEAM)
    assert [(r["source_name"], r["product_id"]) for r in general["results"]] == [("Shared policy.pdf", "")]
    assert general["documents"] == ["Shared policy.pdf"]


@pytest.mark.asyncio
async def test_the_whole_document_path_carries_the_product(monkeypatch, tmp_path) -> None:
    seen: dict = {}

    class Graph:
        async def ainvoke(self, state, config=None):
            seen.update(state)
            return {"questions": [], "answers": []}

    async def text(path):
        return "1. Do you encrypt backups?"

    monkeypatch.setattr(service, "assessment_graph", lambda: Graph())
    monkeypatch.setattr(service, "extracted_document_text", text)
    await service.answer_assessment(tmp_path / "assessment.pdf", team_id=TEAM, product_id="p1")
    assert seen["product_id"] == "p1"

    sent = workflow._fan_out({"questions": [Question(id="q1", text="Q?")], "team_id": TEAM, "product_id": "p1"})
    assert [send.arg["product_id"] for send in sent] == ["p1"]


def test_the_drafter_is_told_which_sources_are_the_products_own() -> None:
    shared = Evidence(source_type=SourceType.GUIDELINE, source_name="Shared.pdf", snippet="Backups are encrypted.")
    own = Evidence(
        source_type=SourceType.GUIDELINE, source_name="Availo.pdf", snippet="Not encrypted.", product_id="p1"
    )
    prior = Evidence(source_type=SourceType.PRIOR_ANSWER, source_name="memory", snippet="No.", product_id="p1")

    general = format_sources_block([shared])
    assert general == "[1] OUR POLICY — Shared.pdf\nBackups are encrypted.", "General's block is as it was"

    block = format_sources_block([own, prior, shared])
    assert block.startswith(PRODUCT_SOURCES_NOTE + "\n\n")
    assert "[1] OUR POLICY, FOR THIS PRODUCT — Availo.pdf" in block
    assert "[2] PREVIOUS ANSWER, FOR THIS PRODUCT —" in block
    assert "[3] OUR POLICY — Shared.pdf" in block


def test_an_approved_answer_is_remembered_for_the_questionnaires_product(stores, user, availo, tmp_path) -> None:
    batch = tools.open_form(user, shapes.simple(tmp_path / "vendor.xlsx"), product_id=availo.id)
    question = next(q for q in batch.form.questions if q.writable)
    tools.set_answer(user, batch.id, question.id, "Yes, every backup is encrypted.")

    entry_id = tools.approve_answer(user, batch.id, question.id)
    assert answer_memory.get(entry_id, TEAM).product_id == availo.id
    assert indexed(knowledge.get_store(TEAM, product_id=availo.id)) == [entry_id]
    assert indexed(knowledge.get_store(TEAM)) == []

    tools.set_product(user, batch.id, "")
    assert tools.approve_answer(user, batch.id, question.id) == entry_id
    assert answer_memory.get(entry_id, TEAM).product_id == "", "approved again, it moves with the questionnaire"
    assert indexed(knowledge.get_store(TEAM, product_id=availo.id)) == []
    assert indexed(knowledge.get_store(TEAM)) == [entry_id]


# --- a chat's product ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_chats_product_reaches_its_questionnaire_and_its_search(
    stores, user, availo, theirs, monkeypatch, tmp_path
) -> None:
    conversation = assistant.start(user, "Read this", availo.id)
    assert conversations.load(conversation.id).product_id == availo.id

    path = shapes.status_and_comment(tmp_path / "HR Assessment.xlsx")
    state: dict = {"batch_id": "", "product_id": availo.id, "pending_upload": str(path), "steps": []}
    tool = {t.__name__: t for t in assistant._tools(user, state)}
    tool["open_questionnaire"]("")
    assert batches.load(state["batch_id"]).product_id == availo.id, "an upload takes the chat's product"

    searched: list[str] = []

    async def search(query, mode="hybrid", limit=8, *, team_id=None, product_id=""):
        searched.append(product_id)
        return {"results": []}

    monkeypatch.setattr(tools, "search", search)
    await tool["search_policies"]("backups")
    assert searched == [availo.id]

    conversation.batch_id = state["batch_id"]
    conversations.save(conversation)
    assistant.choose_product(user, conversation, "")
    assert conversations.load(conversation.id).product_id == ""
    assert batches.load(conversation.batch_id).product_id == "", "the chat's questionnaire follows it"
    with pytest.raises(ProductNotFound):
        assistant.choose_product(user, conversation, theirs.id)


@pytest.mark.asyncio
async def test_the_assistant_is_told_the_product_and_only_when_there_is_one(user, availo, monkeypatch) -> None:
    told: list[dict] = []

    class Agent:
        async def astream(self, payload, config=None, stream_mode=None):
            from langchain_core.messages import AIMessage

            yield {"messages": [*payload["messages"], AIMessage("Done.")]}

    def agent(tool_list, **named):
        told.append(named)
        return Agent()

    monkeypatch.setattr(assistant, "_agent", agent)
    await assistant.say(user, assistant.start(user, "", availo.id), "Which product is this?")
    await assistant.say(user, assistant.start(user, ""), "Hello")

    assert told == [{"product": "Availo"}, {}]
    assert "THIS CONVERSATION is for the product Availo." in FOR_PRODUCT.format(name="Availo")


# --- deleting a product ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_deleting_a_product_returns_its_questionnaires_and_chats_to_general(
    stores, user, availo, answering, tmp_path
) -> None:
    batch = tools.open_form(user, shapes.simple(tmp_path / "vendor.xlsx"), product_id=availo.id)
    await tools.answer(user, batch.id)
    written = batches.answers(batch.id)
    conversation = assistant.start(user, "Hello", availo.id)

    products.delete(identity.add_user("lead@example.test", role=roles.LEAD), TEAM, availo.id, confirm="confirm")

    assert batches.load(batch.id).product_id == ""
    assert batches.answers(batch.id) == written, "with their answers"
    assert conversations.load(conversation.id).product_id == ""


def test_a_version_12_database_upgrades_and_its_work_is_general() -> None:
    conn = store.connect()
    tables = [
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    ]
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript("".join(f"DROP TABLE IF EXISTS {name};" for name in tables))
    conn.execute("PRAGMA foreign_keys = ON")
    for index, step in enumerate(store.MIGRATIONS[:12]):
        getattr(store.migrations, step)(conn) if step.startswith("_") else conn.executescript(step)
        conn.execute(f"PRAGMA user_version = {index + 1}")
    conn.execute(
        "INSERT INTO form_batches (batch_id, team_id, actor_email, source_name, source_path, format, detected, "
        "created_at, updated_at) VALUES ('b1', ?, 'a@example.test', 'f.xlsx', 'f.xlsx', 'xlsx', '{}', 't', 't')",
        (TEAM,),
    )
    conn.execute(
        "INSERT INTO conversations (conversation_id, team_id, actor_email, created_at, updated_at) "
        "VALUES ('c1', ?, 'a@example.test', 't', 't')",
        (TEAM,),
    )
    conn.commit()
    store.reset_connection()

    upgraded = store.connect()
    assert upgraded.execute("PRAGMA user_version").fetchone()[0] == len(store.MIGRATIONS) >= 13
    assert upgraded.execute("SELECT product_id FROM form_batches WHERE batch_id = 'b1'").fetchone()[0] == ""
    assert upgraded.execute("SELECT product_id FROM conversations WHERE conversation_id = 'c1'").fetchone()[0] == ""


# --- the routes ----------------------------------------------------------------------


@pytest.fixture
def alice(availo) -> TestClient:
    identity.set_access_code(TEAM, CODE)
    identity.add_user(ALICE)
    client = TestClient(app)
    assert client.post("/api/auth/session", json={"email": ALICE, "code": CODE}).status_code == 200
    return client


def _upload(client: TestClient, path, **data):
    with open(path, "rb") as handle:
        return client.post(
            "/api/forms", files={"file": (path.name, handle.read(), "application/octet-stream")}, data=data
        )


def test_the_questionnaire_routes_take_and_show_the_product(stores, availo, alice, tmp_path) -> None:
    opened = _upload(alice, shapes.simple(tmp_path / "vendor.xlsx"), product=availo.id)
    assert opened.status_code == 200 and opened.json()["product_id"] == availo.id
    batch_id = opened.json()["id"]
    assert alice.get("/api/forms").json()["forms"][0]["product_id"] == availo.id

    changed = alice.post(f"/api/forms/{batch_id}/product", json={"product": ""})
    assert changed.status_code == 200 and changed.json()["product_id"] == ""
    assert alice.get(f"/api/forms/{batch_id}").json()["product_id"] == ""


@pytest.fixture
def chatting(monkeypatch) -> None:
    """The assistant configured, and each turn a reply with nothing done."""

    async def say(user, conversation, message, *, upload=None, run_id=""):
        return assistant.Turn(conversation_id=conversation.id, batch_id=conversation.batch_id, reply="Done.")

    monkeypatch.setattr(assistant, "configured", lambda: True)
    monkeypatch.setattr(assistant, "say", say)


def test_a_chat_starts_for_a_product_and_changes_by_its_own_route(stores, availo, alice, chatting) -> None:
    first = alice.post("/api/chat", json={"message": "Hello", "product": availo.id}).json()
    assert first["product_id"] == availo.id
    conversation_id = first["conversation_id"]
    kept = alice.post("/api/chat", json={"message": "Again", "conversation_id": conversation_id, "product": ""})
    assert kept.json()["product_id"] == availo.id, "a message only names the product of a chat it starts"

    changed = alice.post(f"/api/chat/{conversation_id}/product", json={"product": ""})
    assert changed.status_code == 200 and changed.json()["product_id"] == ""
    assert alice.get(f"/api/chat/{conversation_id}").json()["product_id"] == ""
    assert alice.get("/api/chat").json()["conversations"][0]["product_id"] == ""

    uploaded = alice.post(
        "/api/chat/upload",
        data={"message": "Read", "product": availo.id},
        files={"file": ("q.xlsx", b"not read", "application/octet-stream")},
    )
    assert uploaded.json()["product_id"] == availo.id, "an upload that starts a chat starts it for its product"


def test_another_teams_product_is_absent_from_every_route(stores, availo, theirs, alice, chatting, tmp_path) -> None:
    batch_id = _upload(alice, shapes.simple(tmp_path / "vendor.xlsx")).json()["id"]
    conversation_id = alice.post("/api/chat", json={"message": "Hello"}).json()["conversation_id"]
    question = {"id": "q1", "text": "Do you encrypt backups?"}
    for response in (
        _upload(alice, shapes.simple(tmp_path / "other.xlsx"), product=theirs.id),
        alice.post(f"/api/forms/{batch_id}/product", json={"product": theirs.id}),
        alice.get(f"/api/search?q=backups&product={theirs.id}"),
        alice.post("/api/assessments/answer-questions", json={"questions": [question], "product": theirs.id}),
        alice.post("/api/chat", json={"message": "Hello", "product": theirs.id}),
        alice.post(f"/api/chat/{conversation_id}/product", json={"product": theirs.id}),
        alice.post(
            "/api/chat/upload",
            data={"message": "Read", "product": theirs.id},
            files={"file": ("q.xlsx", b"not read", "application/octet-stream")},
        ),
    ):
        assert (response.status_code, response.json()["code"]) == (404, "product_not_found"), response.request.url
