"""A product's knowledge base, beside the team's shared one (plan 021)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from src import identity, knowledge, products, roles, scoped_knowledge, service
from src.api import app
from src.config import settings
from src.models import IngestResult, SourceType
from src.vector_names import collection_for
from tests.conftest import FakeDocument, FakeVectorStore, bare_store

TEAM = settings.default_team
CODE = "TEAM-CODE-FOR-TESTS"
ALICE = "alice@example.test"
CHROMA_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,61}[a-zA-Z0-9]$")


@pytest.fixture
def stores(monkeypatch):
    """A fake index per (team, product), reached however the code asks for one."""
    made: dict[tuple[str, str], knowledge.KnowledgeStore] = {}

    def get_store(team_id=None, *, product_id=""):
        key = (team_id or TEAM, product_id)
        if key not in made:
            made[key] = bare_store(FakeVectorStore([]))
            made[key].team_id, made[key].product_id = key
        return made[key]

    monkeypatch.setattr("src.knowledge.get_store", get_store)
    monkeypatch.setattr("src.service.get_store", get_store)
    return made


@pytest.fixture
def availo():
    identity.ensure_team(TEAM)
    lead = identity.add_user("lead@example.test", role=roles.LEAD)
    return products.add(lead, TEAM, "Availo")


def staged(store: knowledge.KnowledgeStore, name: str, score: float) -> None:
    store._store._staged = [(FakeDocument(f"{name} text", {"source_name": name, "source_type": "guideline"}), score)]
    store._store.records.append(
        {"text": f"{name} text", "metadata": {"source_name": name, "source_type": "guideline"}, "id": name}
    )


# --- naming ------------------------------------------------------------------------


@pytest.mark.parametrize("team", [settings.default_team, "privacy", "t2.data_office", "9" * 64])
def test_a_products_collection_is_valid_and_its_own(team: str) -> None:
    product = collection_for(team, "dafd8a7b3fae")
    assert CHROMA_NAME.match(product), product
    assert product != collection_for(team), "never the team's shared collection"
    assert product != collection_for(team, "013b9e76fb60"), "nor another product's"
    assert product != collection_for(team + "x", "dafd8a7b3fae"), "nor the same product id in another team"
    assert collection_for(settings.default_team) == settings.collection_name, "the shared one keeps its name"


# --- searching ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_products_search_reads_its_own_material_first_then_the_shared(stores, availo) -> None:
    shared = knowledge.get_store(TEAM)
    own = knowledge.get_store(TEAM, product_id=availo.id)
    staged(shared, "Shared policy.pdf", 0.9)
    staged(own, "Availo policy.pdf", 0.6)

    scoped = scoped_knowledge.store_for(TEAM, availo.id)
    found = await scoped.search_types("encryption", [(SourceType.GUIDELINE, 5)])

    assert [e.source_name for e in found[SourceType.GUIDELINE]] == ["Availo policy.pdf", "Shared policy.pdf"]
    assert shared.embedded == ["encryption"] and own.embedded == [], "one embedding, used for both"
    assert own._store.searched_vectors == shared._store.searched_vectors
    assert scoped.counts_by_type() == {"guideline": 2}


def test_general_is_the_shared_store_itself(stores) -> None:
    assert scoped_knowledge.store_for(TEAM) is knowledge.get_store(TEAM)


# --- the routes ------------------------------------------------------------------------


@pytest.fixture
def alice(availo) -> TestClient:
    identity.set_access_code(TEAM, CODE)
    identity.add_user(ALICE)
    client = TestClient(app)
    assert client.post("/api/auth/session", json={"email": ALICE, "code": CODE}).status_code == 200
    return client


def test_uploads_go_to_the_knowledge_base_chosen(stores, availo, alice, monkeypatch, tmp_path) -> None:
    calls: list[tuple[str, dict]] = []

    async def indexed(path, source_type, authority="ours", team_id=None, **scope):
        calls.append((path.name, scope))
        return IngestResult(source_name=path.name, source_type=source_type, chunks_indexed=3)

    monkeypatch.setattr("src.routes.knowledge.service.ingest", indexed)
    upload = {"files": ("policy.pdf", b"%PDF-1.4 anything", "application/pdf")}
    assert alice.post("/api/knowledge/guidelines", files=upload).status_code == 200
    assert alice.post("/api/knowledge/guidelines", files=upload, data={"product": availo.id}).status_code == 200
    assert calls == [("policy.pdf", {}), ("policy.pdf", {"product_id": availo.id})]


def names(body: dict) -> list[str]:
    return [source["name"] for source in body["sources"]]


def test_listing_removing_and_clearing_touch_only_the_knowledge_base_chosen(stores, availo, alice) -> None:
    staged(knowledge.get_store(TEAM), "Shared policy.pdf", 0.9)
    staged(knowledge.get_store(TEAM, product_id=availo.id), "Availo policy.pdf", 0.9)

    assert names(alice.get("/api/knowledge").json()) == ["Shared policy.pdf"]
    assert names(alice.get(f"/api/knowledge?product={availo.id}").json()) == ["Availo policy.pdf"]

    assert alice.delete(f"/api/knowledge/sources/Shared policy.pdf?product={availo.id}").status_code == 404
    assert alice.delete(f"/api/knowledge/sources/Availo policy.pdf?product={availo.id}").status_code == 200
    assert names(alice.get(f"/api/knowledge?product={availo.id}").json()) == []
    assert names(alice.get("/api/knowledge").json()) == ["Shared policy.pdf"], "the shared one is untouched"

    staged(knowledge.get_store(TEAM, product_id=availo.id), "Availo standard.pdf", 0.9)
    assert alice.delete(f"/api/knowledge?product={availo.id}").status_code == 200
    assert names(alice.get(f"/api/knowledge?product={availo.id}").json()) == []
    assert names(alice.get("/api/knowledge").json()) == ["Shared policy.pdf"]


def test_another_teams_product_is_absent(stores, availo, alice) -> None:
    identity.ensure_team("privacy")
    theirs = products.add(None, "privacy", "Their product")
    for response in (
        alice.get(f"/api/knowledge?product={theirs.id}"),
        alice.delete(f"/api/knowledge?product={theirs.id}"),
        alice.post(
            "/api/knowledge/guidelines",
            files={"files": ("a.pdf", b"%PDF-1.4", "application/pdf")},
            data={"product": theirs.id},
        ),
    ):
        assert (response.status_code, response.json()["code"]) == (404, "product_not_found")


@pytest.mark.asyncio
async def test_ingest_indexes_into_the_products_own_store(stores, availo, monkeypatch, tmp_path) -> None:
    async def text_of(path):
        return "1. Scope\nAll laptops encrypt their disks with AES-256."

    monkeypatch.setattr(service, "extracted_document_text", text_of)
    policy = tmp_path / "Availo disk policy.pdf"
    policy.write_bytes(b"%PDF-1.4 anything")

    result = await service.ingest(policy, SourceType.GUIDELINE, team_id=TEAM, product_id=availo.id)

    assert result.chunks_indexed > 0
    assert knowledge.get_store(TEAM, product_id=availo.id)._store.records, "indexed into the product's store"
    assert not knowledge.get_store(TEAM)._store.records, "and not into the shared one"


# --- deleting the product takes its knowledge base -----------------------------------


def test_deleting_a_product_deletes_its_collection_in_chroma(availo) -> None:
    """Against real Chroma (in the test's temporary directory): the fakes cannot
    show that `delete_collection` is the call Chroma actually has."""
    lead = identity.find_user("lead@example.test")
    store = knowledge.get_store(TEAM, product_id=availo.id)
    name = store._store._collection.name
    client = store._store._client
    assert name in [c.name for c in client.list_collections()]

    products.delete(lead, TEAM, availo.id, confirm="confirm")

    assert name not in [c.name for c in client.list_collections()]
    assert knowledge.get_store(TEAM, product_id=availo.id) is not store, "the store was forgotten too"
    knowledge.get_store.cache_clear()


def test_the_shared_collection_cannot_be_dropped() -> None:
    with pytest.raises(ValueError, match="never a team's shared one"):
        knowledge.drop_store(TEAM, "")
