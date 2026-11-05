"""A questionnaire or a chat is never for General by accident (plan 029, 2), in a real browser.

The user's rule (2026-11-05): no silent General. Both pages start with no
product chosen; General is one of the choices, chosen on purpose. Reading a
file, answering a list of questions and a new chat's first message wait for a
choice. "Last used" fills the choice in one click and is never chosen for the
person: it is derived from their own questionnaires and chats, and from what
they did on the page. A fixed product shows as a label in its colour.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from playwright.sync_api import Page, expect

from src import batches, conversations, identity, knowledge, products, tools
from src.agents import assistant
from src.config import settings
from src.models import AnsweredQuestion
from tests import forms_fixtures as shapes
from tests.conftest import FakeVectorStore, bare_store
from tests.test_assistant import _graph

pytestmark = pytest.mark.browser

TEAM = settings.default_team
ANSWER = "Yes, backups are encrypted with a key per tenant."
UNCHOSEN = re.compile(r"\bunchosen\b")


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
def answers_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def answered(questions, language=None, run_id=None, **extra):
        return [AnsweredQuestion(question=q, answer=ANSWER, confidence=0.9) for q in questions]

    monkeypatch.setattr("src.tools.service.answer_questions", answered)


@pytest.fixture
def chat_replies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "groq_api_key", "not-a-real-key")  # the model itself is scripted
    monkeypatch.setattr(assistant, "_agent", lambda tools, **named: _graph([])(tools))


def delete(product: products.Product) -> None:
    products.delete(identity.local_user(), TEAM, product.id, "confirm")


def chat(title: str, product_id: str = "") -> None:
    """A saved chat of the local user's, as the history lists it."""
    conversation = assistant.start(identity.local_user(), title, product_id)
    conversation.messages = [HumanMessage(title), AIMessage("Hello again.")]
    conversations.save(conversation)


# --- 2.1 the Workbench waits for a product ------------------------------------


def test_the_workbench_starts_with_no_product_and_reading_waits_for_one(
    page: Page, tmp_path: Path, availo: products.Product
) -> None:
    """The selector started on General, and Read opened the file for it as soon as one was chosen."""
    page.goto("/workbench")
    selector = page.locator("#formProduct")
    expect(selector).to_have_value("")
    expect(selector.locator("option:checked")).to_have_text("Product: choose…")
    expect(selector.locator("option[value='general']")).to_have_text("General (shared policies only)")
    expect(page.locator("#formProductChip")).to_have_class(UNCHOSEN)
    expect(page.locator("#formProductHint")).to_contain_text("Choose the product this questionnaire is for")

    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))
    read = page.locator("#extractBtn")
    expect(read).to_be_disabled()
    expect(read).to_have_text("Read questions from file")
    expect(page.locator("#readNeedsProduct")).to_be_visible()
    expect(page.locator("#readNeedsProduct")).to_have_text("Choose a product first.")

    page.select_option("#formProduct", "general")
    expect(read).to_be_enabled()
    expect(read).to_have_text("Read questions for General")
    expect(page.locator("#readNeedsProduct")).to_be_hidden()
    expect(page.locator("#formProductChip")).not_to_have_class(UNCHOSEN)
    read.click()

    expect(page.get_by_role("textbox", name="Type a question")).to_have_count(4)
    [opened] = batches.recent(TEAM)
    assert opened["product_id"] == "", "General, chosen on purpose, is sent as the server's General"
    expect(selector.locator("option:checked")).to_have_text("General (shared policies only)")
    expect(selector).to_be_disabled()


def test_typed_questions_wait_for_a_product_before_answering(
    page: Page, availo: products.Product, answers_yes: None
) -> None:
    sent: list[dict] = []
    page.on(
        "request",
        lambda request: (
            sent.append(request.post_data_json) if request.url.endswith("/api/assessments/answer-questions") else None
        ),
    )
    page.goto("/workbench")
    page.click("#addQuestionBtn")
    page.get_by_role("textbox", name="Type a question").last.fill("Do you encrypt backups?")

    answer, composer = page.locator("#answerBtn"), page.locator("#composerAnswer")
    expect(answer).to_have_text("Answer 1 question")
    expect(answer).to_be_disabled()
    expect(composer).to_be_disabled()
    hint = page.locator("#answerNeedsProduct")
    expect(hint).to_be_visible()
    expect(hint).to_contain_text("Choose a product first.")
    hint.get_by_role("button", name="Choose…").click()
    expect(page.locator("#formProduct")).to_be_focused()

    page.select_option("#formProduct", availo.id)
    expect(hint).to_be_hidden()
    expect(answer).to_be_enabled()
    answer.click()
    expect(page.locator("#results").get_by_text(ANSWER).first).to_be_visible(timeout=15_000)
    assert [body["product"] for body in sent] == [availo.id]


