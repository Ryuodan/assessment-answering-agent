"""Choosing the product on the pages, in a real browser (plan 024).

Plan 018's main path: a product chosen beside the chat box, a chat and its
questionnaire started for it, its badge in the history, and the chat changed
back to General; on the workbench, a questionnaire opened for a product, its
badge on the pick-up list, a source marked as the product's own, and the
product changed after upload.
"""

from __future__ import annotations

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
        return made[key]

    monkeypatch.setattr("src.knowledge.get_store", get_store)
    identity.ensure_team(TEAM)
    return products.add(None, TEAM, "Availo", color="#16a34a")


def test_a_chat_starts_for_the_product_beside_the_box_and_changes_back(
    page: Page, tmp_path: Path, availo: products.Product, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "groq_api_key", "not-a-real-key")  # the model itself is scripted below
    script = [("open_questionnaire", {"file_name": ""})]
    monkeypatch.setattr(assistant, "_agent", lambda tools, **named: _graph(script)(tools))

    page.goto("/")
    chip = page.locator("#productChip")
    expect(page.locator("#productPick")).to_have_value("")
    page.select_option("#productPick", availo.id)
    colour = chip.evaluate("el => getComputedStyle(el).getPropertyValue('--product').trim()")
    assert colour == "#16a34a", "the chip takes the product's colour"

    page.set_input_files("#fileInput", str(shapes.status_and_comment(tmp_path / "HR.xlsx")))
    page.fill("#prompt", "Read this")
    page.click("#send")
    badge = page.locator("#historyList .convo.on .tag.product")
    expect(badge).to_have_text("Availo")

    [chat] = conversations.recent(TEAM)
    assert chat["product_id"] == availo.id, "the chat started for the chip's product"
    assert batches.recent(TEAM)[0]["product_id"] == availo.id, "and its questionnaire with it"

    page.select_option("#productPick", "")
    expect(badge).to_have_count(0)
    assert conversations.load(chat["id"]).product_id == ""
    assert batches.recent(TEAM)[0]["product_id"] == "", "the chat's questionnaire follows it"

    page.click("#newChat")
    page.select_option("#productPick", availo.id)  # for the next chat; nothing is sent yet
    page.click("#newChat")
    expect(page.locator("#productPick")).to_have_value(availo.id)  # a new conversation keeps the choice
    page.click("#historyList .convo")  # the earlier chat, now General
    expect(page.locator("#productPick")).to_have_value("")
    assert conversations.load(chat["id"]).product_id == "", "opening it changed nothing"


def test_a_questionnaire_is_opened_for_the_product_chosen_and_changed_later(
    page: Page, tmp_path: Path, availo: products.Product, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    page.goto("/workbench")
    page.select_option("#formProduct", availo.id)
    expect(page.locator("#formProductHint")).to_contain_text("Availo's knowledge base and answer memory")
    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))
    page.click("#extractBtn")
    expect(page.get_by_role("textbox", name="Type a question")).to_have_count(4)
    [opened] = batches.recent(TEAM)
    assert opened["product_id"] == availo.id

    page.click("#answerBtn")
    expect(page.locator("#results").get_by_text(ANSWER).first).to_be_visible(timeout=15_000)
    expect(page.locator("#results .cite .tag.product").first).to_have_text("Availo")

    page.reload()  # nothing open, so the questionnaire is offered to pick up, with its badge
    expect(page.locator("#formRecent .tag.product")).to_have_text("Availo")
    page.locator("#formRecent button", has_text="vendor.xlsx").click()
    expect(page.locator("#formProduct")).to_have_value(availo.id)

    page.select_option("#formProduct", "")
    expect(page.locator("#extractStatus")).to_contain_text("The answers already written stay as they are")
    assert batches.recent(TEAM)[0]["product_id"] == ""
