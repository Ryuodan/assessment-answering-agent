"""The sources an answer card cites, in a real browser (plan 027).

Remembered answers approved on one day share one citation, "Answer memory
(2026-10-01)", and since plan 027 more than one of them reaches the drafter.
Each one cited is its own chip, and each chip opens its own answer. Found by
the citation alone, every such chip opened the first, so a product's own
answer cited after a shared one could not be read on the card.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from src import batches, identity, knowledge, products
from src.config import settings
from src.models import AnsweredQuestion, Evidence, SourceType
from tests import forms_fixtures as shapes
from tests.conftest import FakeVectorStore, bare_store

pytestmark = pytest.mark.browser

TEAM = settings.default_team
ANSWER = "Yes, multi-factor authentication is enforced."


def remembered(entry_id: str, answer: str, product_id: str = "") -> Evidence:
    """One answer as the memory indexes it: "Answer memory", chunk 0, its own entry id."""
    return Evidence(
        source_type=SourceType.PRIOR_ANSWER,
        source_name="Answer memory",
        snippet=f"Q: Do you enforce MFA?\nA: {answer}",
        score=0.8,
        chunk=0,
        entry_id=entry_id,
        answered_date="2026-10-01",
        product_id=product_id,
    )


def test_each_cited_remembered_answer_has_a_chip_that_opens_it(
    page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made: dict[tuple[str, str], knowledge.KnowledgeStore] = {}

    def get_store(team_id=None, *, product_id=""):
        key = (team_id or TEAM, product_id)
        if key not in made:
            made[key] = bare_store(FakeVectorStore([]))
        return made[key]

    monkeypatch.setattr("src.knowledge.get_store", get_store)  # the page counts each knowledge base
    identity.ensure_team(TEAM)
    availo = products.add(None, TEAM, "Availo", color="#16a34a")
    shared = remembered("mem-shared", "Yes, for administrators.")
    own = remembered("mem-own", "Yes, with a hardware key for every account.", availo.id)
    assert shared.locator == own.locator == "Answer memory (2026-10-01)"

    async def answered(questions, language=None, run_id=None, **extra):
        return [
            AnsweredQuestion(
                question=q,
                answer=ANSWER,
                confidence=0.9,
                evidence=[shared, own],
                citations=[shared.locator, own.locator],  # as `finalize` cites two remembered answers
            )
            for q in questions
        ]

    monkeypatch.setattr("src.tools.service.answer_questions", answered)

    page.goto("/workbench")
    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))
    page.click("#extractBtn")
    page.click("#answerBtn")
    card = page.locator("#results .answer").first
    expect(card).to_contain_text(ANSWER, timeout=15_000)

    chips = card.locator(".cite")
    expect(chips).to_have_count(2)
    expect(chips.nth(0)).to_contain_text("Answer memory (2026-10-01)")
    expect(chips.nth(0).locator(".tag.product")).to_have_count(0)
    expect(chips.nth(1).locator(".tag.product")).to_have_text("Availo")

    panel = card.locator(".cite-panel")
    chips.nth(0).click()
    expect(panel).to_contain_text("Yes, for administrators.")
    expect(panel.locator(".cite-head .tag.product")).to_have_count(0)
    chips.nth(1).click()
    expect(panel).to_contain_text("Yes, with a hardware key for every account.")
    expect(panel).not_to_contain_text("for administrators")
    expect(panel.locator(".cite-head .tag.product")).to_have_text("Availo")


UNGROUNDED = "the reviewer did not find the answer grounded"


@pytest.fixture
def flagged_but_sure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scored well, flagged anyway: held by the gate on the flag alone."""

    async def answered(questions, language=None, run_id=None, **extra):
        return [
            AnsweredQuestion(question=q, answer=ANSWER, confidence=0.85, needs_review=True, review_reasons=[UNGROUNDED])
            for q in questions
        ]

    monkeypatch.setattr("src.tools.service.answer_questions", answered)


def answered_on_the_workbench(page: Page, tmp_path: Path) -> None:
    page.goto("/workbench")
    page.set_input_files("#assessmentInput", str(shapes.simple(tmp_path / "vendor.xlsx")))
    page.click("#extractBtn")
    page.click("#answerBtn")
    expect(page.locator("#results .answer")).to_have_count(4, timeout=15_000)


def test_withdrawing_an_approval_shows_the_answer_held_again(page: Page, tmp_path: Path, flagged_but_sure) -> None:
    """TD-053: the card said "held back again" while the server had released it."""
    answered_on_the_workbench(page, tmp_path)
    # Plan 029, 1.3: the review opens on "Needs review", which an approved
    # answer leaves; this test follows one card through, so it shows All.
    page.locator("#reviewTabs").get_by_role("button", name=re.compile("^All")).click()
    card = page.locator("#results .answer").first
    expect(card).to_contain_text("Not going into the file yet.")

    card.get_by_role("button", name="Approve", exact=True).click()
    expect(card.get_by_role("button", name="Approved ✓")).to_be_visible()
    expect(card).not_to_contain_text("Not going into the file yet.")

    card.get_by_role("button", name="Approved ✓").click()
    expect(page.locator("#answerStatus")).to_contain_text("It will be held back until somebody edits or approves it.")
    expect(card).to_contain_text("Not going into the file yet.")
    expect(card).to_contain_text(UNGROUNDED)
    expect(card.locator(".tag.warn", has_text="needs review")).to_have_count(1)


