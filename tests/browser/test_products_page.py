"""The Products page (`/products`) in a real browser (plan 020)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from src import identity, knowledge, products, roles
from src.config import settings
from tests.conftest import FakeVectorStore, bare_store

pytestmark = pytest.mark.browser

CODE = "BROWSER-TEST-CODE"
LEAD = "lead@example.test"
MEMBER = "member@example.test"


@pytest.fixture(autouse=True)
def stores(monkeypatch) -> None:
    """A fake index per (team, product), so deleting one never waits on Chroma.

    It used to reach a real collection in the test's directory, and a cold
    Chroma start once took 5.1 s of the page's 5 s wait for the dialog to close
    (plan 023).
    """
    made: dict[tuple[str, str], knowledge.KnowledgeStore] = {}

    def get_store(team_id=None, *, product_id=""):
        key = (team_id or settings.default_team, product_id)
        if key not in made:
            made[key] = bare_store(FakeVectorStore([]))
            made[key]._store.delete_collection = lambda key=key: made.pop(key, None)
        return made[key]

    monkeypatch.setattr("src.knowledge.get_store", get_store)


@pytest.fixture
def team() -> None:
    identity.ensure_team(settings.default_team)
    identity.set_access_code(settings.default_team, CODE)
    identity.add_user(LEAD, role=roles.LEAD)
    identity.add_user(MEMBER)


def sign_in(page: Page, email: str) -> None:
    page.goto("/products")
    page.fill("#authEmail", email)
    page.fill("#authCode", CODE)
    page.click("#authSubmit")
    expect(page.locator("#authGate")).to_be_hidden()


def test_a_lead_adds_a_product_and_deletes_it_only_after_typing_confirm(page: Page, team: None) -> None:
    sign_in(page, LEAD)
    page.fill("#productName", "Availo")
    page.fill("#productDescription", "Payments")
    page.click("#addProduct")
    card = page.locator(".product", has_text="Availo")
    expect(card).to_be_visible()

    card.get_by_role("button", name="Delete").click()
    dialog = page.locator("#deleteDialog")
    expect(dialog).to_be_visible()
    warning = dialog.locator(".danger-box")
    expect(warning).to_contain_text("permanently deletes Availo's documents and its remembered answers")
    # The warning is in the page's error colour, whichever theme is on: the same
    # computed colour as an element painted with var(--err).
    colour, error = warning.evaluate(
        """box => {
            const probe = document.createElement("span");
            probe.style.color = "var(--err)";
            document.body.append(probe);
            const expected = getComputedStyle(probe).color;
            probe.remove();
            return [getComputedStyle(box).color, expected];
        }"""
    )
    assert colour == error, f"the warning is {colour}, the error colour is {error}"

    go = dialog.get_by_role("button", name="Delete product")
    expect(go).to_be_disabled()
    page.fill("#deleteConfirm", "conf")
    expect(go).to_be_disabled()
    page.fill("#deleteConfirm", "confirm")
    expect(go).to_be_enabled()
    go.click()

    expect(dialog).to_be_hidden()
    expect(page.locator(".product", has_text="Availo")).to_have_count(0)
    assert products.list_products(settings.default_team) == []


def test_a_member_sees_the_products_but_nothing_to_change_them_with(page: Page, team: None) -> None:
    lead = identity.find_user(LEAD)
    products.add(lead, settings.default_team, "Msegat")
    sign_in(page, MEMBER)

    expect(page.locator(".product", has_text="Msegat")).to_be_visible()
    expect(page.locator("#addPanel")).to_be_hidden()
    expect(page.get_by_role("button", name="Delete")).to_have_count(0)
    expect(page.locator("#listHint")).to_contain_text("Only the team's leads and administrators")
