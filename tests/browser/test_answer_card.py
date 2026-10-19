"""The sources an answer card cites, in a real browser (plan 027).

Remembered answers approved on one day share one citation, "Answer memory
(2026-10-01)", and since plan 027 more than one of them reaches the drafter.
Each one cited is its own chip, and each chip opens its own answer. Found by
the citation alone, every such chip opened the first, so a product's own
answer cited after a shared one could not be read on the card.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from src import identity, knowledge, products
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
