"""What a watched run reports while it rewords, styles or shortens (plan 016).

The chat page and the workbench label a counted stage by its name: "Answered",
"Reworded", "Applied your preferences to", "Shortened". `set_total` used to set
every counted run's stage to "answering", so the pass that follows answering
read "Answered 0 of 12" and the bar seemed to start again.
"""

from __future__ import annotations

import pytest

from src import batches, identity, progress, rewrite, tools
from src.models import AnsweredQuestion
from tests import forms_fixtures as shapes


@pytest.mark.parametrize("stage", ["rewriting", "styling", "shortening"])
def test_a_counted_pass_keeps_its_own_name(stage: str) -> None:
    progress.start("pass", stage=stage)
    progress.set_total("pass", 12)
    progress.advance("pass")
    state = progress.snapshot("pass")
    assert (state["stage"], state["completed"], state["total"]) == (stage, 1, 12)


@pytest.mark.parametrize("stage", ["extracting", "Thinking…"])
def test_a_stage_with_no_count_becomes_answering_once_there_is_one(stage: str) -> None:
    progress.start("run", stage=stage)
    progress.set_total("run", 3)
    assert progress.snapshot("run")["stage"] == "answering"


@pytest.mark.asyncio
async def test_shortening_after_answering_is_reported_under_the_turns_own_id(tmp_path, monkeypatch) -> None:
    """A brief questionnaire is shortened right after it is answered. That pass
    reported under the batch's id, so a chat turn watched under its own id sat
    at "Answered 4 of 4" until the reply arrived."""
    user = identity.local_user()
    batch = tools.open_form(user, shapes.simple(tmp_path / "vendor.xlsx"))
    batches.set_detail(batch.id, "brief")

    async def answered(questions, language=None, run_id=None, **extra):
        return [AnsweredQuestion(question=q, answer="Yes, it is documented.", confidence=0.9) for q in questions]

    seen: list[str] = []

    async def shorten(answer):
        seen.append(progress.snapshot("turn")["stage"])
        return "Yes."

    monkeypatch.setattr(tools.service, "answer_questions", answered)
    monkeypatch.setattr(rewrite, "shorten", shorten)

    await tools.answer(user, batch.id, tools.Scope(), run_id="turn")

    assert seen and set(seen) == {"shortening"}
    assert progress.snapshot("turn")["stage"] == "done"
