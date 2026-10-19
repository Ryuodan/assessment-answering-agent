"""The workbench's knowledge-base selector in a real browser (plan 021)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from src import knowledge, products, service
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
    # Kept in Availo's own folder, and badged with it in the document library (plan 027).
    assert (settings.product_upload_dir(TEAM, availo.id) / "standard.pdf").is_file()
    card = page.locator("#uploadedDocuments .document-card", has_text="standard.pdf")
    expect(card.locator(".tag.product")).to_have_text("Availo")

    page.select_option("#kbScope", "")
    expect(page.locator("#kbSources")).to_contain_text("Shared policy.pdf")


def test_removing_and_clearing_a_products_documents_takes_their_files_and_their_library_cards(
    page: Page, stores
) -> None:
    """Through the confirm each asks first (plan 027), including a file from
    before products had folders of their own, which used to stay for good."""
    availo = products.add(None, TEAM, "Availo")
    own = service.save_upload("Availo policy.pdf", b"%PDF-1.4 availo", TEAM, product_id=availo.id)
    old = settings.team_upload_dir(TEAM) / "Old policy.pdf"
    old.write_bytes(b"%PDF-1.4 from before")
    record = {"text": "old", "metadata": {"source_name": old.name, "source_type": "guideline"}, "id": old.name}
    knowledge.get_store(TEAM, product_id=availo.id)._store.records.append(record)
    asked: list[str] = []

    def accept(dialog) -> None:
        asked.append(dialog.message)
        dialog.accept()

    page.goto("/workbench")
    page.select_option("#kbScope", availo.id)
    sources, library = page.locator("#kbSources"), page.locator("#uploadedDocuments .document-card")
    expect(sources).to_contain_text("Old policy.pdf")
    expect(library.filter(has_text="Old policy.pdf")).to_have_count(1)

    page.once("dialog", accept)
    sources.locator("li", has_text="Old policy.pdf").get_by_role("button", name="remove").click()
    expect(page.locator("#kbStatus")).to_have_text("Removed Old policy.pdf.")
    assert "Its file is deleted too" in asked[0] and "unless the shared knowledge base" in asked[0]
    expect(sources).not_to_contain_text("Old policy.pdf")
    expect(library.filter(has_text="Old policy.pdf")).to_have_count(0)  # the library was read again
    assert not old.exists()

    page.once("dialog", accept)
    page.click("#kbClear")
    expect(page.locator("#kbStatus")).to_have_text("Removed every policy document from Availo's knowledge base.")
    expect(library.filter(has_text="Availo policy.pdf")).to_have_count(0)
    assert not own.exists()


def test_the_assistants_drawer_has_the_same_selector(page: Page, stores) -> None:
    availo = products.add(None, TEAM, "Availo")
    page.goto("/")
    page.click("#openKb")
    expect(page.locator("#sources")).to_contain_text("Shared policy.pdf")
    page.select_option("#kbScope", availo.id)
    expect(page.locator("#sources")).to_contain_text("Availo policy.pdf")
    expect(page.locator("#sources")).not_to_contain_text("Shared policy.pdf")
