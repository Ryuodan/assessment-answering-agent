"""The memory page's selector, and moving an answer between memories, in a real browser (plan 022)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from src import answer_memory, knowledge, products
from src.config import settings
from tests.conftest import FakeVectorStore, bare_store

pytestmark = pytest.mark.browser

TEAM = settings.default_team


@pytest.fixture
def stores(monkeypatch):
    made: dict[tuple[str, str], knowledge.KnowledgeStore] = {}

    def get_store(team_id=None, *, product_id=""):
        key = (team_id or TEAM, product_id)
        if key not in made:
            made[key] = bare_store(FakeVectorStore([]))
        return made[key]

    monkeypatch.setattr("src.knowledge.get_store", get_store)
    return made


def test_the_page_shows_one_memory_and_moves_an_answer_to_another(page: Page, stores) -> None:
    availo = products.add(None, TEAM, "Availo")
    answer_memory.record("Do you encrypt backups?", "Shared: yes, with AES-256.", scanned=True)
    answer_memory.record("Do you encrypt backups?", "Availo: yes, per tenant.", product_id=availo.id, scanned=True)

    page.goto("/memory")
    entries = page.locator("#entries")
    expect(entries).to_contain_text("Shared: yes, with AES-256.")
    expect(entries).not_to_contain_text("Availo: yes, per tenant.")

    page.select_option("#memoryScope", availo.id)
    expect(page.locator("#memoryScopeHint")).to_contain_text("Used only for Availo's questionnaires")
    expect(entries).to_contain_text("Availo: yes, per tenant.")
    expect(entries).not_to_contain_text("Shared: yes, with AES-256.")

    entries.locator(".entry", has_text="Availo: yes").locator("select.move").select_option("shared")
    expect(entries).not_to_contain_text("Availo: yes, per tenant.")

    page.select_option("#memoryScope", "")
    expect(entries).to_contain_text("Availo: yes, per tenant.")
    expect(entries).to_contain_text("Shared: yes, with AES-256.")
    assert {e.product_id for e in answer_memory.entries()} == {""}


def test_move_to_sits_with_edit_and_forget(page: Page, stores) -> None:
    """TD-041: the menu took the card's whole width and pushed Forget onto a row of its own."""
    products.add(None, TEAM, "Availo")
    answer_memory.record(
        "Do you encrypt backups?",
        "Yes, with AES-256.",
        from_file="E2E vendor questionnaire.xlsx",
        origin="approved",
        approved_by="lead@example.test",
        approved_on="2026-10-19",
        scanned=True,
    )

    for width in (1280, 900):
        page.set_viewport_size({"width": width, "height": 800})
        page.goto("/memory")
        entry = page.locator("#entries .entry").first
        edit = entry.get_by_role("button", name="Edit", exact=True)
        move = entry.locator("select.move")
        forget = entry.get_by_role("button", name="Forget", exact=True)
        expect(move).to_be_visible()

        card = entry.bounding_box()
        boxes = [edit.bounding_box(), move.bounding_box(), forget.bounding_box()]
        assert card and all(boxes), f"at {width}px: {card}, {boxes}"
        assert boxes[1]["width"] <= 240, f"at {width}px the menu is {boxes[1]['width']}px wide"
        middles = [box["y"] + box["height"] / 2 for box in boxes]
        assert max(middles) - min(middles) <= 6, f"at {width}px Edit, Move and Forget are not on one row: {boxes}"
        assert all(box["x"] + box["width"] <= card["x"] + card["width"] for box in boxes), (
            f"at {width}px a control sticks out of its card: {boxes}, {card}"
        )
