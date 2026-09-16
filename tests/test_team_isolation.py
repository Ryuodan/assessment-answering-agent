"""Every team has its own knowledge base, answer memory and documents.

It was one of each for the whole organisation. Batches and conversations were
already a team's, but the policies every answer is drafted from and the answers
the team had given before were shared: one team's questionnaire was answered
from another team's policies and quoted another team's answers, and any member
of any team could correct or forget another team's remembered answers or remove
its documents. These tests hold the boundary from both sides, through the same
routes a person uses.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from src import answer_memory, identity, knowledge, service, store
from src.api import app
from src.config import settings
from src.models import IngestResult
from tests.conftest import FakeVectorStore, bare_store

ALICE = "m.alsaif@t2.sa"            # the team the system was set up for
CAROL = "carol@example.com"         # another team
CODE, OTHER_CODE = "TEAM-CODE-FOR-TESTS", "OTHER-TEAM-CODE"
OTHER = "privacy"


@pytest.fixture
def teams():
    identity.ensure_team(settings.default_team, name="Cybersecurity")
    identity.set_access_code(settings.default_team, CODE)
    identity.add_user(ALICE)
    identity.ensure_team(OTHER, name="Privacy")
    identity.set_access_code(OTHER, OTHER_CODE)
    identity.add_user(CAROL, team_id=OTHER)


def as_person(email: str, code: str) -> TestClient:
    client = TestClient(app)
    assert client.post("/api/auth/session", json={"email": email, "code": code}).status_code == 200
    return client


@pytest.fixture
def stores(monkeypatch):
    """A fake index per team, reached however the code asks for a team's store."""
    made: dict[str, knowledge.KnowledgeStore] = {}

    def get_store(team_id=None):
        team = team_id or settings.default_team
        if team not in made:
            made[team] = bare_store(FakeVectorStore([]))
            made[team].team_id = team
        return made[team]

    monkeypatch.setattr("src.knowledge.get_store", get_store)
    monkeypatch.setattr("src.service.get_store", get_store)
    monkeypatch.setattr("src.graph.nodes.get_store", get_store, raising=False)
    return get_store


# --- the answer memory ----------------------------------------------------------------


def test_one_teams_remembered_answers_are_invisible_to_another(teams, stores):
    alice, carol = as_person(ALICE, CODE), as_person(CAROL, OTHER_CODE)
    added = alice.post("/api/memory", json={"question": "Do you encrypt backups?", "answer": "Yes."}).json()

    assert [e["entry_id"] for e in alice.get("/api/memory").json()["entries"]] == [added["entry_id"]]
    theirs = carol.get("/api/memory").json()
    assert theirs["entries"] == [] and theirs["total"] == 0 and theirs["stats"]["entries"] == 0


def test_another_team_cannot_change_restore_or_forget_them(teams, stores):
    alice, carol = as_person(ALICE, CODE), as_person(CAROL, OTHER_CODE)
    entry_id = alice.post("/api/memory", json={"question": "Q?", "answer": "Yes."}).json()["entry_id"]

    assert carol.patch(f"/api/memory/{entry_id}", json={"answer": "No."}).status_code == 404
    assert carol.post(f"/api/memory/{entry_id}/restore").status_code == 404
    assert carol.delete(f"/api/memory/{entry_id}").status_code == 404
    assert alice.get("/api/memory").json()["entries"][0]["answer"] == "Yes."


def test_disagreements_belong_to_the_team_whose_answers_they_are(teams, stores):
    first = answer_memory.record("Do you run drills?", "Yes.", team_id=settings.default_team)
    second = answer_memory.record("Do you run drills?", "No.", team_id=settings.default_team)
    answer_memory.raise_conflict(first.entry_id, second.entry_id, "they disagree",
                                 team_id=settings.default_team)
    alice, carol = as_person(ALICE, CODE), as_person(CAROL, OTHER_CODE)

    assert len(alice.get("/api/memory/conflicts").json()["conflicts"]) == 1
    assert carol.get("/api/memory/conflicts").json()["conflicts"] == []
    assert carol.post("/api/memory/conflicts/resolve", json={
        "entry_id": first.entry_id, "other_id": second.entry_id, "resolution": "keep_this",
    }).status_code == 404


