"""The Knowledge base page, and the Workbench without it, in a real browser (plan 030).

The Workbench opened on "1 Build the knowledge base": the scope, the upload,
the list with view, remove and clear, and the document library. They moved,
unchanged, to a page of their own (`/knowledge`); their own tests moved with
them (`test_knowledge_scope.py`). These hold what the move added: the
Workbench opens on the questionnaire and says in one line what the answers
are drawn from, every header links the page, the page works for a lead and a
member as before, and reading -- a citation's document, the Search drawer --
still works on the Workbench. Since plan 031 the page chooses no knowledge
base for the person, and the document library is gone ("view" opens what it did).
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from src import events, identity, knowledge, products, roles, service
from src.config import settings
from src.models import AnsweredQuestion, Evidence, IngestResult, SourceType
from tests import forms_fixtures as shapes
from tests.browser.choosing import choose_general
from tests.conftest import FakeVectorStore, bare_store

pytestmark = pytest.mark.browser

TEAM = settings.default_team
CODE = "BROWSER-TEST-CODE"
LEAD = "lead@example.test"
MEMBER = "member@example.test"
POLICY_TEXT = "Section 4.2: multi-factor authentication is enforced for every account."


_ids = itertools.count()


def chunk(name: str, source_type: str = "guideline") -> dict:
    return {"text": "text", "metadata": {"source_name": name, "source_type": source_type}, "id": f"c{next(_ids)}"}


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


def holding(product_id: str, *records: dict) -> None:
    """Chunks put straight into a knowledge base, as indexing would, and its catalog read again."""
    store = knowledge.get_store(TEAM, product_id=product_id)
    store._store.records.extend(records)
    store._reset_caches()


@pytest.fixture
def team() -> None:
    identity.ensure_team(TEAM)
    identity.set_access_code(TEAM, CODE)
    identity.add_user(LEAD, role=roles.LEAD)
    identity.add_user(MEMBER)


def sign_in(page: Page, email: str, path: str) -> None:
    page.goto(path)
    page.fill("#authEmail", email)
    page.fill("#authCode", CODE)
    page.click("#authSubmit")
    expect(page.locator("#authGate")).to_be_hidden()


def accept(dialog) -> None:
    dialog.accept()


# --- the Workbench opens on the questionnaire ---------------------------------


def test_the_workbench_opens_on_the_questionnaire(page: Page, stores) -> None:
    page.goto("/workbench")

    steps = page.locator("main .step .step-head")
    expect(steps.first.locator("h2")).to_have_text("Load a questionnaire")
    expect(steps.first.locator(".step-number")).to_have_text("1")
    expect(page.locator("#resultsCard .step-number")).to_have_text("2")
    expect(page.locator("#formProduct")).to_be_visible()
    for moved in ("#kbScope", "#guidelinesInput", "#guidelinesBtn", "#kbSources", "#kbClear", "#uploadedDocuments"):
        expect(page.locator(moved), f"{moved} is still on the Workbench").to_have_count(0)


def test_the_workbench_says_what_the_answers_draw_on_and_links_the_page(page: Page, stores) -> None:
    availo = products.add(None, TEAM, "Availo")
    beta = products.add(None, TEAM, "Beta")
    # Documents, not passages: two chunks of one file are one document, and the
    # answer memory's previous answers are not documents at all.
    holding("", chunk("Access.pdf"), chunk("Access.pdf"), chunk("Backup.pdf"), chunk("Crypto.docx"))
    holding("", chunk("Answer memory", "prior_answer"))
    holding(availo.id, chunk("Availo standard.pdf"))

    page.goto("/workbench")
    said, manage = page.locator("#kbLineText"), page.locator("#kbManage")
    expect(said).to_have_text("Answers from 3 shared documents")
    expect(manage).to_have_text("Manage")
    expect(manage).to_have_attribute("href", "knowledge")

    page.select_option("#formProduct", availo.id)
    expect(said).to_have_text("Answers from 3 shared documents and 1 for Availo")
    expect(manage).to_have_attribute("href", f"knowledge?product={availo.id}")

    page.select_option("#formProduct", beta.id)
    expect(said).to_have_text("Answers from 3 shared documents and none for Beta")

    # General is the shared knowledge base, named: the page chooses nothing for the person (plan 031).
    choose_general(page)
    expect(said).to_have_text("Answers from 3 shared documents")
    expect(manage).to_have_attribute("href", "knowledge?product=general")

    # "Manage" opens the page on the knowledge base the line counted.
    page.select_option("#formProduct", availo.id)
    expect(manage).to_have_attribute("href", f"knowledge?product={availo.id}")
    manage.click()
    page.wait_for_url(f"**/knowledge?product={availo.id}")
    expect(page.locator("#kbScope")).to_have_value(availo.id)
    expect(page.locator("#kbSources")).to_contain_text("Availo standard.pdf")
    expect(page.locator("#kbSources")).not_to_contain_text("Access.pdf")


def test_manage_opens_the_knowledge_base_chosen_on_the_workbench_and_none_when_none_is(page: Page, stores) -> None:
    """Plan 031: "Manage" with nothing chosen opened the page on the shared knowledge base,
    the one the page then added documents to; with General it could not say "shared"."""
    holding("", chunk("Access.pdf"))
    manage, scope, sources = page.locator("#kbManage"), page.locator("#kbScope"), page.locator("#kbSources")

    page.goto("/workbench")
    expect(page.locator("#kbLineText")).to_have_text("Answers from 1 shared document")
    expect(manage).to_have_attribute("href", "knowledge")
    manage.click()
    page.wait_for_url("**/knowledge")
    expect(scope).to_have_value("")
    expect(page.locator("#kbSummary")).to_contain_text("Choose a knowledge base")
    expect(sources.locator("li")).to_have_count(0)

    page.goto("/workbench")
    choose_general(page)
    manage.click()
    page.wait_for_url("**/knowledge?product=general")
    expect(scope).to_have_value("general")
    expect(sources).to_contain_text("Access.pdf")


def test_one_shared_document_and_an_empty_knowledge_base_read_as_such(page: Page, stores) -> None:
    page.goto("/workbench")
    expect(page.locator("#kbLineText")).to_have_text("Answers from no shared documents")

    holding("", chunk("Access.pdf"))
    page.reload()
    expect(page.locator("#kbLineText")).to_have_text("Answers from 1 shared document")


# --- every header links it ----------------------------------------------------


def test_every_header_leads_to_the_knowledge_base(page: Page, stores) -> None:
    for path in ("/", "/workbench", "/memory", "/preferences", "/products"):
        page.goto(path)
        page.locator(".topbar a.ghost", has_text="Knowledge base").click()
        page.wait_for_url("**/knowledge")
        expect(page.locator(".topbar h1"), f"from {path}").to_have_text("Knowledge base")
    # Its own header leaves itself out, as every page's does.
    expect(page.locator(".topbar a.ghost", has_text="Knowledge base")).to_have_count(0)


# --- the page, for a lead and for a member, as on the Workbench -------------------


@pytest.mark.parametrize("who", [LEAD, MEMBER])
def test_a_lead_and_a_member_each_add_and_remove_documents(page: Page, stores, team, monkeypatch, who: str) -> None:
    """Who may change the knowledge base is unchanged by the move: anyone on the team."""

    async def indexed(path, source_type, authority="ours", team_id=None, **scope):
        holding(scope.get("product_id", ""), chunk(path.name))
        return IngestResult(source_name=path.name, source_type=source_type, chunks_indexed=1)

    monkeypatch.setattr("src.routes.knowledge.service.ingest", indexed)
    holding("", chunk("Old policy.pdf"))

    sign_in(page, who, "/knowledge")
    expect(page.locator("#whoamiEmail")).to_have_text(who)
    page.select_option("#kbScope", "general")  # chosen, never assumed (plan 031)
    page.check('input[name="guidelineAuthority"][value="external"]')
    page.set_input_files(
        "#guidelinesInput", files=[{"name": "PDPL.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4"}]
    )
    page.click("#guidelinesBtn")
    expect(page.locator("#guidelinesStatus")).to_contain_text("Indexed 1/1")
    sources = page.locator("#kbSources")
    expect(sources).to_contain_text("PDPL.pdf")
    indexing = events.recent(TEAM, kind=events.DOCUMENT_INDEXED)
    assert [(e.actor_email, e.subject_id, e.payload.get("authority")) for e in indexing] == [
        (who, "PDPL.pdf", "external")
    ]

    page.once("dialog", accept)
    sources.locator("li", has_text="Old policy.pdf").get_by_role("button", name="remove").click()
    expect(page.locator("#kbStatus")).to_have_text("Removed Old policy.pdf.")
    expect(sources).not_to_contain_text("Old policy.pdf")

    page.once("dialog", accept)
    page.click("#kbClear")
    expect(page.locator("#kbStatus")).to_have_text("Removed every policy document from the shared knowledge base.")
    expect(sources).not_to_contain_text("PDPL.pdf")
    removed = events.recent(TEAM, kind=events.SOURCE_REMOVED)
    assert {e.actor_email for e in removed} == {who} and len(removed) == 2


def test_the_address_names_the_knowledge_base_the_page_shows(page: Page, stores) -> None:
    availo = products.add(None, TEAM, "Availo")
    holding("", chunk("Shared policy.pdf"))
    holding(availo.id, chunk("Availo policy.pdf"))
    sources = page.locator("#kbSources")

    page.goto(f"/knowledge?product={availo.id}")
    expect(page.locator("#kbScope")).to_have_value(availo.id)
    expect(page.locator("#kbScopeHint")).to_contain_text("Used only for Availo's questionnaires")
    expect(sources).to_contain_text("Availo policy.pdf")
    expect(sources).not_to_contain_text("Shared policy.pdf")

    # The shared knowledge base, chosen, is in the address too (plan 031).
    page.select_option("#kbScope", "general")
    expect(sources).to_contain_text("Shared policy.pdf")
    assert page.url.endswith("/knowledge?product=general"), page.url

    page.select_option("#kbScope", availo.id)
    expect(sources).to_contain_text("Availo policy.pdf")
    assert page.url.endswith(f"/knowledge?product={availo.id}"), page.url
    page.reload()
    expect(page.locator("#kbScope")).to_have_value(availo.id)
    expect(sources).to_contain_text("Availo policy.pdf")

    page.goto("/knowledge?product=general")
    expect(page.locator("#kbScope")).to_have_value("general")
    expect(page.locator("#kbScopeHint")).to_have_text("Used for every questionnaire.")
    expect(sources).to_contain_text("Shared policy.pdf")
    expect(sources).not_to_contain_text("Availo policy.pdf")

    # No choice in the address, or a product that is not the team's (deleted, or a link
    # from elsewhere): nothing chosen, nothing listed, and the address says no choice.
    for address in ("/knowledge", "/knowledge?product=not-a-product"):
        page.goto(address)
        expect(page.locator("#kbScope")).to_have_value("")
        expect(page.locator("#kbSummary")).to_contain_text("Choose a knowledge base")
        expect(sources.locator("li")).to_have_count(0)
        assert page.url.endswith("/knowledge"), page.url


def test_the_page_opens_a_document_and_the_text_read_from_it(page: Page, stores, monkeypatch) -> None:
    """ "Your documents", the library of uploaded files, is gone (plan 031: the user found it
    of no use). What it offered, the original and the text read out of it, "view" opens."""
    service.save_upload("Access policy.pdf", b"%PDF-1.4 access", TEAM)
    holding("", chunk("Access policy.pdf"))

    async def extracted(path):
        return POLICY_TEXT

    monkeypatch.setattr("src.service.extracted_document_text", extracted)

    page.goto("/knowledge?product=general")
    for gone in ("details.library", "#uploadedDocuments", "#uploadedDocumentsSummary"):
        expect(page.locator(gone), f"{gone} is still on the page").to_have_count(0)
    expect(page.get_by_text("Your documents")).to_have_count(0)

    page.locator("#kbSources li", has_text="Access policy.pdf").get_by_role("button", name="view").click()
    viewer = page.locator("#documentViewer")
    expect(viewer).to_be_visible()
    expect(page.locator("#viewerTitle")).to_have_text("Access policy")
    expect(page.locator("#viewerMeta")).to_contain_text("Access policy.pdf")

    # The original: previewed, and offered to download.
    original = "/api/documents/uploaded/uploaded/Access%20policy.pdf/"
    expect(page.locator("#originalTab")).to_have_text("Document preview")
    expect(page.locator("#originalPanel")).to_be_visible()
    expect(page.locator("#documentFrame")).to_have_attribute("src", original + "preview")
    expect(page.locator("#documentDownload")).to_have_attribute("href", original + "file")
    assert page.request.get(original + "file").body() == b"%PDF-1.4 access"

    # The text the agent read out of it.
    page.click("#textTab")
    expect(page.locator("#textPanel")).to_be_visible()
    expect(page.locator("#originalPanel")).to_be_hidden()
    expect(page.locator("#extractedText")).to_have_text(POLICY_TEXT)
    page.click("#originalTab")
    expect(page.locator("#originalPanel")).to_be_visible()
    page.click("#viewerClose")
    expect(viewer).to_be_hidden()


# --- reading stays on the Workbench ---------------------------------------------


def test_a_citation_on_the_workbench_still_opens_its_clause_and_its_document(
    page: Page, stores, tmp_path: Path, monkeypatch
) -> None:
    service.save_upload("Access policy.pdf", b"%PDF-1.4 access", TEAM)
    evidence = Evidence(
        source_type=SourceType.GUIDELINE, source_name="Access policy.pdf", snippet=POLICY_TEXT, score=0.8, chunk=0
    )

    async def answered(questions, language=None, run_id=None, **extra):
        return [
            AnsweredQuestion(
                question=q, answer="Yes.", confidence=0.9, evidence=[evidence], citations=[evidence.locator]
            )
            for q in questions
        ]

    async def extracted(path):
        return POLICY_TEXT

    monkeypatch.setattr("src.tools.service.answer_questions", answered)
    monkeypatch.setattr("src.service.extracted_document_text", extracted)

    page.goto("/workbench")
    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))
    choose_general(page)
    page.click("#extractBtn")
    page.click("#answerBtn")
    card = page.locator("#results .answer").first
    expect(card).to_contain_text("Yes.", timeout=15_000)

    card.locator(".cite").first.click()
    panel = card.locator(".cite-panel")
    expect(panel).to_contain_text("multi-factor authentication is enforced")
    panel.get_by_role("button", name="open document").click()
    expect(page.locator("#documentViewer")).to_be_visible()
    expect(page.locator("#viewerTitle")).to_have_text("Access policy")
    page.click("#textTab")
    expect(page.locator("#extractedText")).to_have_text(POLICY_TEXT)


def test_the_workbench_still_searches_the_knowledge_base(page: Page, stores, monkeypatch) -> None:
    searched: list[str] = []

    async def search(query, **options):
        searched.append(query)
        hit = {
            "source_name": "Access policy.pdf",
            "source_type": "guideline",
            "locator": "Access policy.pdf §4.2",
            "snippet": POLICY_TEXT,
            "score": 0.81,
            "is_lexical": False,
        }
        return {"query": query, "mode": "hybrid", "results": [hit], "documents": ["Access policy.pdf"]}

    monkeypatch.setattr("src.api.service.search_knowledge", search)
    page.goto("/workbench")
    page.click("#searchOpen")
    page.fill("#searchInput", "MFA")
    page.press("#searchInput", "Enter")
    hit = page.locator("#searchResults .search-hit")
    expect(hit).to_contain_text("Access policy.pdf §4.2")
    assert searched == ["MFA"]
    hit.get_by_role("button", name="open document").click()
    expect(page.locator("#documentViewer")).to_be_visible()
    expect(page.locator("#viewerTitle")).to_have_text("Access policy")


def test_documents_can_be_added_from_the_keyboard(page: Page) -> None:
    """The file picker was `display: none`, so Tab never reached "Add documents" (the review of plan 030)."""
    page.goto("/knowledge")
    picker = page.locator("#guidelinesInput")
    expect(picker).to_have_count(1)
    for _ in range(60):
        if page.evaluate("document.activeElement && document.activeElement.id") == "guidelinesInput":
            break
        page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement && document.activeElement.id") == "guidelinesInput"