def test_closing_a_questionnaire_goes_back_to_choose(
    page: Page, tmp_path: Path, availo: products.Product, product_requests: list[str]
) -> None:
    """Close kept the closed questionnaire's product chosen for the next file."""
    page.goto("/workbench")
    page.select_option("#formProduct", availo.id)
    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))
    page.click("#extractBtn")
    expect(page.get_by_role("textbox", name="Type a question")).to_have_count(4)

    page.click("#closeForm")
    selector = page.locator("#formProduct")
    expect(selector).to_be_enabled()
    expect(selector).to_have_value("")
    expect(page.locator("#formProductChip")).to_have_class(UNCHOSEN)
    expect(page.locator("#extractBtn")).to_be_disabled()  # the same file, still chosen, waits again

    page.click("#addQuestionBtn")
    page.get_by_role("textbox", name="Type a question").last.fill("Do you encrypt backups?")
    expect(page.locator("#answerBtn")).to_be_disabled()
    assert not product_requests, "nothing about a product was sent"


def test_a_new_spreadsheet_read_while_one_is_open_says_whose_product_it_takes(
    page: Page, tmp_path: Path, availo: products.Product
) -> None:
    """While a questionnaire is open, another file is opened for its product, and nothing said so."""
    page.goto("/workbench")
    page.select_option("#formProduct", availo.id)
    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))
    page.click("#extractBtn")
    expect(page.get_by_role("textbox", name="Type a question")).to_have_count(4)

    page.set_input_files("#assessmentInput", str(shapes.status_and_comment(tmp_path / "other.xlsx")))
    read = page.locator("#extractBtn")
    expect(read).to_have_text("Read questions for Availo")
    expect(read).to_be_enabled()


def test_a_reload_chooses_nothing(page: Page, availo: products.Product) -> None:
    page.goto("/workbench")
    page.select_option("#formProduct", availo.id)
    page.reload()

    selector = page.locator("#formProduct")
    expect(selector.locator("option", has_text="Availo")).to_have_count(1)  # the products are listed
    expect(selector).to_have_value("")
    expect(selector.locator("option:checked")).to_have_text("Product: choose…")


@pytest.mark.parametrize(("address", "selector"), [("/workbench", "#formProduct"), ("/", "#productPick")])
def test_general_chosen_before_the_products_arrive_stays_chosen(
    page: Page, availo: products.Product, address: str, selector: str
) -> None:
    """Found by the suite: the page read the choice before asking for the products, and put it
    back to "choose…" when they arrived, so a quick choice of General was silently undone."""
    held: list = []
    released: list[bool] = []
    page.route("**/api/products", lambda route: route.continue_() if released else held.append(route))
    page.goto(address)
    for _ in range(200):
        if held:
            break
        page.wait_for_timeout(25)
    assert held, "the page asked for its products"

    page.select_option(selector, "general")
    released.append(True)
    for route in held:
        route.continue_()

    expect(page.locator(selector).locator("option", has_text="Availo")).to_have_count(1)  # the list arrived
    expect(page.locator(selector)).to_have_value("general")


def test_a_page_whose_products_could_not_be_loaded_says_so(
    page: Page, tmp_path: Path, availo: products.Product, chat_replies: None
) -> None:
    """With the products missing, the selector offered General alone, without a word."""
    tools.open_form(identity.local_user(), shapes.simple(tmp_path / "vendor.xlsx"), product_id=availo.id)
    page.route("**/api/products", lambda route: route.fulfill(status=503, json={"detail": "down"}))

    page.goto("/workbench")
    expect(page.locator("#formProductHint")).to_contain_text("Your products could not be loaded")
    expect(page.locator("#formProduct")).to_have_value("")
    expect(page.locator("#formLastUsed button")).to_have_count(0)  # Availo is not known to be choosable

    page.goto("/")
    expect(page.locator("#productNeeded")).to_contain_text("Your products could not be loaded")
    expect(page.locator("#productPick")).to_have_value("")


# --- 2.2 the chat waits for a product -----------------------------------------


