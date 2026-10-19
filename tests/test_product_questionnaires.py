"""Questionnaires and chats carry a product, and answering uses it (plan 023)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from src import answer_memory, batches, conversations, identity, knowledge, products, roles, service, store, tools
from src.agents import assistant
from src.agents.assistant_prompt import FOR_PRODUCT
from src.api import app
from src.config import settings
from src.errors import ProductLocked, ProductNotFound
from src.graph import nodes, workflow
from src.models import AnsweredQuestion, Evidence, Question, SourceType
from src.prompts import PRODUCT_SOURCES_NOTE, format_sources_block
from src.schemas import AnswerReview, DraftedAnswer
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
async def test_a_questionnaire_is_answered_for_its_product_which_is_fixed(
    stores, user, availo, theirs, answering, tmp_path
) -> None:
    """TD-040: a questionnaire's product is fixed when the file is opened. Switched
    to General before approving, an answer drafted from one product's material
    went into the shared memory."""
    path = shapes.simple(tmp_path / "vendor.xlsx")
    batch = tools.open_form(user, path, product_id=availo.id)
    assert batch.product_id == availo.id
    assert tools.inspect(user, batch.id)["product_id"] == availo.id
    assert batches.recent(TEAM, actor_email=user.email)[0]["product_id"] == availo.id

    await tools.answer(user, batch.id)
    assert answering[-1]["product_id"] == availo.id
    written = batches.answers(batch.id)

    with pytest.raises(ProductLocked) as locked:
        tools.set_product(user, batch.id, "")
    assert (locked.value.code, locked.value.status) == ("product_locked", 409)
    assert tools.inspect(user, batch.id)["product_id"] == availo.id
    assert batches.answers(batch.id) == written, "the answers are as they were"
    assert tools.set_product(user, batch.id, availo.id).product_id == availo.id, "its own product is accepted"

    general = tools.open_form(user, path)
    with pytest.raises(ProductLocked):
        tools.set_product(user, general.id, availo.id)
    await tools.answer(user, general.id)
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


@pytest.mark.asyncio
async def test_the_drafter_and_reviewer_see_product_sources_marked_and_shared_ones_not(monkeypatch) -> None:
    """TD-040, as decided: the product's own evidence is marked FOR THIS PRODUCT,
    shared evidence carries no mark, and the reviewer checks the draft against
    the same marked list the drafter wrote it from."""
    told: list[str] = []

    class Model:
        def __init__(self, schema):
            self.schema = schema

        async def ainvoke(self, messages):
            told.append(dict(messages)["user"])
            if self.schema is DraftedAnswer:
                return DraftedAnswer(answer="No.", confidence=0.8, used_source_ids=[1])
            return AnswerReview(grounded=True, confidence=0.8)

    monkeypatch.setattr(nodes, "structured_llm", lambda schema, temperature=None: Model(schema))
    own = Evidence(
        source_type=SourceType.GUIDELINE, source_name="Availo.pdf", snippet="Not encrypted.", product_id="p1", score=0.8
    )
    prior = Evidence(
        source_type=SourceType.PRIOR_ANSWER, source_name="memory", snippet="No.", product_id="p1", score=0.8
    )
    shared = Evidence(
        source_type=SourceType.GUIDELINE, source_name="Shared.pdf", snippet="Backups are encrypted.", score=0.8
    )
    state: dict = {"question": Question(id="q1", text="Are backups encrypted?"), "language": "en"}

    drafted = await nodes.draft({**state, "evidence": [own, prior, shared]})
    await nodes.review({**state, "evidence": [own, prior, shared], **drafted})
    drafter, reviewer = told
    assert PRODUCT_SOURCES_NOTE in drafter
    assert "OUR POLICY, FOR THIS PRODUCT — Availo.pdf" in drafter
    assert "PREVIOUS ANSWER, FOR THIS PRODUCT —" in drafter
    assert "] OUR POLICY — Shared.pdf" in drafter
    assert format_sources_block(nodes._sources({**state, "evidence": [own, prior, shared]})) in reviewer
    assert format_sources_block(nodes._sources({**state, "evidence": [own, prior, shared]})) in drafter

    told.clear()
    await nodes.draft({**state, "evidence": [shared]})
    assert PRODUCT_SOURCES_NOTE not in told[0] and "FOR THIS PRODUCT" not in told[0], "General's is as it was"


def test_an_approved_answer_is_remembered_for_the_questionnaires_product(stores, user, availo, tmp_path) -> None:
    batch = tools.open_form(user, shapes.simple(tmp_path / "vendor.xlsx"), product_id=availo.id)
    question = next(q for q in batch.form.questions if q.writable)
    tools.set_answer(user, batch.id, question.id, "Yes, every backup is encrypted.")

    entry_id = tools.approve_answer(user, batch.id, question.id)
    assert answer_memory.get(entry_id, TEAM).product_id == availo.id
    assert indexed(knowledge.get_store(TEAM, product_id=availo.id)) == [entry_id]
    assert indexed(knowledge.get_store(TEAM)) == []

    with pytest.raises(ProductLocked):
        tools.set_product(user, batch.id, "")
    assert tools.approve_answer(user, batch.id, question.id) == entry_id
    assert answer_memory.get(entry_id, TEAM).product_id == availo.id, "approved again, it stays where it was"
    assert indexed(knowledge.get_store(TEAM, product_id=availo.id)) == [entry_id]

    # Moved to the shared memory on the memory page, then approved again in its
    # questionnaire: it goes back to the questionnaire's product.
    answer_memory.move(entry_id, "", TEAM)
    assert indexed(knowledge.get_store(TEAM)) == [entry_id]
    assert tools.approve_answer(user, batch.id, question.id) == entry_id
    assert answer_memory.get(entry_id, TEAM).product_id == availo.id
    assert indexed(knowledge.get_store(TEAM, product_id=availo.id)) == [entry_id]
    assert indexed(knowledge.get_store(TEAM)) == []


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
    with pytest.raises(ProductLocked):
        assistant.choose_product(user, conversation, "")
    assert conversations.load(conversation.id).product_id == availo.id, "a chat's product is fixed (TD-040)"
    assert batches.load(conversation.batch_id).product_id == availo.id, "and so is its questionnaire's"
    assistant.choose_product(user, conversation, availo.id)  # its own: accepted, and nothing changes
    assert conversations.load(conversation.id).product_id == availo.id
    with pytest.raises(ProductNotFound):
        assistant.choose_product(user, conversation, theirs.id)


@pytest.mark.asyncio
async def test_every_upload_in_a_product_chat_is_opened_for_the_chats_product(stores, user, availo, tmp_path) -> None:
    """A chat never takes over a questionnaire opened elsewhere: each file attached
    to it is opened afresh, for the chat's product, so the two cannot differ."""
    path = shapes.status_and_comment(tmp_path / "HR Assessment.xlsx")
    general = tools.open_form(user, path)
    state: dict = {"batch_id": "", "product_id": availo.id, "pending_upload": str(path), "steps": []}
    tool = {t.__name__: t for t in assistant._tools(user, state)}

    tool["open_questionnaire"]("")
    first = state["batch_id"]
    assert first != general.id and batches.load(first).product_id == availo.id
    assert batches.load(general.id).product_id == "", "the one opened as General stays General"

    state["pending_upload"] = str(path)
    tool["open_questionnaire"]("")
    assert state["batch_id"] not in (first, general.id), "the chat follows its latest upload"
    assert batches.load(state["batch_id"]).product_id == availo.id


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
    told_about = FOR_PRODUCT.format(name="Availo")
    assert "THIS CONVERSATION is for the product Availo." in told_about
    assert "marking Availo's own clauses FOR THIS\nPRODUCT" in told_about
    assert "is fixed; to work on another product the\nperson starts a new chat" in told_about


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


