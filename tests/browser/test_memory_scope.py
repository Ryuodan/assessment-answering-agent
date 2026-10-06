"""The memory page's selector, and moving an answer between memories, in a real browser (plan 022)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from src import answer_memory, knowledge, products
from src.config import settings
from tests.conftest import FakeVectorStore, bare_store

pytestmark = pytest.mark.browser

TEAM = settings.default_team


@pytest.fixture
def stores(monkeypatch):
    made: dict[tuple[str, str], knowledge.KnowledgeStore] = {}

    def get_store(team_id=None, *, product_id=""):
        key = (team_id or TEAM, product_id)
        if key not in made:
            made[key] = bare_store(FakeVectorStore([]))
        return made[key]

    monkeypatch.setattr("src.knowledge.get_store", get_store)
    return made


def test_the_page_shows_one_memory_and_moves_an_answer_to_another(page: Page, stores) -> None:
    availo = products.add(None, TEAM, "Availo")
    answer_memory.record("Do you encrypt backups?", "Shared: yes, with AES-256.", scanned=True)
    answer_memory.record("Do you encrypt backups?", "Availo: yes, per tenant.", product_id=availo.id, scanned=True)

    page.goto("/memory")
    entries = page.locator("#entries")
    expect(entries).to_contain_text("Shared: yes, with AES-256.")
    expect(entries).not_to_contain_text("Availo: yes, per tenant.")

    page.select_option("#memoryScope", availo.id)
    expect(page.locator("#memoryScopeHint")).to_contain_text("Used only for Availo's questionnaires")
    expect(entries).to_contain_text("Availo: yes, per tenant.")
    expect(entries).not_to_contain_text("Shared: yes, with AES-256.")

    entries.locator(".entry", has_text="Availo: yes").locator("select.move").select_option("shared")
    expect(entries).not_to_contain_text("Availo: yes, per tenant.")

    page.select_option("#memoryScope", "")
    expect(entries).to_contain_text("Availo: yes, per tenant.")
    expect(entries).to_contain_text("Shared: yes, with AES-256.")
    assert {e.product_id for e in answer_memory.entries()} == {""}
