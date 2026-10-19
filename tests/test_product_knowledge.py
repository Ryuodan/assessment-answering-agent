"""A product's knowledge base, beside the team's shared one (plan 021)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import answer_memory, batches, events, identity, knowledge, memory_sweep, products, roles, scoped_knowledge
from src import service, uploads
from src.api import app
from src.config import settings
from src.errors import ProductDeleted
from src.forms.model import DetectedForm
from src.graph import nodes
from src.identity import User
from src.models import IngestResult, Question, SourceType
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
            made[key]._store.delete_collection = lambda key=key: made.pop(key, None)
        return made[key]

    monkeypatch.setattr("src.knowledge.get_store", get_store)
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
    calls: list[tuple[str, dict, Path]] = []

    async def indexed(path, source_type, authority="ours", team_id=None, **scope):
        calls.append((path.name, scope, path.parent))
        return IngestResult(source_name=path.name, source_type=source_type, chunks_indexed=3)

    monkeypatch.setattr("src.routes.knowledge.service.ingest", indexed)
    upload = {"files": ("policy.pdf", b"%PDF-1.4 anything", "application/pdf")}
    assert alice.post("/api/knowledge/guidelines", files=upload).status_code == 200
    assert alice.post("/api/knowledge/guidelines", files=upload, data={"product": availo.id}).status_code == 200
    assert calls == [
        ("policy.pdf", {}, settings.team_upload_dir(TEAM)),
        ("policy.pdf", {"product_id": availo.id}, settings.product_upload_dir(TEAM, availo.id)),
    ], "a product's file is kept in its own folder, which goes with it"


def test_one_name_is_one_document_across_the_team_and_its_products(availo) -> None:
    """Answering merges evidence by file name, so two different files of one
    name, one shared and one a product's, would lose one of them from answers."""
    msegat = products.add(None, TEAM, "Msegat")
    shared = service.save_upload("Policy.pdf", b"shared", TEAM)
    differs = service.save_upload("Policy.pdf", b"availo's own", TEAM, product_id=availo.id)
    same = service.save_upload("Policy.pdf", b"shared", TEAM, product_id=msegat.id)

    assert shared == settings.team_upload_dir(TEAM) / "Policy.pdf"
    assert differs == settings.product_upload_dir(TEAM, availo.id) / "Policy (2).pdf"
    assert same == settings.product_upload_dir(TEAM, msegat.id) / "Policy.pdf", "the same bytes keep the name"

    service.save_upload("Standard.pdf", b"availo's standard", TEAM, product_id=availo.id)
    later = service.save_upload("Standard.pdf", b"the team's standard", TEAM)
    assert later == settings.team_upload_dir(TEAM) / "Standard (2).pdf", "checked from the shared side too"
    assert service.save_upload("Policy.pdf", b"availo's own", TEAM, product_id=availo.id) == differs


def test_removing_a_products_document_removes_its_file_and_a_shared_one_keeps_it(stores, availo, alice) -> None:
    shared = service.save_upload("Shared policy.pdf", b"%PDF-1.4 shared", TEAM)
    own = service.save_upload("Availo policy.pdf", b"%PDF-1.4 availo", TEAM, product_id=availo.id)
    other = service.save_upload("Availo standard.pdf", b"%PDF-1.4 standard", TEAM, product_id=availo.id)
    read_out = uploads.extracted_text_cache_path(own)
    read_out.parent.mkdir(parents=True, exist_ok=True)
    read_out.write_text("Availo's policy", encoding="utf-8")
    staged(knowledge.get_store(TEAM), shared.name, 0.9)
    staged(knowledge.get_store(TEAM, product_id=availo.id), own.name, 0.9)
    staged(knowledge.get_store(TEAM, product_id=availo.id), other.name, 0.9)

    assert alice.delete(f"/api/knowledge/sources/{own.name}?product={availo.id}").status_code == 200
    assert not own.exists() and not read_out.exists(), "the file and the text read out of it"
    assert other.exists(), "only the document removed"

    assert alice.delete("/api/knowledge/sources/Shared policy.pdf").status_code == 200
    assert shared.exists(), "a shared document's file stays, as it always has"

    assert alice.delete(f"/api/knowledge?product={availo.id}").status_code == 200
    assert uploads.document_files(settings.product_upload_dir(TEAM, availo.id)) == []
    assert alice.delete("/api/knowledge").status_code == 200
    assert shared.exists()


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