def test_a_turn_that_outlives_a_products_deletion_does_not_bring_it_back(stores, user, availo) -> None:
    """A turn saves the conversation it loaded when the message arrived. Saving
    its product too wrote a product deleted during the turn back over General,
    and with the product fixed nothing could put that right."""
    conversation = assistant.start(user, "Hello", availo.id)
    stale = conversations.load(conversation.id)

    products.delete(identity.add_user("lead@example.test", role=roles.LEAD), TEAM, availo.id, confirm="confirm")
    stale.messages = [HumanMessage("Hello"), AIMessage("Hello again.")]
    conversations.save(stale)

    saved = conversations.load(conversation.id)
    assert saved.product_id == "" and [m.content for m in saved.messages] == ["Hello", "Hello again."]


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

    refused = alice.post(f"/api/forms/{batch_id}/product", json={"product": ""})
    assert (refused.status_code, refused.json()["code"]) == (409, "product_locked")
    assert "close it and open the file again" in refused.json()["detail"]
    assert alice.get(f"/api/forms/{batch_id}").json()["product_id"] == availo.id
    same = alice.post(f"/api/forms/{batch_id}/product", json={"product": availo.id})
    assert same.status_code == 200 and same.json()["product_id"] == availo.id


@pytest.fixture
def chatting(monkeypatch) -> None:
    """The assistant configured, and each turn a reply with nothing done."""

    async def say(user, conversation, message, *, upload=None, run_id=""):
        return assistant.Turn(conversation_id=conversation.id, batch_id=conversation.batch_id, reply="Done.")

    monkeypatch.setattr(assistant, "configured", lambda: True)
    monkeypatch.setattr(assistant, "say", say)


def test_a_chat_starts_for_a_product_and_keeps_it(stores, availo, alice, chatting) -> None:
    first = alice.post("/api/chat", json={"message": "Hello", "product": availo.id}).json()
    assert first["product_id"] == availo.id
    conversation_id = first["conversation_id"]
    kept = alice.post("/api/chat", json={"message": "Again", "conversation_id": conversation_id, "product": ""})
    assert kept.json()["product_id"] == availo.id, "a message only names the product of a chat it starts"

    refused = alice.post(f"/api/chat/{conversation_id}/product", json={"product": ""})
    assert (refused.status_code, refused.json()["code"]) == (409, "product_locked")
    assert "start a new chat" in refused.json()["detail"]
    assert alice.get(f"/api/chat/{conversation_id}").json()["product_id"] == availo.id
    assert alice.get("/api/chat").json()["conversations"][0]["product_id"] == availo.id
    same = alice.post(f"/api/chat/{conversation_id}/product", json={"product": availo.id})
    assert same.status_code == 200 and same.json()["product_id"] == availo.id

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