# --- Edit on a Brief card edits the brief (plan 029, 0.5) ------------------------

BRIEF = "Yes."


@pytest.fixture
def confident(monkeypatch: pytest.MonkeyPatch) -> None:
    async def answered(questions, language=None, run_id=None, **extra):
        return [AnsweredQuestion(question=q, answer=ANSWER, confidence=0.9, needs_review=False) for q in questions]

    monkeypatch.setattr("src.tools.service.answer_questions", answered)


def shortened_to(monkeypatch: pytest.MonkeyPatch, brief: str | None) -> None:
    """Stand in for the rewrite that derives a brief; None fails, so there is none."""

    async def shorten(answered):
        if brief is None:
            raise RuntimeError("the model is unavailable")
        return brief

    monkeypatch.setattr("src.rewrite.shorten", shorten)


def switched_to_brief(page: Page) -> None:
    page.locator("#detailPick").get_by_role("button", name="Brief").click()
    expect(page.locator("#answerStatus")).to_contain_text("Showing the brief answers")


def the_first_question() -> tuple[str, str]:
    [listed] = batches.recent(TEAM)
    loaded = batches.load(listed["id"])
    assert loaded is not None
    return loaded.id, loaded.form.questions[0].id


def test_editing_a_brief_card_edits_the_brief(page: Page, tmp_path: Path, monkeypatch, confident) -> None:
    """The editor opened on the full answer under a brief card, and saved it as the brief."""
    shortened_to(monkeypatch, BRIEF)
    answered_on_the_workbench(page, tmp_path)
    switched_to_brief(page)
    card = page.locator("#results .answer").first
    expect(card.locator(".rendered")).to_have_text(BRIEF)

    card.get_by_role("button", name="Edit", exact=True).click()
    editor = card.locator("textarea")
    expect(editor).to_have_value(BRIEF)
    editor.fill("Yes, quarterly.")
    with page.expect_request("**/answers") as sent:
        card.get_by_role("button", name="Done editing").click()

    batch_id, question_id = the_first_question()
    assert sent.value.post_data_json == {"question_id": question_id, "text": "Yes, quarterly.", "which": "brief"}
    expect(card.locator(".rendered")).to_have_text("Yes, quarterly.")
    expect(page.locator("#answerStatus")).to_contain_text("Your edit is saved")
    stored = batches.answers(batch_id)[question_id]
    assert (stored.answer, stored.brief) == (ANSWER, "Yes, quarterly.")


def test_a_brief_card_without_a_brief_edits_the_full_answer(page: Page, tmp_path: Path, monkeypatch, confident) -> None:
    """No brief could be derived, so the card shows the full answer, and that is what is edited."""
    shortened_to(monkeypatch, None)
    answered_on_the_workbench(page, tmp_path)
    switched_to_brief(page)
    card = page.locator("#results .answer").first
    expect(card.locator(".rendered")).to_have_text(ANSWER)

    card.get_by_role("button", name="Edit", exact=True).click()
    expect(card.locator("textarea")).to_have_value(ANSWER)
    card.locator("textarea").fill("Yes, approved and reviewed every year.")
    with page.expect_request("**/answers") as sent:
        card.get_by_role("button", name="Done editing").click()

    assert sent.value.post_data_json["which"] == "answer"
    expect(page.locator("#answerStatus")).to_contain_text("Your edit is saved")
    batch_id, question_id = the_first_question()
    stored = batches.answers(batch_id)[question_id]
    assert (stored.answer, stored.brief) == ("Yes, approved and reviewed every year.", "")


def test_emptying_a_brief_is_refused_on_the_card(page: Page, tmp_path: Path, monkeypatch, confident) -> None:
    """Saved, an empty brief released the model's full answer as a person's (TD-055)."""
    shortened_to(monkeypatch, BRIEF)
    answered_on_the_workbench(page, tmp_path)
    switched_to_brief(page)
    card = page.locator("#results .answer").first
    sent: list[str] = []
    page.on("request", lambda request: sent.append(request.url) if request.url.endswith("/answers") else None)

    card.get_by_role("button", name="Edit", exact=True).click()
    # Plan 029's review: said to a screen reader too. A live region, there
    # before it speaks, and the editor's description.
    note = card.locator(".edit-refused")
    expect(note).to_have_attribute("role", "status")
    expect(note).to_have_text("")
    note_id = note.get_attribute("id")
    assert note_id and card.locator("textarea").get_attribute("aria-describedby") == note_id
    card.locator("textarea").fill("")
    card.get_by_role("button", name="Done editing").click()

    expect(card.locator(".rendered")).to_have_text(BRIEF)
    expect(card).to_contain_text("A brief answer cannot be empty. To write nothing here, use Leave blank.")
    expect(card.get_by_role("status")).to_have_text(
        "A brief answer cannot be empty. To write nothing here, use Leave blank."
    )
    assert sent == []
    batch_id, question_id = the_first_question()
    assert batches.answers(batch_id)[question_id].brief == BRIEF
