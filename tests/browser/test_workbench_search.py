"""The Workbench's search drawer, for the shared policies or a product's documents with them (plan 031).

It searched the shared knowledge base alone and listed only its files, so a
product's documents were never searched, whatever the Workbench was answering
for. The server already searched a product's knowledge base beside the shared
one when asked (`GET /api/search?product=`); the drawer never asked.
"""

from __future__ import annotations

import itertools
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import Page, expect

from src import knowledge, products
from src.config import settings
from tests.browser.choosing import choose_general
from tests.conftest import FakeVectorStore, bare_store

pytestmark = pytest.mark.browser

TEAM = settings.default_team
_ids = itertools.count()


@pytest.fixture
def stores(monkeypatch) -> dict[tuple[str, str], knowledge.KnowledgeStore]:
    """A fake index per (team, product), empty until a test puts chunks in it."""
    made: dict[tuple[str, str], knowledge.KnowledgeStore] = {}

    def get_store(team_id=None, *, product_id=""):
        key = (team_id or TEAM, product_id)
        if key not in made:
            made[key] = bare_store(FakeVectorStore([]))
        return made[key]

    monkeypatch.setattr("src.knowledge.get_store", get_store)
    return made


def holding(product_id: str, *names: str) -> None:
    """Documents put straight into a knowledge base, as indexing would, and its catalog read again."""
    store = knowledge.get_store(TEAM, product_id=product_id)
    for name in names:
        store._store.records.append(
            {"text": "text", "metadata": {"source_name": name, "source_type": "guideline"}, "id": f"c{next(_ids)}"}
        )
    store._reset_caches()


def hit(name: str, product_id: str = "") -> dict:
    return {
        "source_name": name,
        "source_type": "guideline",
        "locator": f"{name} §1",
        "snippet": f"What {name} says about MFA.",
        "score": 0.8,
        "is_lexical": False,
        "product_id": product_id,
    }


@pytest.fixture
def searched(monkeypatch) -> list[dict]:
    """Each search the server ran: its query, product and file. A product's search finds
    one passage of its own and one shared, as `src.search` returns them."""
    calls: list[dict] = []

    async def search(query, **options):
        product = options.get("product_id", "")
        calls.append({"query": query, "product": product, "source": options.get("source_name", "")})
        results = ([hit("Availo standard.pdf", product)] if product else []) + [hit("Access.pdf")]
        return {"query": query, "mode": "hybrid", "results": results, "documents": []}

    monkeypatch.setattr("src.api.service.search_knowledge", search)
    return calls


@pytest.fixture
def availo(stores):
    availo = products.add(None, TEAM, "Availo")
    holding("", "Access.pdf", "Backup.pdf")
    holding(availo.id, "Availo standard.pdf")
    return availo


def files_offered(page: Page) -> list[str]:
    return page.locator("#searchSource option").evaluate_all("options => options.map((o) => o.value)")


def search(page: Page, query: str = "MFA") -> None:
    page.fill("#searchInput", query)
    page.press("#searchInput", "Enter")


def test_with_a_product_chosen_its_documents_are_searched_listed_and_badged(page: Page, availo, searched) -> None:
    page.goto("/workbench")
    page.select_option("#formProduct", availo.id)
    page.click("#searchOpen")

    expect(page.locator("#searchScope")).to_have_value(availo.id)
    expect(page.locator("#searchScope option:checked")).to_have_text("Availo and shared policies")
    expect(page.locator("#searchSource option", has_text="Availo standard.pdf")).to_have_count(1)
    assert files_offered(page) == ["", "Availo standard.pdf", "Access.pdf", "Backup.pdf"]

    with page.expect_request(lambda request: "/api/search?" in request.url) as sent:
        search(page)
    assert parse_qs(urlsplit(sent.value.url).query)["product"] == [availo.id]
    hits = page.locator("#searchResults .search-hit")
    expect(hits).to_have_count(2)
    assert searched == [{"query": "MFA", "product": availo.id, "source": ""}]

    # The product's passage carries its badge; a shared policy's carries none.
    own = hits.filter(has_text="Availo standard.pdf")
    expect(own.locator(".tag.product")).to_have_text("Availo")
    expect(own.locator(".tag.product")).to_have_attribute(
        "title", "From Availo's own documents, not the shared policies"
    )
    expect(hits.filter(has_text="Access.pdf").locator(".tag.product")).to_have_count(0)