def test_deleting_a_product_removes_its_folder_and_the_text_read_from_its_files(stores, availo) -> None:
    lead = identity.find_user("lead@example.test")
    shared = service.save_upload("Shared policy.pdf", b"%PDF-1.4 shared", TEAM)
    own = service.save_upload("Availo policy.pdf", b"%PDF-1.4 availo", TEAM, product_id=availo.id)
    read_out = [uploads.extracted_text_cache_path(path) for path in (shared, own)]
    for cache in read_out:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text("the text read out of it", encoding="utf-8")

    deletion = products.delete(lead, TEAM, availo.id, confirm="confirm")

    assert not settings.product_upload_dir(TEAM, availo.id).exists()
    assert not read_out[1].exists(), "the text read out of its file goes too"
    assert shared.exists() and read_out[0].exists(), "the shared knowledge base's file is untouched"
    assert (deletion.files_removed, deletion.files_left) == (1, ())


def test_deleting_a_product_removes_its_files_from_before_it_had_a_folder(stores, availo) -> None:
    """Product files used to be kept in the team's folder. One only this product
    indexes goes; one that anything else still uses is kept."""
    lead = identity.find_user("lead@example.test")
    msegat = products.add(None, TEAM, "Msegat")
    folder = settings.team_upload_dir(TEAM)
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("Legacy.pdf", "Shared.pdf", "Both.pdf", "Claimed.pdf", "Unindexed.pdf"):
        (folder / name).write_bytes(b"%PDF-1.4 " + name.encode())
    for name in ("Legacy.pdf", "Shared.pdf", "Both.pdf", "Claimed.pdf"):
        staged(knowledge.get_store(TEAM, product_id=availo.id), name, 0.9)
    staged(knowledge.get_store(TEAM), "Shared.pdf", 0.9)
    staged(knowledge.get_store(TEAM, product_id=msegat.id), "Both.pdf", 0.9)
    batches.create(
        User(email=ALICE, team_id=TEAM), folder / "Claimed.pdf", DetectedForm(source_name="Claimed.pdf", format="xlsx")
    )

    counted = products.deletion_preview(TEAM, availo.id)["documents"]
    assert (counted["names"], counted["kept"]) == (["Legacy.pdf"], 3), "three are kept, and said to be"
    deletion = products.delete(lead, TEAM, availo.id, confirm="confirm")

    assert not (folder / "Legacy.pdf").exists()
    assert [path.name for path in uploads.document_files(folder)] == [
        "Both.pdf",
        "Claimed.pdf",
        "Shared.pdf",
        "Unindexed.pdf",
    ]
    assert deletion.files_removed == 1


def test_a_shared_file_of_the_same_name_as_a_products_own_is_not_taken_for_its_legacy_one(stores, availo) -> None:
    """The product's document is its own folder's copy; the team folder's file of
    that name is a shared upload the shared index no longer lists (it was cleared,
    and a cleared shared file stays). Deleting the product used to take it too."""
    lead = identity.find_user("lead@example.test")
    shared = service.save_upload("X.pdf", b"%PDF-1.4 the same", TEAM)
    own = service.save_upload("X.pdf", b"%PDF-1.4 the same", TEAM, product_id=availo.id)
    staged(knowledge.get_store(TEAM, product_id=availo.id), "X.pdf", 0.9)

    counted = products.deletion_preview(TEAM, availo.id)["documents"]
    assert (counted["files"], counted["names"], counted["kept"]) == (1, ["X.pdf"], 1), "counted once; the team's stays"
    assert products.delete(lead, TEAM, availo.id, confirm="confirm").files_removed == 1

    assert shared.exists() and not own.exists()


# --- a product's files from before it had a folder, removed and cleared (plan 027) ----


def legacy(*names: str) -> list[Path]:
    """Files in the team's folder that only Availo's knowledge base indexes, as every product file was before."""
    folder = settings.team_upload_dir(TEAM)
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"%PDF-1.4 " + name.encode())
    return [folder / name for name in names]