def test_a_new_chat_waits_for_a_product_before_sending(
    page: Page, availo: products.Product, chat_replies: None
) -> None:
    """General was preselected, so Send and Enter started a General chat."""
    posted: list[str] = []
    page.on(
        "request",
        lambda request: (
            posted.append(request.url) if request.method == "POST" and request.url.endswith("/api/chat") else None
        ),
    )
    page.goto("/")
    pick, send, needed = page.locator("#productPick"), page.locator("#send"), page.locator("#productNeeded")
    expect(pick).to_have_value("")
    expect(pick.locator("option:checked")).to_have_text("Product: choose…")
    expect(page.locator("#productChip")).to_have_class(UNCHOSEN)
    expect(needed).to_be_visible()
    expect(needed).to_contain_text("Which product is this chat for?")

    page.fill("#prompt", "Do we encrypt backups?")
    expect(send).to_be_disabled()
    expect(needed).to_contain_text("Choose a product to send this.")
    expect(needed).to_have_class(re.compile(r"\bwarn\b"))
    page.press("#prompt", "Enter")  # past the disabled button
    page.wait_for_timeout(300)
    expect(page.locator("#thread .turn")).to_have_count(0)
    expect(page.locator("#prompt")).to_have_value("Do we encrypt backups?")
    assert posted == [], "nothing was sent"

    page.select_option("#productPick", "general")
    expect(send).to_be_enabled()
    expect(needed).to_be_hidden()
    send.click()
    expect(page.locator("#thread .turn.assistant:not(.working)")).to_have_count(1)
    [started] = conversations.recent(TEAM)
    assert started["product_id"] == ""
    expect(pick).to_be_disabled()  # the chat's label from now on
    expect(pick.locator("option:checked")).to_have_text("General (shared policies only)")


def test_a_file_can_be_attached_before_the_product_but_not_sent(
    page: Page, tmp_path: Path, availo: products.Product, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "groq_api_key", "not-a-real-key")
    script = [("open_questionnaire", {"file_name": ""})]
    monkeypatch.setattr(assistant, "_agent", lambda tools, **named: _graph(script)(tools))

    page.goto("/")
    page.set_input_files("#fileInput", str(shapes.status_and_comment(tmp_path / "HR.xlsx")))
    expect(page.locator("#attached")).to_be_visible()
    send = page.locator("#send")
    expect(send).to_be_disabled()
    expect(page.locator("#productNeeded")).to_contain_text("Choose a product to send this.")
    assert batches.recent(TEAM) == [], "the file stays in the page until Send"

    page.select_option("#productPick", availo.id)
    expect(send).to_be_enabled()
    send.click()
    expect(page.locator("#historyList .convo.on .tag.product")).to_have_text("Availo")
    assert batches.recent(TEAM)[0]["product_id"] == availo.id


def test_new_conversation_from_an_open_chat_chooses_nothing(page: Page, availo: products.Product) -> None:
    """New conversation kept the chip's last choice, or General after a reload."""
    chat("About Availo", availo.id)
    page.goto("/")
    page.locator("#historyList .convo").click()
    pick = page.locator("#productPick")
    expect(pick).to_have_value(availo.id)
    expect(pick).to_be_disabled()

    page.click("#newChat")
    expect(pick).to_be_enabled()
    expect(pick).to_have_value("")
    expect(page.locator("#productChip")).to_have_class(UNCHOSEN)
    page.fill("#prompt", "Hello")
    expect(page.locator("#send")).to_be_disabled()


# --- 2.3 "Last used", in one click, never chosen ------------------------------


def test_last_used_comes_from_the_persons_latest_questionnaire_and_is_never_chosen(
    page: Page, tmp_path: Path, availo: products.Product, product_requests: list[str]
) -> None:
    tools.open_form(identity.local_user(), shapes.simple(tmp_path / "vendor.xlsx"), product_id=availo.id)
    page.goto("/workbench")
    selector, offer = page.locator("#formProduct"), page.locator("#formLastUsed button")
    expect(offer).to_have_text("Last used: Availo")
    expect(offer.locator(".tag.product")).to_have_text("Availo")
    expect(selector).to_have_value("")

    offer.click()
    expect(selector).to_have_value(availo.id)
    expect(selector).to_be_enabled()
    expect(selector).to_be_focused()
    expect(offer).to_have_count(0)
    assert not product_requests
    assert len(batches.recent(TEAM)) == 1, "a click chooses; it opens nothing"

    page.reload()
    expect(offer).to_have_text("Last used: Availo")
    expect(selector).to_have_value("")


