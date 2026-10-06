"""The workbench's knowledge-base selector in a real browser (plan 021)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from src import knowledge, products
from src.config import settings
from src.models import IngestResult
from tests.conftest import FakeVectorStore, bare_store

pytestmark = pytest.mark.browser

TEAM = settings.default_team


@pytest.fixture
def stores(monkeypatch):
    """A fake index per (team, product), with one document in each knowledge base."""
    made: dict[tuple[str, str], knowledge.KnowledgeStore] = {}

    def get_store(team_id=None, *, product_id=""):
        key = (team_id or TEAM, product_id)
        if key not in made:
            made[key] = bare_store(FakeVectorStore([]))
            name = "Availo policy.pdf" if product_id else "Shared policy.pdf"
            made[key]._store.records.append(
                {"text": "text", "metadata": {"source_name": name, "source_type": "guideline"}, "id": name}
            )
        return made[key]

    monkeypatch.setattr("src.knowledge.get_store", get_store)
    return made


def test_the_selector_decides_which_knowledge_base_is_listed_and_uploaded_to(
    page: Page, stores, monkeypatch, tmp_path
) -> None:
    availo = products.add(None, TEAM, "Availo")
    uploads: list[dict] = []

    async def indexed(path, source_type, authority="ours", team_id=None, **scope):
        uploads.append(scope)
        return IngestResult(source_name=path.name, source_type=source_type, chunks_indexed=2)

    monkeypatch.setattr("src.routes.knowledge.service.ingest", indexed)

    page.goto("/workbench")
    expect(page.locator("#kbSources")).to_contain_text("Shared policy.pdf")
    expect(page.locator("#kbScope option", has_text="Availo")).to_have_count(1)

    page.select_option("#kbScope", availo.id)
    expect(page.locator("#kbScopeHint")).to_contain_text("Used only for Availo's questionnaires")
    expect(page.locator("#kbSources")).to_contain_text("Availo policy.pdf")
    expect(page.locator("#kbSources")).not_to_contain_text("Shared policy.pdf")

    page.set_input_files(
        "#guidelinesInput", files=[{"name": "standard.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4"}]
    )
    page.click("#guidelinesBtn")
    expect(page.locator("#guidelinesStatus")).to_contain_text("Indexed 1/1")
    assert uploads == [{"product_id": availo.id}]

    page.select_option("#kbScope", "")
    expect(page.locator("#kbSources")).to_contain_text("Shared policy.pdf")


def test_the_assistants_drawer_has_the_same_selector(page: Page, stores) -> None:
    availo = products.add(None, TEAM, "Availo")
    page.goto("/")
    page.click("#openKb")
    expect(page.locator("#sources")).to_contain_text("Shared policy.pdf")
    page.select_option("#kbScope", availo.id)
    expect(page.locator("#sources")).to_contain_text("Availo policy.pdf")
    expect(page.locator("#sources")).not_to_contain_text("Shared policy.pdf")