def test_removing_a_products_document_from_before_it_had_a_folder_removes_its_file(stores, availo, alice) -> None:
    lead = identity.find_user("lead@example.test")
    old, other, shared = legacy("Old policy.pdf", "Old standard.pdf", "Shared.pdf")
    read_out = uploads.extracted_text_cache_path(old)
    read_out.parent.mkdir(parents=True, exist_ok=True)
    read_out.write_text("the old policy", encoding="utf-8")
    for path in (old, other, shared):
        staged(knowledge.get_store(TEAM, product_id=availo.id), path.name, 0.9)
    staged(knowledge.get_store(TEAM), "Shared.pdf", 0.9)

    removed = alice.delete(f"/api/knowledge/sources/{old.name}?product={availo.id}")
    assert removed.json() == {"deleted": old.name, "files_left": []}
    assert not old.exists() and not read_out.exists(), "its file and the text read out of it"
    assert other.exists(), "only the document removed"
    assert alice.delete(f"/api/knowledge/sources/Shared.pdf?product={availo.id}").status_code == 200
    assert shared.exists(), "the shared knowledge base still uses it"
    assert [doc["name"] for doc in service.list_documents(TEAM)] == ["Old standard.pdf", "Shared.pdf"]

    # Deleting the product afterwards still finds the one it has left.
    deletion = products.delete(lead, TEAM, availo.id, confirm="confirm")
    assert deletion.files_removed == 1 and not other.exists()
    assert shared.exists()


def test_clearing_a_products_knowledge_base_removes_its_files_from_before_it_had_a_folder(
    stores, availo, alice
) -> None:
    msegat = products.add(None, TEAM, "Msegat")
    old, both, claimed, shared = legacy("Old.pdf", "Both.pdf", "Claimed.pdf", "Shared.pdf")
    own = service.save_upload("New.pdf", b"%PDF-1.4 new", TEAM, product_id=availo.id)
    for name in ("Old.pdf", "Both.pdf", "Claimed.pdf", "Shared.pdf", "New.pdf"):
        staged(knowledge.get_store(TEAM, product_id=availo.id), name, 0.9)
    staged(knowledge.get_store(TEAM, product_id=msegat.id), "Both.pdf", 0.9)
    staged(knowledge.get_store(TEAM), "Shared.pdf", 0.9)
    batches.create(User(email=ALICE, team_id=TEAM), claimed, DetectedForm(source_name="Claimed.pdf", format="xlsx"))

    assert alice.delete(f"/api/knowledge?product={availo.id}").json() == {"cleared": True, "files_left": []}

    assert not old.exists() and not own.exists()
    assert both.exists() and claimed.exists() and shared.exists(), "kept: another product, a questionnaire, Shared"


def test_a_file_that_cannot_be_removed_is_reported_by_remove_and_clear(stores, availo, alice, monkeypatch) -> None:
    [stuck] = legacy("Old.pdf")
    own = service.save_upload("New.pdf", b"%PDF-1.4 new", TEAM, product_id=availo.id)
    for name in ("Old.pdf", "New.pdf"):
        staged(knowledge.get_store(TEAM, product_id=availo.id), name, 0.9)
    unlink = Path.unlink

    def in_use(path, missing_ok=False):
        if path.name in ("Old.pdf", "New.pdf"):
            raise PermissionError("open in another program")
        return unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", in_use)

    removed = alice.delete(f"/api/knowledge/sources/New.pdf?product={availo.id}").json()
    assert removed == {"deleted": "New.pdf", "files_left": ["New.pdf"]}
    cleared = alice.delete(f"/api/knowledge?product={availo.id}").json()
    assert cleared == {"cleared": True, "files_left": ["New.pdf", "Old.pdf"]}, "the one still there, and the old one"
    assert stuck.exists() and own.exists()


