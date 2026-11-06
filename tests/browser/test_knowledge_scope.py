"""The knowledge-base selector in a real browser (plan 021).

On the Workbench's first step until plan 030 moved it, unchanged, to the
Knowledge base page; these tests moved with it. Since plan 031 it starts with
nothing chosen, as answering does (D-022): a document is added to the shared
knowledge base, or a product's, only once the person has said which.
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
PDF = {"name": "standard.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4"}


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


@pytest.fixture
def uploads(monkeypatch) -> list[dict]:
    """The scope each upload was indexed into: {} for the shared knowledge base."""
    scopes: list[dict] = []

    async def indexed(path, source_type, authority="ours", team_id=None, **scope):
        scopes.append(scope)
        return IngestResult(source_name=path.name, source_type=source_type, chunks_indexed=2)

    monkeypatch.setattr("src.routes.knowledge.service.ingest", indexed)
    return scopes


def test_the_page_opens_with_no_knowledge_base_chosen_and_adds_nothing_until_one_is(
    page: Page, stores, uploads, monkeypatch
) -> None:
    """Plan 031, the user's rule: "choosing which product it belongs to should be
    mandatorily selected just as answering and not assumed to be general". The page
    opened on "Shared, for every product", so a document added without touching the
    selector went into every product's answers."""
    listed: list[str] = []
    real = service.knowledge_stats

    def counted(team_id=None, *, product_id=""):
        listed.append(product_id)
        return real(team_id, product_id=product_id)

    monkeypatch.setattr(service, "knowledge_stats", counted)
    scope, button, why = page.locator("#kbScope"), page.locator("#guidelinesBtn"), page.locator("#guidelinesNeedsScope")

    page.goto("/knowledge")
    expect(scope).to_have_value("")
    prompt = scope.locator("option").first
    expect(prompt).to_have_text("Choose a knowledge base…")
    expect(prompt).to_be_disabled()
    expect(page.locator("#kbSummary")).to_contain_text("Choose a knowledge base")
    expect(page.locator("#kbSources li")).to_have_count(0)
    expect(page.locator("#kbClear")).to_be_hidden()

    page.set_input_files("#guidelinesInput", files=[PDF])
    expect(page.locator("#guidelinesChosen")).to_have_text("standard.pdf")
    expect(button).to_be_disabled()
    expect(why).to_be_visible()
    expect(why).to_contain_text("Choose the knowledge base")
    expect(button).to_have_accessible_description("Choose the knowledge base they go to, above, first.")
    assert listed == [], "the shared list was read with nothing chosen"

    page.select_option("#kbScope", "general")
    expect(button).to_be_enabled()
    expect(why).to_be_hidden()
    # A hidden description is still read out: it goes with the line (plan 031's review).
    expect(button).to_have_accessible_description("")
    expect(page.locator("#kbSources")).to_contain_text("Shared policy.pdf")
    expect(page.locator("#kbClear")).to_be_visible()
    page.click("#guidelinesBtn")
    expect(page.locator("#guidelinesStatus")).to_contain_text("Indexed 1/1")
    assert uploads == [{}], "the shared knowledge base is sent as no product, as the server expects"
    expect(button).to_be_disabled()  # its files went: nothing to index again


def test_the_selector_decides_which_knowledge_base_is_listed_and_uploaded_to(page: Page, stores, uploads) -> None:
    availo = products.add(None, TEAM, "Availo")

    page.goto("/knowledge")
    expect(page.locator("#kbScope option", has_text="Availo")).to_have_count(1)

    page.select_option("#kbScope", availo.id)
    expect(page.locator("#kbScopeHint")).to_contain_text("Used only for Availo's questionnaires")
    expect(page.locator("#kbSources")).to_contain_text("Availo policy.pdf")
    expect(page.locator("#kbSources")).not_to_contain_text("Shared policy.pdf")

    page.set_input_files("#guidelinesInput", files=[PDF])
    page.click("#guidelinesBtn")
    expect(page.locator("#guidelinesStatus")).to_contain_text("Indexed 1/1")
    assert uploads == [{"product_id": availo.id}]
    # Kept in Availo's own folder (plan 027).
    assert (settings.product_upload_dir(TEAM, availo.id) / "standard.pdf").is_file()

    page.select_option("#kbScope", "general")
    expect(page.locator("#kbSources")).to_contain_text("Shared policy.pdf")
    page.set_input_files("#guidelinesInput", files=[PDF])
    page.click("#guidelinesBtn")
    expect(page.locator("#guidelinesStatus")).to_contain_text("Indexed 1/1")
    assert uploads == [{"product_id": availo.id}, {}]


def test_removing_and_clearing_a_products_documents_takes_their_files(page: Page, stores) -> None:
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
    sources = page.locator("#kbSources")
    expect(sources).to_contain_text("Old policy.pdf")

    page.once("dialog", accept)
    sources.locator("li", has_text="Old policy.pdf").get_by_role("button", name="remove").click()
    expect(page.locator("#kbStatus")).to_have_text("Removed Old policy.pdf.")
    assert "Its file is deleted too" in asked[0] and "unless the shared knowledge base" in asked[0]
    expect(sources).not_to_contain_text("Old policy.pdf")
    assert not old.exists()

    page.once("dialog", accept)
    page.click("#kbClear")
    expect(page.locator("#kbStatus")).to_have_text("Removed every policy document from Availo's knowledge base.")
    expect(sources).not_to_contain_text("Availo policy.pdf")
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
    page.select_option("#kbScope", "general")
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
    page.goto("/knowledge?product=general")
    expect(page.locator("#kbSources")).to_contain_text("Shared policy.pdf")

    page.once("dialog", answering(asked, accept=False))
    page.click("#kbClear")
    expect(page.locator("#kbSources")).to_contain_text("Shared policy.pdf")
    assert asked and "Remove the 1 policy document from the shared knowledge base?" in asked[0]
    assert "every product" in asked[0] and "The answer memory is not affected." in asked[0]
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
        page.goto("/knowledge?product=general")
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
    page.goto("/knowledge?product=general")
    expect(page.locator("#kbSources")).to_contain_text("Shared policy.pdf")

    page.select_option("#kbScope", availo.id)
    page.once("dialog", answering(asked, accept=False))
    page.click("#kbClear")  # while Availo's list is on its way
    assert asked and asked[0].startswith("Remove every policy document from Availo's knowledge base?")

    expect(page.locator("#kbSources")).to_contain_text("Availo standard.pdf")
    page.once("dialog", answering(asked, accept=False))
    page.click("#kbClear")
    assert asked[1].startswith("Remove all 2 policy documents from Availo's knowledge base?")
