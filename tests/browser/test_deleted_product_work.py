"""A deleted product's questionnaires and chats, kept read-only, in a real browser (plan 027).

The user's decision: they stay listed, marked as from a deleted product, and
read-only. They can be read, and a questionnaire filled and its file
downloaded; nothing in them can be answered, edited, approved or chatted in.
The pages say so calmly, and leave out every control that would change them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from playwright.sync_api import Page, expect

from src import conversations, identity, knowledge, products, tools
from src.agents import assistant
from src.config import settings
from tests import forms_fixtures as shapes
from tests.conftest import FakeVectorStore, bare_store
from tests.test_assistant import _graph

pytestmark = pytest.mark.browser

TEAM = settings.default_team
WRITTEN = "Yes, every backup is encrypted."


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


def delete(product: products.Product) -> None:
    products.delete(identity.local_user(), TEAM, product.id, "confirm")


def test_a_deleted_products_questionnaire_is_shown_read_only_and_can_still_be_filled(
    page: Page, tmp_path: Path, availo: products.Product
) -> None:
    user = identity.local_user()
    batch = tools.open_form(user, shapes.simple(tmp_path / "vendor.xlsx"), product_id=availo.id)
    question = next(q for q in batch.form.questions if q.writable)
    tools.set_answer(user, batch.id, question.id, WRITTEN)
    tools.approve_answer(user, batch.id, question.id)
    delete(availo)

    page.goto("/workbench")
    offered = page.locator("#formRecent button", has_text="vendor.xlsx")
    expect(offered.locator(".tag.product.deleted")).to_have_text("Availo · deleted")
    offered.click()

    note = page.locator("#formReadOnly")
    expect(note).to_be_visible()
    expect(note).to_contain_text("Availo was deleted")
    expect(note).to_contain_text("can no longer be answered, edited or approved")
    expect(note).not_to_contain_text(availo.id)
    selector = page.locator("#formProduct")
    expect(selector).to_be_disabled()
    expect(selector).to_have_value(availo.id)
    expect(selector.locator("option:checked")).to_have_text("Availo (deleted)")

    for control in (
        "#answerBtn",
        "#addQuestionBtn",
        "#clearQuestions",
        "#answerStyle",
        "#detailPick",
        "#reviseRow",
        "#composer",
        "#extractBtn",
    ):
        expect(page.locator(control)).to_be_hidden()
    expect(page.locator("#questionList .qactions button")).to_have_count(0)
    expect(page.locator("#questionList textarea:enabled")).to_have_count(0)
    expect(page.locator("#formColumns select:enabled")).to_have_count(0)

    card = page.locator("#results .answer", has_text=WRITTEN)
    expect(card).to_be_visible()
    expect(card.get_by_role("button", name="Approve")).to_have_count(0)
    expect(card.get_by_role("button", name="Edit")).to_be_hidden()
    expect(card.get_by_role("button", name="Leave blank")).to_have_count(0)
    expect(card.locator(".tag", has_text="approved")).to_be_visible()

    expect(page.locator("#questionListHint")).to_contain_text("Kept to read")
    page.click("#fillFormBtn")
    filled = page.locator("#formFilled")
    expect(filled).to_contain_text("Wrote 1 value(s) into")
    with page.expect_download() as download:
        filled.get_by_role("button", name="Download the filled file").click()
    assert download.value.suggested_filename.endswith(".xlsx")

    page.click("#closeForm")
    expect(note).to_be_hidden()
    expect(selector).to_be_enabled()
    expect(selector).to_have_value("")
    expect(selector.locator("option", has_text="(deleted)")).to_have_count(0)
    expect(page.locator("#answerBtn")).to_be_visible()


def test_a_questionnaire_open_when_its_product_is_deleted_turns_read_only(
    page: Page, tmp_path: Path, availo: products.Product
) -> None:
    """A page opened before the deletion learns it from the refusal of its next
    change, or when the person comes back to the tab, and redraws itself so."""
    user = identity.local_user()
    batch = tools.open_form(user, shapes.simple(tmp_path / "vendor.xlsx"), product_id=availo.id)
    question = next(q for q in batch.form.questions if q.writable)
    tools.set_answer(user, batch.id, question.id, WRITTEN)

    page.goto("/workbench")
    page.locator("#formRecent button", has_text="vendor.xlsx").click()
    card = page.locator("#results .answer", has_text=WRITTEN)
    expect(card.get_by_role("button", name="Approve")).to_be_visible()
    delete(availo)  # in another tab, by a lead

    card.get_by_role("button", name="Approve").click()
    expect(page.locator("#answerStatus")).to_contain_text("Availo was deleted, so this is kept read-only")
    expect(page.locator("#formReadOnly")).to_be_visible()
    expect(page.locator("#results .answer", has_text=WRITTEN).get_by_role("button", name="Approve")).to_have_count(0)
    expect(page.locator("#formProduct option:checked")).to_have_text("Availo (deleted)")

    page.click("#closeForm")
    page.locator("#formRecent button", has_text="vendor.xlsx").click()
    expect(page.locator("#formReadOnly")).to_be_visible()  # and so it opens from now on


def test_coming_back_to_a_chat_whose_product_was_deleted_shows_it_read_only(
    page: Page, availo: products.Product
) -> None:
    conversation = assistant.start(identity.local_user(), "Hello", availo.id)
    conversation.messages = [HumanMessage("Hello"), AIMessage("Hello again.")]
    conversations.save(conversation)

    page.goto("/")
    page.locator("#historyList .convo").click()
    expect(page.locator("#prompt")).to_be_enabled()
    delete(availo)
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")  # the person comes back to the tab

    expect(page.locator("#composerNote")).to_contain_text("Availo was deleted. This chat is kept so you can read it")
    expect(page.locator("#prompt")).to_be_disabled()
    expect(page.locator("#historyList .convo .tag.product.deleted")).to_have_text("Availo · deleted")


def test_a_deleted_products_chat_is_shown_read_only(page: Page, availo: products.Product) -> None:
    conversation = assistant.start(identity.local_user(), "Hello", availo.id)
    conversation.messages = [HumanMessage("Hello"), AIMessage("Hello again.")]
    conversations.save(conversation)
    delete(availo)

    page.goto("/")
    listed = page.locator("#historyList .convo")
    expect(listed.locator(".tag.product.deleted")).to_have_text("Availo · deleted")
    listed.click()

    expect(page.locator("#thread .turn")).to_have_count(2)
    expect(page.locator("#prompt")).to_be_disabled()
    expect(page.locator("#send")).to_be_disabled()
    note = page.locator("#composerNote")
    expect(note).to_be_visible()
    expect(note).to_have_class("status calm composer-note")
    expect(note).to_contain_text("Availo was deleted. This chat is kept so you can read it")
    expect(note).not_to_contain_text(availo.id)
    pick = page.locator("#productPick")
    expect(pick).to_be_disabled()
    expect(pick.locator("option:checked")).to_have_text("Availo (deleted)")

    page.click("#newChat")
    expect(page.locator("#prompt")).to_be_enabled()
    expect(note).to_be_hidden()
    expect(pick).to_be_enabled()
    expect(pick).to_have_value("")
    expect(pick.locator("option", has_text="(deleted)")).to_have_count(0)
    page.fill("#prompt", "Hello")
    expect(page.locator("#send")).to_be_enabled()


def test_a_deleted_products_chat_shows_its_questionnaire_read_only_and_can_still_fill_it(
    page: Page, tmp_path: Path, availo: products.Product
) -> None:
    """The answers beside the chat: drawn without the controls that would change them, and
    without the length and skill pickers; Fill and Download still work."""
    user = identity.local_user()
    batch = tools.open_form(user, shapes.simple(tmp_path / "vendor.xlsx"), product_id=availo.id)
    question = next(q for q in batch.form.questions if q.writable)
    tools.set_answer(user, batch.id, question.id, WRITTEN)  # typed, and not approved: a live card offers Approve
    conversation = assistant.start(user, "Open vendor.xlsx", availo.id)
    conversation.batch_id = batch.id
    conversation.messages = [HumanMessage("Open vendor.xlsx"), AIMessage("It has 4 questions.")]
    conversations.save(conversation)
    delete(availo)

    page.goto("/")
    page.locator("#historyList .convo").click()
    expect(page.locator("#composerNote")).to_contain_text("Availo was deleted")
    pane = page.locator("#answers")
    card = pane.locator(".answer", has_text=WRITTEN)
    expect(card).to_be_visible()
    expect(card.get_by_role("button", name="Approve")).to_have_count(0)
    expect(card.get_by_role("button", name="Leave blank")).to_have_count(0)
    expect(pane.locator(".pick-row")).to_have_count(0)  # the length and skill pickers change every answer

    page.click("#fillBtn")
    expect(page.locator("#thread .turn.assistant").last).to_contain_text("Wrote 1 value(s) into")
    with page.expect_download() as download:
        page.click("#downloadBtn")
    assert download.value.suggested_filename.endswith(".xlsx")


def test_a_chat_open_when_its_product_is_deleted_becomes_read_only_on_the_next_message(
    page: Page, availo: products.Product, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "groq_api_key", "not-a-real-key")  # the model itself is scripted below
    monkeypatch.setattr(assistant, "_agent", lambda tools, **named: _graph([])(tools))

    page.goto("/")
    page.select_option("#productPick", availo.id)
    page.fill("#prompt", "Hello")
    page.click("#send")
    # The reply, not the "working" placeholder drawn before the request is sent: the chat is saved by then.
    expect(page.locator("#thread .turn.assistant:not(.working)")).to_have_count(1)
    [chat] = conversations.recent(TEAM)
    delete(availo)  # in another tab, by a lead

    page.fill("#prompt", "Do we encrypt backups?")
    page.click("#send")

    note = page.locator("#composerNote")
    expect(note).to_contain_text("Availo was deleted")
    expect(page.locator("#thread .turn")).to_have_count(2)  # the refused message is taken off the page
    expect(page.locator("#prompt")).to_have_value("Do we encrypt backups?")  # the words are kept
    expect(page.locator("#prompt")).to_be_disabled()
    expect(page.locator("#send")).to_be_disabled()
    expect(page.locator("#productPick option:checked")).to_have_text("Availo (deleted)")
    assert len(conversations.load(chat["id"]).messages) == 2, "nothing was added to it"