def test_two_teams_may_import_a_questionnaire_of_the_same_name(stores):
    """Imported entries are named `<file>::<n>`, so the same file name in two
    teams is the same id -- one team's import used to overwrite the other's."""
    class Pair:
        def __init__(self, question, answer):
            self.question, self.answer, self.section = question, answer, ""

    answer_memory.adopt_file("Vendor.xlsx", [Pair("Q?", "Ours.")], team_id=settings.default_team)
    answer_memory.adopt_file("Vendor.xlsx", [Pair("Q?", "Theirs.")], team_id=OTHER)

    assert answer_memory.get("Vendor.xlsx::0", settings.default_team).answer == "Ours."
    assert answer_memory.get("Vendor.xlsx::0", OTHER).answer == "Theirs."


def test_an_approved_answer_is_remembered_in_the_approvers_team_index(teams, stores):
    entry = answer_memory.record("Q?", "Yes.", team_id=OTHER, origin="approved", entry_id="approved::b::1")

    assert [r["id"] for r in stores(OTHER)._store.records] == [entry.entry_id]
    assert stores(settings.default_team)._store.records == []


async def test_the_sweep_compares_an_entry_only_within_its_own_team(stores, monkeypatch):
    ours = answer_memory.record("Do you have a CISO?", "Yes.", team_id=settings.default_team)
    theirs = answer_memory.record("Do you have a CISO?", "No.", team_id=OTHER)
    searched = []

    async def search(self, query, source_type, k, expand=True):
        searched.append(self.team_id)
        return []

    monkeypatch.setattr(knowledge.KnowledgeStore, "search", search)
    await answer_memory.scan(theirs)

    assert searched == [OTHER]
    assert answer_memory.get(ours.entry_id, settings.default_team).stands


# --- the knowledge base ---------------------------------------------------------------


def test_one_teams_documents_and_index_are_its_own(teams, stores, monkeypatch):
    async def indexed(path, source_type, authority="ours", team_id=None):
        stores(team_id).add_guideline(path.name, "## 1 Scope\n\nRetention is 90 days.")
        return IngestResult(source_name=path.name, source_type=source_type, chunks_indexed=1)

    monkeypatch.setattr("src.api.service.ingest", indexed)
    alice, carol = as_person(ALICE, CODE), as_person(CAROL, OTHER_CODE)

    alice.post("/api/knowledge/guidelines",
               files={"files": ("T2 - Retention Policy.pdf", b"%PDF-1.4 ours", "application/pdf")})

    assert [s["name"] for s in alice.get("/api/knowledge").json()["sources"]] == ["T2 - Retention Policy.pdf"]
    assert carol.get("/api/knowledge").json()["sources"] == []
    assert carol.get("/api/search", params={"q": "retention", "mode": "keyword"}).json()["results"] == []
    assert carol.delete("/api/knowledge/sources/T2 - Retention Policy.pdf").status_code == 404
    assert [s["name"] for s in alice.get("/api/knowledge").json()["sources"]] == ["T2 - Retention Policy.pdf"]


def test_another_teams_documents_cannot_be_listed_or_opened(teams, stores, monkeypatch):
    async def indexed(path, source_type, authority="ours", team_id=None):
        return IngestResult(source_name=path.name, source_type=source_type, chunks_indexed=1)

    monkeypatch.setattr("src.api.service.ingest", indexed)
    alice, carol = as_person(ALICE, CODE), as_person(CAROL, OTHER_CODE)
    carol.post("/api/knowledge/guidelines",
               files={"files": ("Privacy Charter.pdf", b"%PDF-1.4 theirs", "application/pdf")})

    assert [d["name"] for d in carol.get("/api/documents").json()["documents"]] == ["Privacy Charter.pdf"]
    assert alice.get("/api/documents").json()["documents"] == []
    assert alice.get("/api/documents/uploaded/uploaded/Privacy Charter.pdf/file").status_code == 404
    assert carol.get("/api/documents/uploaded/uploaded/Privacy Charter.pdf/file").status_code == 200


