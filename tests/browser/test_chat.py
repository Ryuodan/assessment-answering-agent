"""The assistant page (`/`) in a real browser: what the working bubble says during a turn (plan 016)."""

from __future__ import annotations

import asyncio
import itertools
import re
import time
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from src import identity, preferences, rewrite, service
from src.agents import assistant
from src.config import settings
from src.models import AnsweredQuestion
from tests import forms_fixtures as shapes
from tests.test_assistant import _graph

pytestmark = pytest.mark.browser


def watch_the_turn(page: Page, timeout: float = 30) -> list[str]:
    """Every distinct text of the working bubble, until the reply replaces it."""
    seen: list[str] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        working = page.locator(".working .bubble")
        if not working.count():
            if seen:
                return seen
        else:
            text = " ".join(working.first.inner_text().split())
            if not seen or seen[-1] != text:
                seen.append(text)
        page.wait_for_timeout(100)
    raise AssertionError(f"the turn did not finish in {timeout} s; the bubble said {seen}")


def test_the_count_does_not_start_again_when_the_answers_are_styled(
    page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Answering four questions, then rewording them to the person's preferences.
    The second pass used to read "Answered 0 of 4" again, so the count seemed to
    reset; it is the preferences being applied, and now says so."""
    answered, styled = itertools.count(1), itertools.count(1)

    async def answer_one(question, language, *, run_id="", team_id=None):
        await asyncio.sleep(0.6 * next(answered))  # spread out, so the page sees the count move
        return AnsweredQuestion(question=question, answer="Yes, it is documented.", confidence=0.9)

    async def reword(result, instruction, language=None, note=""):
        await asyncio.sleep(0.6 * next(styled))
        return result.model_copy(update={"answer": "Yes. It is documented."})

    monkeypatch.setattr(settings, "groq_api_key", "not-a-real-key")  # the model itself is scripted below
    monkeypatch.setattr(service, "answer_one_question", answer_one)
    monkeypatch.setattr(rewrite, "rewrite", reword)
    script = [("open_questionnaire", {"file_name": ""}), ("answer_questions", {})]
    monkeypatch.setattr(assistant, "_agent", lambda tools: _graph(script)(tools))
    preferences.save(identity.local_user().email, verdict_first=True)

    page.goto("/")
    page.set_input_files("#fileInput", str(shapes.status_and_comment(tmp_path / "HR.xlsx")))
    page.fill("#prompt", "Answer it")
    page.select_option("#productPick", "general")  # plan 029 (D-022): a new chat's first message waits for a choice
    page.click("#send")
    seen = watch_the_turn(page)

    styling = [i for i, text in enumerate(seen) if text.startswith("Applied your preferences to")]
    assert styling, f"the styling pass was never shown: {seen}"
    assert not any(text.startswith("Answered") for text in seen[styling[0] :]), seen
    counts = [int(m.group(1)) for text in seen if (m := re.match(r"Answered (\d+) of", text))]
    assert counts == sorted(counts), f"the answered count went backwards: {seen}"


def test_editing_a_brief_card_in_the_chat_edits_the_brief(
    page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same card as the Workbench's: under Brief, Edit opened on the full answer (plan 029, 0.5)."""

    async def answer_one(question, language, *, run_id="", team_id=None):
        return AnsweredQuestion(question=question, answer="Yes, it is documented and reviewed.", confidence=0.9)

    async def shorten(answered):
        return "Yes."

    monkeypatch.setattr(settings, "groq_api_key", "not-a-real-key")  # the model itself is scripted below
    monkeypatch.setattr(service, "answer_one_question", answer_one)
    monkeypatch.setattr(rewrite, "shorten", shorten)
    script = [("open_questionnaire", {"file_name": ""}), ("answer_questions", {})]
    monkeypatch.setattr(assistant, "_agent", lambda tools: _graph(script)(tools))

    page.goto("/")
    page.set_input_files("#fileInput", str(shapes.status_and_comment(tmp_path / "HR.xlsx")))
    page.fill("#prompt", "Answer it")
    page.select_option("#productPick", "general")  # plan 029 (D-022): a new chat's first message waits for a choice
    page.click("#send")
    pane = page.locator("#answersPane")
    expect(pane.locator(".answer")).to_have_count(4, timeout=30_000)
    expect(page.locator(".working")).to_have_count(0, timeout=30_000)  # the turn is over: nothing redraws the pane

    pane.locator(".detail-pick").get_by_role("button", name="Brief").click()
    card = pane.locator(".answer").first
    expect(card.locator(".rendered")).to_have_text("Yes.")
    card.get_by_role("button", name="Edit", exact=True).click()
    expect(card.locator("textarea")).to_have_value("Yes.")

    card.locator("textarea").fill("Yes, every year.")
    with page.expect_request("**/answers") as sent:
        card.get_by_role("button", name="Done editing").click()
    assert sent.value.post_data_json["which"] == "brief"
    assert sent.value.post_data_json["text"] == "Yes, every year."
    expect(pane.locator(".answer").first.locator(".rendered")).to_have_text("Yes, every year.")