def test_a_product_upload_that_did_not_go_in_leaves_no_file(stores, availo, alice, monkeypatch) -> None:
    """A product's folder holds its knowledge base and nothing else; a file kept
    there that is not in it was listed with its badge and nothing could remove it."""
    outcomes = {
        "Broken.pdf": {"error": "Could not read it."},
        "Copy.pdf": {"duplicate_of": "Policy.pdf"},
        "Policy.pdf": {"chunks_indexed": 3},
    }

    async def indexed(path, source_type, authority="ours", team_id=None, **scope):
        return IngestResult(
            **{"source_name": path.name, "source_type": source_type, "chunks_indexed": 0} | outcomes[path.name]
        )

    monkeypatch.setattr("src.routes.knowledge.service.ingest", indexed)
    files = [("files", (name, b"%PDF-1.4 " + name.encode(), "application/pdf")) for name in outcomes]
    assert alice.post("/api/knowledge/guidelines", files=files, data={"product": availo.id}).status_code == 200

    folder = settings.product_upload_dir(TEAM, availo.id)
    assert [path.name for path in uploads.document_files(folder)] == ["Policy.pdf"]
    assert alice.post("/api/knowledge/guidelines", files=files).status_code == 200
    assert len(uploads.document_files(settings.team_upload_dir(TEAM))) == 3, "the shared knowledge base as before"


# --- a deleted product's knowledge base is never made again (plan 027) ------------------


@pytest.mark.asyncio
async def test_a_deleted_products_knowledge_base_is_not_made_again(stores, availo, monkeypatch) -> None:
    """Its questionnaires, chats and remembered answers keep its id, and asking for
    its knowledge base built an empty collection that nothing would drop again."""
    lead = identity.find_user("lead@example.test")
    entry = answer_memory.record("Is MFA enforced?", "Yes.", team_id=TEAM, product_id=availo.id, index=False)
    products.delete(lead, TEAM, availo.id, confirm="confirm")
    assert (TEAM, availo.id) not in stores

    for ask in (
        lambda: scoped_knowledge.own_store(TEAM, availo.id),
        lambda: scoped_knowledge.store_for(TEAM, availo.id),
        lambda: scoped_knowledge.knowledge_stats(TEAM, product_id=availo.id),
    ):
        with pytest.raises(ProductDeleted, match="Availo was deleted"):
            ask()
    with pytest.raises(ProductDeleted):
        await service.search_knowledge("backups", team_id=TEAM, product_id=availo.id)
    with pytest.raises(ProductDeleted):
        await memory_sweep.scan(entry)

    def no_model(*args, **kwargs):
        raise AssertionError("a model was called")

    monkeypatch.setattr(settings, "query_expansion", False)
    monkeypatch.setattr(nodes, "chat_llm", no_model)
    monkeypatch.setattr(nodes, "structured_llm", no_model)
    [answered] = await service.answer_questions(
        [Question(id="q1", text="Backups?")], team_id=TEAM, product_id=availo.id
    )
    assert "Availo was deleted" in answered.error

    assert (TEAM, availo.id) not in stores, "never made again"
    assert scoped_knowledge.store_for(TEAM) is knowledge.get_store(TEAM), "the shared one is untouched"


def test_a_file_that_cannot_be_removed_does_not_stop_the_delete(stores, availo, monkeypatch, caplog) -> None:
    lead = identity.find_user("lead@example.test")
    stuck = service.save_upload("Availo policy.pdf", b"%PDF-1.4 availo", TEAM, product_id=availo.id)
    unlink = Path.unlink

    def in_use(path, missing_ok=False):
        if path == stuck:
            raise PermissionError("open in another program")
        return unlink(path, missing_ok=missing_ok)

    def cannot(path, *args, **kwargs):
        raise PermissionError("open in another program")

    monkeypatch.setattr(Path, "unlink", in_use)
    monkeypatch.setattr(uploads.shutil, "rmtree", cannot)

    deletion = products.delete(lead, TEAM, availo.id, confirm="confirm")

    assert products.list_products(TEAM) == [], "the product is deleted all the same"
    assert (deletion.files_removed, deletion.files_left) == (0, ("Availo policy.pdf",))
    recorded = events.for_subject("product", availo.id)[-1]
    assert (recorded.kind, recorded.payload["files_left"]) == (events.PRODUCT_DELETED, ["Availo policy.pdf"])
    assert "products.files_remove_failed" in caplog.text
    assert stuck.exists()
    assert "Availo policy.pdf" not in [doc["name"] for doc in service.list_documents(TEAM)], "nothing lists it"
    with pytest.raises(FileNotFoundError):
        service.resolve_document("uploaded", "uploaded", "Availo policy.pdf", TEAM)


def test_the_shared_collection_cannot_be_dropped() -> None:
    with pytest.raises(ValueError, match="never a team's shared one"):
        knowledge.drop_store(TEAM, "")
