"""The knowledge-base selector in a real browser (plan 021).

On the Workbench's first step until plan 030 moved it, unchanged, to the
Knowledge base page; these tests moved with it.
"""

from __future__ import annotations

import time

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

    page.goto("/knowledge")
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

    page.goto("/knowledge")
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


def answering(asked: list[str], accept: bool):
    def handle(dialog) -> None:
        asked.append(dialog.message)
        dialog.accept() if accept else dialog.dismiss()

    return handle


def shared_names(stores) -> list[str]:
    return [r["metadata"]["source_name"] for r in stores[(TEAM, "")]._store.records]


def test_removing_a_shared_document_asks_first_and_names_the_impact(page: Page, stores) -> None:
    """It went on one click, nine pixels from "view", out of every product's answers (plan 029)."""
    asked: list[str] = []
    page.goto("/knowledge")
    sources = page.locator("#kbSources")
    row = sources.locator("li", has_text="Shared policy.pdf")
    expect(row).to_have_count(1)

    page.once("dialog", answering(asked, accept=False))
    row.get_by_role("button", name="remove").click()
    expect(row).to_have_count(1)
    assert asked, "no question was asked"
    assert "“Shared policy.pdf”" in asked[0] and "shared knowledge base" in asked[0]
    assert "every product" in asked[0] and "Its file stays on the server" in asked[0]
    assert shared_names(stores) == ["Shared policy.pdf"]

    page.once("dialog", answering(asked, accept=True))
    row.get_by_role("button", name="remove").click()
    expect(page.locator("#kbStatus")).to_have_text("Removed Shared policy.pdf.")
    expect(sources).not_to_contain_text("Shared policy.pdf")
    assert shared_names(stores) == []


def test_clearing_the_shared_knowledge_base_says_how_many(page: Page, stores) -> None:
    asked: list[str] = []
    page.goto("/knowledge")
    expect(page.locator("#kbSources")).to_contain_text("Shared policy.pdf")

    page.once("dialog", answering(asked, accept=False))
    page.click("#kbClear")
    expect(page.locator("#kbSources")).to_contain_text("Shared policy.pdf")
    assert asked and "Remove the 1 policy document from the shared knowledge base?" in asked[0]
    assert "every product" in asked[0] and "The answer memory is not affected." in asked[0]
    assert shared_names(stores) == ["Shared policy.pdf"]


def test_the_assistants_drawer_names_the_same_impact(page: Page, stores) -> None:
    on_the_page: list[str] = []
    page.goto("/knowledge")
    page.once("dialog", answering(on_the_page, accept=False))
    page.locator("#kbSources li", has_text="Shared policy.pdf").get_by_role("button", name="remove").click()
    expect(page.locator("#kbSources")).to_contain_text("Shared policy.pdf")

    in_the_chat: list[str] = []
    page.goto("/")
    page.click("#openKb")
    row = page.locator("#sources .source", has_text="Shared policy.pdf")
    page.once("dialog", answering(in_the_chat, accept=False))
    row.get_by_role("button", name="remove").click()
    expect(row).to_have_count(1)

    assert in_the_chat and in_the_chat == on_the_page
    assert shared_names(stores) == ["Shared policy.pdf"]


def test_a_late_answer_for_the_shared_list_does_not_replace_a_products(page: Page, stores, monkeypatch) -> None:
    """Found by `poe check` (plan 029): the page's first, shared, request came back
    after the product's, and the list and its count went back to the shared
    knowledge base under a selector that still said Availo."""
    availo = products.add(None, TEAM, "Availo")
    real = service.knowledge_stats

    def slow_when_shared(team_id=None, *, product_id=""):
        if not product_id:
            time.sleep(1.5)
        return real(team_id, product_id=product_id)

    monkeypatch.setattr(service, "knowledge_stats", slow_when_shared)
    sources = page.locator("#kbSources")

    with page.expect_response(lambda response: response.url.endswith("/api/knowledge")):
        page.goto("/knowledge")
        page.select_option("#kbScope", availo.id)
        expect(sources).to_contain_text("Availo policy.pdf")
    page.wait_for_timeout(500)  # time for the late answer to be drawn, were it drawn

    expect(sources).to_contain_text("Availo policy.pdf")
    expect(sources).not_to_contain_text("Shared policy.pdf")


def test_clearing_while_a_products_list_loads_does_not_count_another(page: Page, stores, monkeypatch) -> None:
    """Plan 029's review: until the product's list arrived, "Remove every policy
    document" asked about the product with the shared knowledge base's count."""
    availo = products.add(None, TEAM, "Availo")
    record = {"text": "t", "metadata": {"source_name": "Availo standard.pdf", "source_type": "guideline"}, "id": "s"}
    knowledge.get_store(TEAM, product_id=availo.id)._store.records.append(record)
    real = service.knowledge_stats

    def slow_for_a_product(team_id=None, *, product_id=""):
        if product_id:
            time.sleep(1.5)
        return real(team_id, product_id=product_id)

    monkeypatch.setattr(service, "knowledge_stats", slow_for_a_product)
    asked: list[str] = []
    page.goto("/knowledge")
    expect(page.locator("#kbSources")).to_contain_text("Shared policy.pdf")

    page.select_option("#kbScope", availo.id)
    page.once("dialog", answering(asked, accept=False))
    page.click("#kbClear")  # while Availo's list is on its way
    assert asked and asked[0].startswith("Remove every policy document from Availo's knowledge base?")

    expect(page.locator("#kbSources")).to_contain_text("Availo standard.pdf")
    page.once("dialog", answering(asked, accept=False))
    page.click("#kbClear")
    assert asked[1].startswith("Remove all 2 policy documents from Availo's knowledge base?")


def test_the_assistants_drawer_has_the_same_selector(page: Page, stores) -> None:
    availo = products.add(None, TEAM, "Availo")
    page.goto("/")
    page.click("#openKb")
    expect(page.locator("#sources")).to_contain_text("Shared policy.pdf")
    page.select_option("#kbScope", availo.id)
    expect(page.locator("#sources")).to_contain_text("Availo policy.pdf")
    expect(page.locator("#sources")).not_to_contain_text("Shared policy.pdf")
