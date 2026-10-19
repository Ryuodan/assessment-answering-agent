"""Choosing the product on the pages, in a real browser (plan 024, TD-040, TD-041).

A product is chosen once (TD-040). In the chat it is chosen beside the box
before the first message, and from then on the chip is the chat's badge; a new
chat can be for another. On the workbench it is chosen before a questionnaire
is opened, and fixed while it is open; closing it frees the selector for the
next file. Neither page ever asks the server to change a product.

Also here: a product deleted after the page listed it, chosen for a new chat,
is refused beside the box and the chip goes back to General; and a source from
a product's own knowledge base carries its badge in the chat as on the
workbench (TD-041).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from src import batches, conversations, identity, knowledge, products
from src.agents import assistant
from src.config import settings
from src.models import AnsweredQuestion, Evidence, SourceType
from tests import forms_fixtures as shapes
from tests.conftest import FakeVectorStore, bare_store
from tests.test_assistant import _graph

pytestmark = pytest.mark.browser

TEAM = settings.default_team
ANSWER = "Yes, backups are encrypted with a key per tenant."


@pytest.fixture
def availo(monkeypatch: pytest.MonkeyPatch) -> products.Product:
    made: dict[tuple[str, str], knowledge.KnowledgeStore] = {}

    def get_store(team_id=None, *, product_id=""):
        key = (team_id or TEAM, product_id)
        if key not in made:
            made[key] = bare_store(FakeVectorStore([]))
            # So deleting a product drops its fake collection rather than reaching Chroma.
            made[key]._store.delete_collection = lambda key=key: made.pop(key, None)
        return made[key]

    monkeypatch.setattr("src.knowledge.get_store", get_store)
    identity.ensure_team(TEAM)
    return products.add(None, TEAM, "Availo", color="#16a34a")


@pytest.fixture
def product_requests(page: Page) -> list[str]:
    """Every request a page makes to a route that would change a product."""
    asked: list[str] = []
    page.on("request", lambda request: asked.append(request.url) if request.url.endswith("/product") else None)
    return asked


@pytest.fixture
def answers_from_availo(monkeypatch: pytest.MonkeyPatch, availo: products.Product) -> None:
    own = Evidence(
        source_type=SourceType.GUIDELINE,
        source_name="Availo backup standard.pdf",
        snippet="Backups are encrypted with a key per tenant.",
        product_id=availo.id,
    )

    async def answered(questions, language=None, run_id=None, **extra):
        return [
            AnsweredQuestion(question=q, answer=ANSWER, confidence=0.9, citations=[own.locator], evidence=[own])
            for q in questions
        ]

    monkeypatch.setattr("src.tools.service.answer_questions", answered)


def test_a_chat_starts_for_the_product_beside_the_box_and_is_fixed(
    page: Page,
    tmp_path: Path,
    availo: products.Product,
    product_requests: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "groq_api_key", "not-a-real-key")  # the model itself is scripted below
    script = [("open_questionnaire", {"file_name": ""})]
    monkeypatch.setattr(assistant, "_agent", lambda tools, **named: _graph(script)(tools))

    page.goto("/")
    chip, pick = page.locator("#productChip"), page.locator("#productPick")
    expect(pick).to_have_value("")
    expect(pick).to_be_enabled()
    page.select_option("#productPick", availo.id)
    colour = chip.evaluate("el => getComputedStyle(el).getPropertyValue('--product').trim()")
    assert colour == "#16a34a", "the chip takes the product's colour"

    page.set_input_files("#fileInput", str(shapes.status_and_comment(tmp_path / "HR.xlsx")))
    page.fill("#prompt", "Read this")
    page.click("#send")
    expect(page.locator("#historyList .convo.on .tag.product")).to_have_text("Availo")

    [chat] = conversations.recent(TEAM)
    assert chat["product_id"] == availo.id, "the chat started for the chip's product"
    assert batches.recent(TEAM)[0]["product_id"] == availo.id, "and its questionnaire with it"
    expect(pick).to_be_disabled()  # the chat's badge from now on
    expect(pick).to_have_value(availo.id)
    expect(chip).to_have_attribute("title", re.compile("Fixed for this chat"))

    page.click("#newChat")
    expect(pick).to_be_enabled()
    expect(pick).to_have_value(availo.id)  # a new conversation keeps the choice
    page.select_option("#productPick", "")  # for the next chat; nothing is sent
    page.click("#historyList .convo")  # the earlier chat
    expect(pick).to_be_disabled()
    expect(pick).to_have_value(availo.id)
    page.click("#newChat")
    expect(pick).to_be_enabled()
    expect(pick).to_have_value("")  # the person's last choice, not the chat that was open

    assert not product_requests, "the page never asks to change a chat's product"
    assert conversations.load(chat["id"]).product_id == availo.id


def test_a_questionnaire_is_opened_for_the_product_chosen_and_fixed_until_closed(
    page: Page,
    tmp_path: Path,
    availo: products.Product,
    answers_from_availo: None,
    product_requests: list[str],
) -> None:
    page.goto("/workbench")
    selector, hint, close = page.locator("#formProduct"), page.locator("#formProductHint"), page.locator("#closeForm")
    page.select_option("#formProduct", availo.id)
    expect(hint).to_contain_text("Availo's knowledge base and answer memory")
    expect(close).to_be_hidden()
    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))
    page.click("#extractBtn")
    questions = page.get_by_role("textbox", name="Type a question")
    expect(questions).to_have_count(4)
    [opened] = batches.recent(TEAM)
    assert opened["product_id"] == availo.id
    expect(selector).to_be_disabled()
    expect(selector).to_have_value(availo.id)
    expect(hint).to_contain_text("Fixed for this questionnaire")

    page.click("#answerBtn")
    expect(page.locator("#results").get_by_text(ANSWER).first).to_be_visible(timeout=15_000)
    expect(page.locator("#results .cite .tag.product").first).to_have_text("Availo")

    close.click()
    expect(page.locator("#extractStatus")).to_contain_text("Closed vendor.xlsx")
    expect(selector).to_be_enabled()
    expect(questions).to_have_count(0)
    expect(page.locator("#resultsCard")).to_be_hidden()
    expect(close).to_be_hidden()
    assert batches.recent(TEAM)[0]["product_id"] == availo.id, "closing changes nothing on the server"

    # Offered to pick up, with its badge, and fixed again when it is.
    expect(page.locator("#formRecent .tag.product")).to_have_text("Availo")
    page.select_option("#formProduct", "")
    page.locator("#formRecent button", has_text="vendor.xlsx").click()
    expect(selector).to_have_value(availo.id)
    expect(selector).to_be_disabled()
    assert not product_requests, "the page never asks to change a questionnaire's product"


def test_a_typed_list_keeps_its_product_while_its_answers_are_on_the_page(
    page: Page, availo: products.Product, answers_from_availo: None
) -> None:
    page.goto("/workbench")
    selector = page.locator("#formProduct")
    page.select_option("#formProduct", availo.id)
    page.click("#addQuestionBtn")
    page.get_by_role("textbox", name="Type a question").last.fill("Do you encrypt backups?")
    expect(selector).to_be_enabled()  # nothing answered yet

    page.click("#answerBtn")
    expect(page.locator("#results").get_by_text(ANSWER).first).to_be_visible(timeout=15_000)
    expect(selector).to_be_disabled()
    expect(page.locator("#formProductHint")).to_contain_text("clear the list to choose another product")

    page.once("dialog", lambda dialog: dialog.accept())
    page.click("#clearQuestions")
    expect(selector).to_be_enabled()


def test_a_deleted_product_chosen_before_the_first_message_is_refused_beside_the_box(
    page: Page, availo: products.Product, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "groq_api_key", "not-a-real-key")  # the route has to reach the product check
    monkeypatch.setattr(assistant, "_agent", lambda tools, **named: _graph([])(tools))
    gone = products.add(None, TEAM, "Msegat", color="#dc2626")

    page.goto("/")
    page.select_option("#productPick", gone.id)
    products.delete(identity.local_user(), TEAM, gone.id, "confirm")  # the tab now offers a deleted product

    page.fill("#prompt", "Do we encrypt backups?")
    page.click("#send")
    note = page.locator("#composerNote")
    expect(note).to_be_visible()
    expect(note).to_have_class("status error composer-note")
    expect(note).to_contain_text("Msegat has been deleted")
    expect(note).not_to_contain_text(gone.id)

    pick = page.locator("#productPick")
    expect(pick).to_have_value("")  # back on General
    expect(pick).to_be_enabled()
    expect(pick.locator("option", has_text="Msegat")).to_have_count(0)
    style = page.locator("#productChip").get_attribute("style") or ""
    assert "--product" not in style, "the chip is General's colour again"
    expect(page.locator("#thread .turn")).to_have_count(0)  # nothing was said, so nothing is shown as said
    expect(page.locator("#empty")).to_be_visible()
    expect(page.locator("#prompt")).to_have_value("Do we encrypt backups?")
    assert conversations.recent(TEAM) == [], "nothing was saved"

    page.click("#send")  # as General, now
    expect(page.locator("#thread .turn.assistant")).to_have_count(1)
    expect(note).to_be_hidden()
    [chat] = conversations.recent(TEAM)
    assert chat["product_id"] == ""


def test_the_chip_is_fixed_while_the_first_message_is_on_its_way(
    page: Page, availo: products.Product, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "groq_api_key", "not-a-real-key")
    monkeypatch.setattr(assistant, "_agent", lambda tools, **named: _graph([])(tools))
    held = []
    page.route("**/api/chat", lambda route: held.append(route) if route.request.method == "POST" else route.continue_())

    page.goto("/")
    pick = page.locator("#productPick")
    page.select_option("#productPick", availo.id)
    page.fill("#prompt", "Hello")
    page.click("#send")
    page.wait_for_function("() => document.querySelector('#thread .turn.working') !== null")
    expect(pick).to_be_disabled()  # before the server has answered: the chat starts for this product
    assert len(held) == 1
    held[0].continue_()

    expect(page.locator("#thread .turn.assistant:not(.working)")).to_have_count(1)
    expect(pick).to_be_disabled()
    [chat] = conversations.recent(TEAM)
    assert chat["product_id"] == availo.id


def test_a_deleted_product_chosen_for_a_chat_with_a_file_keeps_the_file_attached(
    page: Page, tmp_path: Path, availo: products.Product, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "groq_api_key", "not-a-real-key")  # the route has to reach the product check
    monkeypatch.setattr(assistant, "_agent", lambda tools, **named: _graph([])(tools))
    gone = products.add(None, TEAM, "Msegat", color="#dc2626")

    page.goto("/")
    page.select_option("#productPick", gone.id)
    products.delete(identity.local_user(), TEAM, gone.id, "confirm")
    page.set_input_files("#fileInput", str(shapes.status_and_comment(tmp_path / "HR.xlsx")))
    page.fill("#prompt", "Read this")
    page.click("#send")

    expect(page.locator("#composerNote")).to_contain_text("Msegat has been deleted")
    expect(page.locator("#attached")).to_be_visible()
    expect(page.locator("#attachedName")).to_have_text("HR.xlsx")
    expect(page.locator("#thread .turn")).to_have_count(0)
    expect(page.locator("#prompt")).to_have_value("Read this")
    expect(page.locator("#productPick")).to_have_value("")
    assert conversations.recent(TEAM) == [], "nothing was saved"
    folder = settings.user_upload_dir(TEAM, identity.local_user().email)
    assert not folder.exists() or not any(folder.iterdir()), "and no file was kept"


def test_a_product_deleted_after_the_workbench_listed_it_is_said_when_a_file_is_opened(
    page: Page, tmp_path: Path, availo: products.Product
) -> None:
    """The workbench's twin of the chat's refusal: the upload is refused before
    anything is kept, and the page said nothing true about why."""
    gone = products.add(None, TEAM, "Msegat", color="#dc2626")
    page.goto("/workbench")
    page.select_option("#formProduct", gone.id)
    products.delete(identity.local_user(), TEAM, gone.id, "confirm")

    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))
    page.click("#extractBtn")

    status = page.locator("#extractStatus")
    expect(status).to_contain_text("Msegat has been deleted, so the file was not opened for it")
    expect(status).not_to_contain_text(gone.id)
    expect(status).not_to_contain_text("not supported")
    selector = page.locator("#formProduct")
    expect(selector).to_have_value("")
    expect(selector.locator("option", has_text="Msegat")).to_have_count(0)
    assert batches.recent(TEAM) == []

    page.click("#extractBtn")  # as General, now
    expect(page.get_by_role("textbox", name="Type a question")).to_have_count(4)
    assert batches.recent(TEAM)[0]["product_id"] == ""


def test_closing_a_questionnaire_asks_about_typed_answers_and_forgets_the_fill(
    page: Page, tmp_path: Path, availo: products.Product, answers_from_availo: None
) -> None:
    page.goto("/workbench")
    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))
    page.click("#extractBtn")
    questions = page.get_by_role("textbox", name="Type a question")
    expect(questions).to_have_count(4)
    page.click("#addQuestionBtn")
    questions.last.fill("Do you test your backups?")
    page.click("#answerBtn")
    expect(page.locator("#results .answer")).to_have_count(5, timeout=15_000)
    page.click("#fillFormBtn")
    expect(page.locator("#formFilled")).to_be_visible()

    asked: list[str] = []

    def dismiss(dialog) -> None:
        asked.append(dialog.message)
        dialog.dismiss()

    page.once("dialog", dismiss)
    page.click("#closeForm")
    assert "1 question(s) typed beside it are not part of the file and will go" in asked[0]
    assert "and so will the answers to 1 of them" in asked[0]
    rows = page.locator("#questionList .qrow")
    expect(rows).to_have_count(5)  # dismissed: nothing went
    expect(page.locator("#results .answer", has_text="Do you test your backups?")).to_be_visible()
    expect(page.locator("#closeForm")).to_be_visible()

    page.once("dialog", lambda dialog: dialog.accept())
    page.click("#closeForm")
    expect(rows).to_have_count(0)
    expect(page.locator("#closeForm")).to_be_hidden()
    expect(page.locator("#formFilled")).to_be_hidden()

    page.click("#addQuestionBtn")
    questions.last.fill("Do you encrypt backups?")
    page.click("#answerBtn")
    expect(page.locator("#results .answer")).to_have_count(1, timeout=15_000)
    expect(page.locator("#formFilled")).to_be_hidden()  # the closed file's fill is not shown again
    expect(page.locator("#extractStatus")).to_contain_text("Closed vendor.xlsx. It stays in")
    expect(page.locator("#formRecent button").first).to_contain_text("vendor.xlsx")


def test_close_waits_for_a_request_about_the_questionnaire(
    page: Page, tmp_path: Path, availo: products.Product, answers_from_availo: None
) -> None:
    """A reply arriving after Close opened the closed questionnaire again."""
    page.goto("/workbench")
    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))
    page.click("#extractBtn")
    page.click("#answerBtn")
    expect(page.locator("#results .answer")).to_have_count(4, timeout=15_000)
    held = []
    page.route("**/approve", lambda route: held.append(route))

    page.locator("#results button.approve").first.click()
    close = page.locator("#closeForm")
    expect(close).to_be_disabled()
    held[0].continue_()
    expect(close).to_be_enabled()
    close.click()
    expect(close).to_be_hidden()
    expect(page.get_by_role("textbox", name="Type a question")).to_have_count(0)


def test_chat_sources_from_a_product_carry_its_badge(
    page: Page, availo: products.Product, monkeypatch: pytest.MonkeyPatch
) -> None:
    hits = [
        Evidence(
            source_type=SourceType.GUIDELINE,
            source_name="Availo backup standard.pdf",
            snippet="Backups are encrypted with a key per tenant.",
            product_id=availo.id,
            chunk=0,
        ),
        Evidence(
            source_type=SourceType.GUIDELINE,
            source_name="Availo backup standard.pdf",
            snippet="Backup keys are rotated every year.",
            product_id=availo.id,
            chunk=1,
        ),
        Evidence(
            source_type=SourceType.GUIDELINE,
            source_name="Shared policy.pdf",
            snippet="Backups are kept for ninety days.",
            chunk=0,
        ),
    ]

    async def search(query, **scope):
        return {"query": query, "results": [hit.model_dump() for hit in hits], "documents": []}

    monkeypatch.setattr("src.tools.search", search)
    monkeypatch.setattr(settings, "groq_api_key", "not-a-real-key")
    script = [("search_policies", {"query": "backups"})]
    monkeypatch.setattr(assistant, "_agent", lambda tools, **named: _graph(script)(tools))

    page.goto("/")
    page.select_option("#productPick", availo.id)
    page.fill("#prompt", "Do we encrypt backups?")
    page.click("#send")
    page.locator(".turn .sources summary").click()

    own = page.locator(".turn .cite", has_text="Availo backup standard")
    expect(own).to_have_count(2)  # two passages of one document with one locator, not collapsed into one
    expect(own.first.locator(".tag.product")).to_have_text("Availo")
    shared = page.locator(".turn .cite", has_text="Shared policy")
    expect(shared).to_have_count(1)
    expect(shared.locator(".tag.product")).to_have_count(0)

    own.first.click()
    expect(page.locator(".turn .cite-panel .cite-head .tag.product").first).to_have_text("Availo")