async def test_a_question_is_answered_from_its_own_teams_index(stores):
    from src.graph import nodes
    from src.models import Question

    stores(settings.default_team).add_guideline("ours.pdf", "## 1 Scope\n\nOur retention is 90 days.")
    stores(OTHER).add_guideline("theirs.pdf", "## 1 Scope\n\nTheir retention is 30 days.")
    asked = []

    async def search_types(self, query, wanted, expand=True):
        asked.append(self.team_id)
        return {}

    import src.knowledge as module
    original = module.KnowledgeStore.search_types
    module.KnowledgeStore.search_types = search_types
    try:
        await nodes.retrieve({
            "question": Question(id="1", text="How long is data retained?"),
            "search_queries": ["retention"], "team_id": OTHER,
        })
    finally:
        module.KnowledgeStore.search_types = original

    assert asked == [OTHER]


def test_uploads_land_in_their_teams_own_directory():
    ours = service.save_upload("Policy.pdf", b"ours")
    theirs = service.save_upload("Policy.pdf", b"theirs", OTHER)

    assert ours.parent == settings.upload_dir
    assert theirs.parent == settings.upload_dir.parent / "teams" / OTHER / "uploads"
    assert ours.read_bytes() == b"ours" and theirs.read_bytes() == b"theirs"


@pytest.mark.parametrize("team", ["../escape", "a/b", "..", "UPPER", ""])
def test_a_team_id_that_is_not_a_directory_name_is_refused(team):
    if team == "":
        assert settings.team_upload_dir(team) == settings.upload_dir, "no team means the default one"
        return
    with pytest.raises(ValueError):
        settings.team_upload_dir(team)


def test_an_admin_cannot_create_a_team_that_would_name_a_path(teams):
    identity.add_user("boss@example.com", role=identity.ADMIN, password="a-long-password")
    admin = as_person("boss@example.com", "a-long-password")
    response = admin.post("/api/admin/users", json={"email": "x@example.com", "team": "../../etc"})
    assert response.status_code == 422


@pytest.mark.parametrize("team", ["privacy", "risk-and-compliance", "a", "t2.data_office", "9" * 64])
def test_every_team_gets_a_valid_collection_of_its_own(team):
    import re

    name = knowledge.collection_for(team)
    assert 3 <= len(name) <= 63 and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*[a-zA-Z0-9]", name)
    assert name != settings.collection_name
    assert knowledge.collection_for(settings.default_team) == settings.collection_name
    assert knowledge.collection_for(team) != knowledge.collection_for(team + "x")


# --- the migration ----------------------------------------------------------------------


def test_what_was_remembered_before_teams_belongs_to_the_default_team(tmp_path, monkeypatch):
    """The deployment's 698 answers were stored with no team. They are the
    security team's -- the team the system was set up for."""
    path = tmp_path / "before.db"
    monkeypatch.setattr(settings, "db_path", path)
    conn = sqlite3.connect(path)
    for index, step in enumerate(store.MIGRATIONS[:9]):
        conn.executescript(step)
        conn.execute(f"PRAGMA user_version = {index + 1}")
    conn.executescript(
        """
        INSERT INTO memory_entries (entry_id, team_id, question, answer, created_at, updated_at)
        VALUES ('Vendor.xlsx::0', '', 'Q?', 'Yes.', '2026-01-01', '2026-01-01'),
               ('approved::b::1', 'cybersecurity', 'Q2?', 'No.', '2026-01-01', '2026-01-01');
        INSERT INTO memory_conflicts (entry_id, other_id, because, raised_at)
        VALUES ('Vendor.xlsx::0', 'approved::b::1', 'they disagree', '2026-01-01');
        """
    )
    conn.commit()
    conn.close()
    store.reset_connection()

    migrated = store.connect()

    assert migrated.execute("PRAGMA user_version").fetchone()[0] == len(store.MIGRATIONS)
    assert {row["team_id"] for row in migrated.execute("SELECT team_id FROM memory_entries")} == {
        settings.default_team
    }
    assert [row["team_id"] for row in migrated.execute("SELECT team_id FROM memory_conflicts")] == [
        settings.default_team
    ]
    assert answer_memory.get("Vendor.xlsx::0").answer == "Yes."
