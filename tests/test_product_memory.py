"""A product's answer memory, beside the team's shared one (plan 022)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import answer_memory, identity, knowledge, memory_sweep, products, roles, store
from src.api import app
from src.config import settings
from src.models import Evidence, SourceType
from tests.conftest import FakeVectorStore, bare_store

TEAM = settings.default_team
CODE = "TEAM-CODE-FOR-TESTS"
ALICE = "alice@example.test"


@pytest.fixture
def stores(monkeypatch):
    """A fake index per (team, product); a search finds the entries of its own memory only."""
    made: dict[tuple[str, str], knowledge.KnowledgeStore] = {}

    def get_store(team_id=None, *, product_id=""):
        key = (team_id or TEAM, product_id)
        if key not in made:
            made[key] = bare_store(FakeVectorStore([]))
            made[key].team_id, made[key].product_id = key
            made[key]._store.delete_collection = lambda key=key: made.pop(key, None)
        return made[key]

    async def search(self, query, source_type, k, expand=True):
        own = answer_memory.entries(product_id=self.product_id, limit=50)
        return [
            Evidence(
                source_type=SourceType.PRIOR_ANSWER,
                source_name="memory",
                snippet=e.answer,
                score=0.93,
                entry_id=e.entry_id,
            )
            for e in own
        ]

    async def everyone(question, candidates):
        return candidates

    monkeypatch.setattr("src.knowledge.get_store", get_store)
    monkeypatch.setattr("src.knowledge.KnowledgeStore.search", search)
    monkeypatch.setattr(memory_sweep, "_close_questions", everyone)
    monkeypatch.setattr(memory_sweep, "_same_question", everyone)
    return made


@pytest.fixture
def availo():
    identity.ensure_team(TEAM)
    return products.add(None, TEAM, "Availo")


def ids(entries) -> set[str]:
    return {entry.entry_id for entry in entries}


def test_an_answer_belongs_to_one_memory(stores, availo) -> None:
    shared = answer_memory.record("Do you encrypt backups?", "Yes, with AES-256.")
    own = answer_memory.record("Do you encrypt backups?", "Yes, with a key per tenant.", product_id=availo.id)

    assert (shared.product_id, own.product_id) == ("", availo.id)
    assert ids(answer_memory.entries(product_id="")) == {shared.entry_id}
    assert ids(answer_memory.entries(product_id=availo.id)) == {own.entry_id}
    assert ids(answer_memory.entries()) == {shared.entry_id, own.entry_id}, "left out, every memory"
    assert answer_memory.stats(TEAM, availo.id)["entries"] == 1
    assert answer_memory.count(product_id="") == 1

    product_index = knowledge.get_store(TEAM, product_id=availo.id)._store.records
    shared_index = knowledge.get_store(TEAM)._store.records
    assert [r["metadata"]["entry_id"] for r in product_index] == [own.entry_id]
    assert [r["metadata"]["entry_id"] for r in shared_index] == [shared.entry_id]


@pytest.mark.asyncio
async def test_a_product_answer_that_differs_from_a_shared_one_is_not_a_disagreement(stores, availo) -> None:
    answer_memory.record("Is data stored outside Saudi Arabia?", "No, all data stays in-country.")
    answer_memory.record("Is data stored outside Saudi Arabia?", "Yes, backups go to Frankfurt.", product_id=availo.id)
    await answer_memory.scan_pending(team_id=TEAM)
    assert answer_memory.conflicts(team_id=TEAM) == [], "different memories, so the product's own answer"

    # The same two answers inside one memory are a disagreement, as before.
    answer_memory.record("Is data stored outside Saudi Arabia?", "Yes, backups go to Frankfurt.")
    await answer_memory.scan_pending(team_id=TEAM)
    assert len(answer_memory.conflicts(team_id=TEAM, product_id="")) == 1
    assert answer_memory.conflicts(team_id=TEAM, product_id=availo.id) == []


def test_an_answer_moves_between_memories_and_is_compared_again(stores, availo) -> None:
    entry = answer_memory.record("Is MFA enforced?", "Yes, for every account.", scanned=True)
    assert entry.entry_id not in ids(answer_memory.pending(team_id=TEAM))

    moved = answer_memory.move(entry.entry_id, availo.id, TEAM)

    assert moved.product_id == availo.id
    assert knowledge.get_store(TEAM)._store.records == [], "out of the shared index"
    assert [r["metadata"]["entry_id"] for r in knowledge.get_store(TEAM, product_id=availo.id)._store.records] == [
        entry.entry_id
    ]
    assert entry.entry_id in ids(answer_memory.pending(team_id=TEAM)), "to be compared with its new neighbours"
    assert answer_memory.move(entry.entry_id, "", TEAM).product_id == ""


def test_deleting_a_product_forgets_its_answers_and_their_disagreements(stores, availo) -> None:
    keep = answer_memory.record("Is MFA enforced?", "Yes.")
    first = answer_memory.record("Is MFA enforced?", "Yes.", product_id=availo.id)
    second = answer_memory.record("Is MFA enforced?", "No.", product_id=availo.id)
    answer_memory.raise_conflict(first.entry_id, second.entry_id, "they disagree", team_id=TEAM)
    lead = identity.add_user("lead@example.test", role=roles.LEAD)

    products.delete(lead, TEAM, availo.id, confirm="confirm")

    assert ids(answer_memory.entries()) == {keep.entry_id}
    assert answer_memory.conflicts(team_id=TEAM, open_only=False) == []
    assert (TEAM, availo.id) not in stores, "and its collection"


# --- the routes -------------------------------------------------------------------


@pytest.fixture
def alice(availo) -> TestClient:
    identity.set_access_code(TEAM, CODE)
    identity.add_user(ALICE)
    client = TestClient(app)
    assert client.post("/api/auth/session", json={"email": ALICE, "code": CODE}).status_code == 200
    return client


def test_the_routes_read_and_write_the_memory_chosen(stores, availo, alice) -> None:
    taught = alice.post(
        "/api/memory", json={"question": "Do you pen-test?", "answer": "Yes, yearly.", "product": availo.id}
    ).json()
    assert taught["product_id"] == availo.id
    alice.post("/api/memory", json={"question": "Do you pen-test?", "answer": "Yes, twice a year."})

    shared = alice.get("/api/memory").json()
    own = alice.get(f"/api/memory?product={availo.id}").json()
    assert [e["answer"] for e in shared["entries"]] == ["Yes, twice a year."]
    assert [e["answer"] for e in own["entries"]] == ["Yes, yearly."]
    assert (shared["stats"]["entries"], own["stats"]["entries"]) == (1, 1)

    moved = alice.post(f"/api/memory/{taught['entry_id']}/move", json={"product": ""})
    assert moved.status_code == 200 and moved.json()["product_id"] == ""
    assert len(alice.get("/api/memory").json()["entries"]) == 2
    missing = alice.post("/api/memory/nope/move", json={"product": ""})
    assert (missing.status_code, missing.json()["code"]) == (404, "memory_entry_not_found")
    assert alice.get(f"/api/memory/conflicts?product={availo.id}").json() == {"conflicts": []}


def test_another_teams_product_is_absent_from_the_memory_routes(stores, availo, alice) -> None:
    identity.ensure_team("privacy")
    theirs = products.add(None, "privacy", "Theirs")
    entry = answer_memory.record("Q?", "A.", team_id=TEAM)
    for response in (
        alice.get(f"/api/memory?product={theirs.id}"),
        alice.get(f"/api/memory/conflicts?product={theirs.id}"),
        alice.post("/api/memory", json={"question": "Q?", "answer": "A.", "product": theirs.id}),
        alice.post(f"/api/memory/{entry.entry_id}/move", json={"product": theirs.id}),
    ):
        assert (response.status_code, response.json()["code"]) == (404, "product_not_found")


def test_a_shared_answer_moved_into_a_product_is_counted_and_forgotten_with_it(stores, availo, alice) -> None:
    """As the user confirmed (TD-040): an answer moved in from Shared is the
    product's now, and goes with it rather than back to Shared. The warning
    before the delete counts it, so it is not forgotten silently."""
    entry = answer_memory.record("Is MFA enforced?", "Yes, for every account.", team_id=TEAM)
    answer_memory.record("Do you pen-test?", "Yes, yearly.", team_id=TEAM, product_id=availo.id)
    assert alice.post(f"/api/memory/{entry.entry_id}/move", json={"product": availo.id}).status_code == 200
    assert products.deletion_preview(TEAM, availo.id)["answers"] == {"remembered": 2, "moved_from_shared": 1}

    lead = identity.add_user("lead@example.test", role=roles.LEAD)
    deletion = products.delete(lead, TEAM, availo.id, confirm="confirm")

    assert (deletion.answers_forgotten, deletion.moved_from_shared) == (2, 1)
    assert answer_memory.get(entry.entry_id, TEAM) is None
    assert entry.entry_id not in ids(answer_memory.entries(product_id=""))
    assert (TEAM, availo.id) not in stores, "and its collection"


def test_a_version_11_database_upgrades_and_its_answers_stay_shared() -> None:
    conn = store.connect()
    tables = [
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    ]
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript("".join(f"DROP TABLE IF EXISTS {name};" for name in tables))
    conn.execute("PRAGMA foreign_keys = ON")
    for index, step in enumerate(store.MIGRATIONS[:11]):
        getattr(store.migrations, step)(conn) if step.startswith("_") else conn.executescript(step)
        conn.execute(f"PRAGMA user_version = {index + 1}")
    conn.execute(
        "INSERT INTO memory_entries (entry_id, team_id, question, answer, created_at, updated_at) "
        "VALUES ('mem-1', ?, 'Q?', 'A.', '2026-01-01', '2026-01-01')",
        (TEAM,),
    )
    conn.commit()
    store.reset_connection()

    upgraded = store.connect()
    assert upgraded.execute("PRAGMA user_version").fetchone()[0] == len(store.MIGRATIONS) >= 12
    assert upgraded.execute("SELECT product_id FROM memory_entries WHERE entry_id = 'mem-1'").fetchone()[0] == ""
