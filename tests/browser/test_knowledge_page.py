"""The Knowledge base page, and the Workbench without it, in a real browser (plan 030).

The Workbench opened on "1 Build the knowledge base": the scope, the upload,
the list with view, remove and clear, and the document library. They moved,
unchanged, to a page of their own (`/knowledge`); their own tests moved with
them (`test_knowledge_scope.py`). These hold what the move added: the
Workbench opens on the questionnaire and says in one line what the answers
are drawn from, every header links the page, the page works for a lead and a
member as before, and reading -- a citation's document, the Search drawer --
still works on the Workbench.
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

    choose_general(page)
    expect(said).to_have_text("Answers from 3 shared documents")
    expect(manage).to_have_attribute("href", "knowledge")

    # "Manage" opens the page on the knowledge base the line counted.
    page.select_option("#formProduct", availo.id)
    expect(manage).to_have_attribute("href", f"knowledge?product={availo.id}")
    manage.click()
    page.wait_for_url(f"**/knowledge?product={availo.id}")
    expect(page.locator("#kbScope")).to_have_value(availo.id)
    expect(page.locator("#kbSources")).to_contain_text("Availo standard.pdf")
    expect(page.locator("#kbSources")).not_to_contain_text("Access.pdf")


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

    page.select_option("#kbScope", "")
    expect(sources).to_contain_text("Shared policy.pdf")
    assert page.url.endswith("/knowledge"), page.url

    page.select_option("#kbScope", availo.id)
    expect(sources).to_contain_text("Availo policy.pdf")
    assert page.url.endswith(f"/knowledge?product={availo.id}"), page.url
    page.reload()
    expect(page.locator("#kbScope")).to_have_value(availo.id)
    expect(sources).to_contain_text("Availo policy.pdf")

    # A product that is not the team's (deleted, or a link from elsewhere): the shared one.
    page.goto("/knowledge?product=not-a-product")
    expect(page.locator("#kbScope")).to_have_value("")
    expect(sources).to_contain_text("Shared policy.pdf")
    assert page.url.endswith("/knowledge"), page.url


def test_the_page_opens_a_document_and_the_text_read_from_it(page: Page, stores, monkeypatch) -> None:
    service.save_upload("Access policy.pdf", b"%PDF-1.4 access", TEAM)
    holding("", chunk("Access policy.pdf"))

    async def extracted(path):
        return POLICY_TEXT

    monkeypatch.setattr("src.service.extracted_document_text", extracted)

    page.goto("/knowledge")
    page.locator("#kbSources li", has_text="Access policy.pdf").get_by_role("button", name="view").click()
    viewer = page.locator("#documentViewer")
    expect(viewer).to_be_visible()
    expect(page.locator("#viewerTitle")).to_have_text("Access policy")
    page.click("#textTab")
    expect(page.locator("#extractedText")).to_have_text(POLICY_TEXT)
    page.click("#viewerClose")
    expect(viewer).to_be_hidden()

    page.locator("details.library > summary").click()
    card = page.locator("#uploadedDocuments .document-card", has_text="Access policy.pdf")
    card.get_by_role("button", name="View document").click()
    expect(viewer).to_be_visible()
    expect(page.locator("#viewerMeta")).to_contain_text("Access policy.pdf")


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


# --- the chat's drawer stays, and points at the page ---------------------------------


def test_the_chats_drawer_links_the_page_for_the_knowledge_base_it_shows(page: Page, stores) -> None:
    availo = products.add(None, TEAM, "Availo")
    holding(availo.id, chunk("Availo policy.pdf"))

    page.goto("/")
    # Two controls named "Knowledge base" in the chat's bar: the drawer, and the page. Their
    # descriptions tell them apart.
    drawer_button = page.locator("#openKb")
    page_link = page.locator(".topbar a.ghost", has_text="Knowledge base")
    assert drawer_button.get_attribute("title") != page_link.get_attribute("title")

    drawer_button.click()
    link = page.locator("#kb").get_by_role("link", name="Manage on the Knowledge base page")
    expect(link).to_have_attribute("href", "knowledge")
    expect(page.locator("#kbScope option", has_text="Availo")).to_have_count(1)
    page.select_option("#kbScope", availo.id)
    expect(link).to_have_attribute("href", f"knowledge?product={availo.id}")

    link.click()
    page.wait_for_url(f"**/knowledge?product={availo.id}")
    expect(page.locator("#kbScope")).to_have_value(availo.id)
    expect(page.locator("#kbSources")).to_contain_text("Availo policy.pdf")
