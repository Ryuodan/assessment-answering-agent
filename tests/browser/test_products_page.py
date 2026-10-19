"""The Products page (`/products`) in a real browser (plan 020)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from src import answer_memory, batches, events, identity, knowledge, products, roles, service
from src.config import settings
from src.forms.model import DetectedForm
from src.identity import User
from tests.conftest import FakeVectorStore, bare_store

pytestmark = pytest.mark.browser

CODE = "BROWSER-TEST-CODE"
LEAD = "lead@example.test"
MEMBER = "member@example.test"
TEAM = settings.default_team


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


def give_it_work(product: products.Product) -> None:
    """A document with its file, an answer moved in from Shared, and a questionnaire."""
    service.save_upload("Availo policy.pdf", b"%PDF-1.4 availo", TEAM, product_id=product.id)
    metadata = {"source_name": "Availo policy.pdf", "source_type": "guideline"}
    knowledge.get_store(TEAM, product_id=product.id)._store.records.append(
        {"text": "policy", "metadata": metadata, "id": "policy"}
    )
    lead = identity.find_user(LEAD)
    entry = answer_memory.record("Is MFA enforced?", "Yes.", team_id=TEAM, product_id=product.id, index=False)
    events.record(
        lead, events.MEMORY_EDITED, subject_type="memory_entry", subject_id=entry.entry_id, moved_to=product.id
    )
    form = DetectedForm(source_name="Vendor.xlsx", format="xlsx")
    batches.create(User(email=MEMBER, team_id=TEAM), settings.upload_dir / "Vendor.xlsx", form, product.id)


def test_a_lead_adds_a_product_and_deletes_it_only_after_typing_confirm(page: Page, team: None) -> None:
    sign_in(page, LEAD)
    page.fill("#productName", "Availo")
    page.fill("#productDescription", "Payments")
    page.click("#addProduct")
    card = page.locator(".product", has_text="Availo")
    expect(card).to_be_visible()
    availo = products.list_products(TEAM)[0]
    give_it_work(availo)

    card.get_by_role("button", name="Delete").click()
    dialog = page.locator("#deleteDialog")
    expect(dialog).to_be_visible()
    warning = dialog.locator(".danger-box")
    expect(warning).to_contain_text("This cannot be undone")
    expect(warning).to_contain_text("1 document (1 passage), and its file on the server")
    expect(warning).to_contain_text("Availo policy.pdf")
    expect(warning).to_contain_text("1 remembered answer, including 1 moved here from Shared")
    expect(warning).to_contain_text("not moved back to Shared")
    # Decided 2026-10-19 (plan 027): they stay, read-only, rather than becoming General.
    expect(dialog.locator("#deleteStays")).to_contain_text(
        "1 questionnaire and 0 chats for Availo stay listed, marked as from a deleted product, and become read-only"
    )
    expect(dialog.locator("#deleteStays")).to_contain_text("can be read and filled files downloaded")
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

    go = dialog.get_by_role("button", name="Delete permanently")
    expect(go).to_be_disabled()
    page.fill("#deleteConfirm", "conf")
    expect(go).to_be_disabled()
    page.fill("#deleteConfirm", "confirm")
    expect(go).to_be_enabled()
    go.click()

    expect(dialog).to_be_hidden()
    expect(page.locator(".product", has_text="Availo")).to_have_count(0)
    expect(page.locator("#listStatus")).to_contain_text(
        "Deleted Availo: 1 file and 1 remembered answer removed; 1 questionnaire and 0 chats are kept, read-only."
    )
    assert products.list_products(TEAM) == []
    assert not settings.product_upload_dir(TEAM, availo.id).exists()
    expect(page.locator(".product", has_text="Availo")).to_have_count(0)  # deleted products are not listed here


def test_the_warning_says_which_files_stay_because_something_else_uses_them(page: Page, team: None) -> None:
    """A product file from before it had a folder, that the shared knowledge base
    also indexes, stays (one name is one document); the warning said it left."""
    availo = products.add(identity.find_user(LEAD), TEAM, "Availo")
    folder = settings.team_upload_dir(TEAM)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "Shared policy.pdf").write_bytes(b"%PDF-1.4 shared")
    record = {"text": "policy", "metadata": {"source_name": "Shared policy.pdf", "source_type": "guideline"}}
    knowledge.get_store(TEAM, product_id=availo.id)._store.records.append({**record, "id": "own"})
    knowledge.get_store(TEAM)._store.records.append({**record, "id": "shared"})
    sign_in(page, LEAD)

    page.locator(".product", has_text="Availo").get_by_role("button", name="Delete").click()
    warning = page.locator("#deleteDialog .danger-box")
    expect(warning).to_contain_text("1 document (1 passage).")
    expect(warning).to_contain_text(
        "1 file of the same name in the team's folder stays, because the shared knowledge base"
    )
    expect(warning).not_to_contain_text("leaves the document library")


def test_the_delete_dialog_still_warns_when_the_counts_cannot_be_read(page: Page, team: None) -> None:
    products.add(identity.find_user(LEAD), TEAM, "Msegat")
    page.route(
        "**/deletion",
        lambda route: route.fulfill(status=500, content_type="application/json", body='{"detail": "It broke."}'),
    )
    sign_in(page, LEAD)

    page.locator(".product", has_text="Msegat").get_by_role("button", name="Delete").click()
    dialog = page.locator("#deleteDialog")
    warning = dialog.locator(".danger-box")
    expect(warning).to_contain_text("every document, and its file on the server")
    expect(warning).to_contain_text("every remembered answer, including any moved here from Shared")
    expect(dialog.locator("#deleteStays")).to_contain_text(
        "its questionnaires and chats stay listed, marked as from a deleted product, and become read-only"
    )
    expect(dialog.locator("#deleteStatus")).to_contain_text("Could not count what would be deleted (It broke.)")

    go = dialog.get_by_role("button", name="Delete permanently")
    expect(go).to_be_disabled()
    page.fill("#deleteConfirm", "confirm")
    expect(go).to_be_enabled()
    go.click()

    expect(dialog).to_be_hidden()
    assert products.list_products(TEAM) == []


def test_a_member_sees_the_products_but_nothing_to_change_them_with(page: Page, team: None) -> None:
    lead = identity.find_user(LEAD)
    products.add(lead, settings.default_team, "Msegat")
    sign_in(page, MEMBER)

    expect(page.locator(".product", has_text="Msegat")).to_be_visible()
    expect(page.locator("#addPanel")).to_be_hidden()
    expect(page.get_by_role("button", name="Delete")).to_have_count(0)
    expect(page.locator("#listHint")).to_contain_text("Only the team's leads and administrators")
