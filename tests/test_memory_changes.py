"""Decided changes to the live answer memory: forgetting and moving entries (plan 026)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import memory_changes
from src import answer_memory, identity, knowledge, products, store
from src.config import settings
from tests.conftest import FakeVectorStore, bare_store

TEAM = settings.default_team
LEAD = "lead@example.test"


@pytest.fixture
def stores(monkeypatch):
    """A fake index per (team, product)."""
    made: dict[tuple[str, str], knowledge.KnowledgeStore] = {}

    def get_store(team_id=None, *, product_id=""):
        key = (team_id or TEAM, product_id)
        if key not in made:
            made[key] = bare_store(FakeVectorStore([]))
        return made[key]

    monkeypatch.setattr("src.knowledge.get_store", get_store)
    return made


@pytest.fixture
def ole5(stores):
    identity.ensure_team(TEAM)
    identity.add_user(LEAD)
    product = products.add(None, TEAM, "Ole5")
    answer_memory.record("Who completed this form?", "A routing note.", entry_id="MEM-1", scanned=True)
    answer_memory.record("Is the system hosted in Saudi Arabia?", "Yes.", entry_id="MEM-2", scanned=True)
    return product


def changes(tmp_path: Path, **content) -> str:
    path = tmp_path / "changes.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    return str(path)


DECIDED = {
    "remove": [{"entry_id": "MEM-1", "reason": "a routing note, not an answer"}],
    "move": [{"entry_id": "MEM-2", "product": "ole5", "reason": "describes the product's hosting"}],
}


def entry_ids(stores, product_id: str = "") -> list[str]:
    return [r["metadata"]["entry_id"] for r in knowledge.get_store(TEAM, product_id=product_id)._store.records]


def test_without_apply_nothing_changes(ole5, tmp_path, capsys) -> None:
    assert memory_changes.main([changes(tmp_path, **DECIDED), "--by", LEAD]) == 0
    out = capsys.readouterr().out
    assert "forget MEM-1" in out and "move MEM-2 to ole5" in out and "would be made" in out
    assert answer_memory.get("MEM-1", TEAM) is not None
    assert answer_memory.get("MEM-2", TEAM).product_id == ""


def test_applied_changes_match_the_memory_page_and_are_recorded(ole5, stores, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(memory_changes, "app_running", lambda port: False)
    assert memory_changes.main([changes(tmp_path, **DECIDED), "--by", LEAD, "--apply"]) == 0

    assert answer_memory.get("MEM-1", TEAM) is None
    moved = answer_memory.get("MEM-2", TEAM)
    assert moved.product_id == ole5.id
    assert entry_ids(stores, ole5.id) == ["MEM-2"] and entry_ids(stores) == [], "re-indexed in Ole5's memory"
    assert "MEM-2" in {e.entry_id for e in answer_memory.pending(team_id=TEAM)}, "to be compared again there"

    rows = store.connect().execute("SELECT kind, actor_email, subject_id, payload FROM events ORDER BY id").fetchall()
    recorded = [(r["kind"], r["actor_email"], r["subject_id"]) for r in rows if r["subject_id"].startswith("MEM-")]
    assert recorded == [("memory_removed", LEAD, "MEM-1"), ("memory_edited", LEAD, "MEM-2")]
    assert json.loads(rows[-1]["payload"])["moved_to"] == ole5.id


def test_nothing_is_applied_while_the_app_is_running(ole5, tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(memory_changes, "app_running", lambda port: True)
    assert memory_changes.main([changes(tmp_path, **DECIDED), "--by", LEAD, "--apply"]) == 1
    assert "stop the app first" in capsys.readouterr().out
    assert answer_memory.get("MEM-1", TEAM) is not None


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ({"remove": [{"entry_id": "MEM-404", "reason": "gone already"}]}, "MEM-404: not in the answer memory"),
        ({"move": [{"entry_id": "MEM-2", "product": "Nope", "reason": "a product"}]}, "no product 'Nope'"),
        ({"move": [{"entry_id": "MEM-2", "product": "", "reason": "back to shared"}]}, "already in the shared memory"),
    ],
)
def test_a_change_that_cannot_be_made_stops_them_all(ole5, tmp_path, monkeypatch, capsys, content, expected) -> None:
    monkeypatch.setattr(memory_changes, "app_running", lambda port: False)
    content = {"remove": DECIDED["remove"] + content.get("remove", []), "move": content.get("move", [])}
    assert memory_changes.main([changes(tmp_path, **content), "--by", LEAD, "--apply"]) == 1
    assert expected in capsys.readouterr().out
    assert answer_memory.get("MEM-1", TEAM) is not None, "nothing was changed"


def test_the_decider_must_have_an_account(ole5, tmp_path) -> None:
    assert memory_changes.main([changes(tmp_path, **DECIDED), "--by", "nobody@example.test"]) == 2


def test_a_listening_port_counts_as_the_app_running() -> None:
    import socket

    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        assert memory_changes.app_running(port)
    assert not memory_changes.app_running(port)