def test_a_questionnaire_reopened_from_its_address_shows_its_product_and_offers_nothing(
    page: Page, tmp_path: Path, availo: products.Product
) -> None:
    """Plan 029, 1.1 with 2: the reopened questionnaire's product is its label, at once."""
    batch = tools.open_form(identity.local_user(), shapes.simple(tmp_path / "vendor.xlsx"), product_id=availo.id)
    page.goto(f"/workbench?q={batch.id}")

    expect(page.get_by_role("textbox", name="Type a question")).to_have_count(4)
    selector = page.locator("#formProduct")
    expect(selector).to_have_value(availo.id)
    expect(selector).to_be_disabled()
    expect(page.locator("#formProductChip")).not_to_have_class(UNCHOSEN)
    expect(page.locator("#formLastUsed button")).to_have_count(0)
    expect(page.locator("#readNeedsProduct")).to_be_hidden()


def test_closing_a_questionnaire_offers_its_product_as_last_used(
    page: Page, tmp_path: Path, availo: products.Product
) -> None:
    user = identity.local_user()
    tools.open_form(user, shapes.simple(tmp_path / "general.xlsx"))  # the older one, for General
    tools.open_form(user, shapes.simple(tmp_path / "vendor.xlsx"), product_id=availo.id)

    page.goto("/workbench")
    offer = page.locator("#formLastUsed button")
    expect(offer).to_have_text("Last used: Availo")  # the most recently changed questionnaire

    page.locator("#formRecent button", has_text="general.xlsx").click()
    expect(page.locator("#formProduct")).to_have_value("general")
    page.click("#closeForm")
    expect(offer).to_have_text("Last used: General")  # what was done on the page comes first
    expect(page.locator("#formProduct")).to_have_value("")
    offer.click()
    expect(page.locator("#formProduct")).to_have_value("general")


def test_last_used_skips_a_deleted_product(page: Page, tmp_path: Path, availo: products.Product) -> None:
    user = identity.local_user()
    msegat = products.add(None, TEAM, "Msegat", color="#dc2626")
    tools.open_form(user, shapes.simple(tmp_path / "a.xlsx"), product_id=availo.id)
    tools.open_form(user, shapes.simple(tmp_path / "b.xlsx"), product_id=msegat.id)
    delete(msegat)

    page.goto("/workbench")
    expect(page.locator("#formLastUsed button")).to_have_text("Last used: Availo")


def test_new_conversation_suggests_the_chat_that_was_open(page: Page, availo: products.Product) -> None:
    chat("About Availo", availo.id)
    chat("About everything")  # General, the most recent

    page.goto("/")
    offer, pick = page.locator("#chatLastUsed button"), page.locator("#productPick")
    expect(offer).to_have_text("Last used: General")
    expect(pick).to_have_value("")

    page.locator("#historyList .convo", has_text="About Availo").click()
    expect(pick).to_have_value(availo.id)
    page.click("#newChat")
    expect(pick).to_have_value("")
    expect(offer).to_have_text("Last used: Availo")
    expect(offer.locator(".tag.product")).to_have_text("Availo")

    offer.click()
    expect(pick).to_have_value(availo.id)
    expect(page.locator("#prompt")).to_be_focused()
    expect(page.locator("#productNeeded")).to_be_hidden()
    page.fill("#prompt", "Hello")
    expect(page.locator("#send")).to_be_enabled()

    page.reload()
    expect(offer).to_have_text("Last used: General")  # from the chats, the most recently used
    expect(pick).to_have_value("")


def test_last_used_in_the_chat_skips_a_deleted_product(page: Page, availo: products.Product) -> None:
    msegat = products.add(None, TEAM, "Msegat", color="#dc2626")
    chat("About Availo", availo.id)
    chat("About Msegat", msegat.id)
    delete(msegat)

    page.goto("/")
    expect(page.locator("#chatLastUsed button")).to_have_text("Last used: Availo")


# --- 2.4 a fixed product is a label -------------------------------------------


def test_the_review_heading_names_the_product(page: Page, tmp_path: Path, availo: products.Product) -> None:
    """A reviewer a hundred cards down approved into a memory they could not see from there."""
    user = identity.local_user()
    for name, product_id in (("availo.xlsx", availo.id), ("general.xlsx", "")):
        batch = tools.open_form(user, shapes.simple(tmp_path / name), product_id=product_id)
        question = next(q for q in batch.form.questions if q.writable)
        tools.set_answer(user, batch.id, question.id, "We do.")

    page.goto("/workbench")
    label = page.locator("#resultsProduct .tag.product")
    page.locator("#formRecent button", has_text="availo.xlsx").click()
    expect(page.locator("#results .answer")).to_have_count(1)
    expect(label).to_have_text("Availo")

    page.click("#closeForm")
    page.locator("#formRecent button", has_text="general.xlsx").click()
    expect(page.locator("#results .answer")).to_have_count(1)
    expect(label).to_have_text("General")
    expect(page.locator("#formProduct option:checked")).to_have_text("General (shared policies only)")