def test_the_shared_policies_are_searched_with_no_product(page: Page, availo, searched) -> None:
    """`products.chosen(team, "general")` is `product_not_found`: General is no product
    to the server, so the shared policies are asked for with none."""
    page.goto("/workbench")
    choose_general(page)
    page.click("#searchOpen")
    expect(page.locator("#searchScope")).to_have_value("")
    expect(page.locator("#searchSource option", has_text="Access.pdf")).to_have_count(1)
    assert files_offered(page) == ["", "Access.pdf", "Backup.pdf"], "no product's file"

    with page.expect_request(lambda request: "/api/search?" in request.url) as sent:
        search(page)
    assert "product" not in parse_qs(urlsplit(sent.value.url).query)
    expect(page.locator("#searchResults .search-hit")).to_have_count(1)
    assert searched == [{"query": "MFA", "product": "", "source": ""}]


def searching(page: Page):
    return page.expect_response(lambda response: "/api/search?" in response.url)


def test_changing_search_in_searches_again_and_drops_the_files_it_left(page: Page, availo, searched) -> None:
    hits = page.locator("#searchResults .search-hit")
    page.goto("/workbench")
    page.select_option("#formProduct", availo.id)
    page.click("#searchOpen")
    expect(page.locator("#searchSource option", has_text="Availo standard.pdf")).to_have_count(1)
    search(page)
    expect(hits).to_have_count(2)

    with searching(page):
        page.select_option("#searchSource", "Availo standard.pdf")
    assert searched[-1] == {"query": "MFA", "product": availo.id, "source": "Availo standard.pdf"}

    # The shared policies: Availo's file is not among them, so the filter lets it go.
    with searching(page):
        page.select_option("#searchScope", "")
    expect(hits).to_have_count(1)
    assert searched[-1] == {"query": "MFA", "product": "", "source": ""}
    expect(page.locator("#searchSource")).to_have_value("")
    assert files_offered(page) == ["", "Access.pdf", "Backup.pdf"]

    with searching(page):
        page.select_option("#searchScope", availo.id)
    expect(hits).to_have_count(2)
    expect(hits.locator(".tag.product")).to_have_text("Availo")
    assert searched[-1] == {"query": "MFA", "product": availo.id, "source": ""}
    assert len(searched) == 4, searched


def test_the_drawer_follows_the_workbench_when_it_opens_and_keeps_a_scope_chosen_in_it(
    page: Page, availo, searched
) -> None:
    beta = products.add(None, TEAM, "Beta")
    scope = page.locator("#searchScope")
    page.goto("/workbench")
    expect(page.locator("#formProduct option", has_text="Beta")).to_have_count(1)

    def reopen() -> None:
        page.click("#searchClose")
        page.click("#searchOpen")

    page.click("#searchOpen")
    expect(scope).to_have_value("")  # nothing chosen: the shared policies

    page.click("#searchClose")
    page.select_option("#formProduct", availo.id)
    page.click("#searchOpen")
    expect(scope).to_have_value(availo.id)

    # Chosen in the drawer, and kept while the Workbench's choice stays as it was.
    page.select_option("#searchScope", "")
    reopen()
    expect(scope).to_have_value("")

    page.click("#searchClose")
    page.select_option("#formProduct", beta.id)
    page.click("#searchOpen")
    expect(scope).to_have_value(beta.id)

    page.click("#searchClose")
    choose_general(page)
    page.click("#searchOpen")
    expect(scope).to_have_value("")
    assert searched == [], "nothing was typed, so nothing was searched"


def test_an_earlier_answer_is_told_apart_from_a_policy(page: Page, availo, monkeypatch) -> None:
    """TD-074: search shows the team's earlier answers now, so each says what it is."""
    remembered = {**hit("Answer memory"), "source_type": "prior_answer", "locator": "Answer memory (2026-10-01)"}

    async def search_knowledge(query, **options):
        return {"query": query, "mode": "hybrid", "results": [hit("Access.pdf"), remembered], "documents": []}

    monkeypatch.setattr("src.api.service.search_knowledge", search_knowledge)
    page.goto("/workbench")
    choose_general(page)
    page.click("#searchOpen")
    search(page)

    hits = page.locator("#searchResults .search-hit")
    expect(hits).to_have_count(2)
    expect(hits.filter(has_text="Answer memory").locator(".tag.prior_answer")).to_have_text("previous answer")
    expect(hits.filter(has_text="Access.pdf").locator(".tag.prior_answer")).to_have_count(0)
