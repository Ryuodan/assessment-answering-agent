"""Rewording a finished answer.

`rewrite` exists because the alternative -- running the answering pipeline
again with a wording instruction attached -- was measured and lost. Injection
followed the instruction just as well, but retrieval and review ran a second
time, so an answer could come back saying something different, and the drafter
told to be brief cited about a third fewer sources. These tests hold the two
properties that made rewriting the better trade: the facts and the citations
survive, and a failed rewrite costs the wording rather than the answer.
"""

from __future__ import annotations

import pytest

from src import rewrite
from src.models import AnsweredQuestion, Evidence, Question, SourceType
from src.prompts import REWRITE_SYSTEM


def _evidence(n: int) -> list[Evidence]:
    return [
        Evidence(
            source_type=SourceType.GUIDELINE,
            source_name=f"policy-{index}.pdf",
            snippet=f"clause {index}",
            score=1.0 - index / 100,
            clause=f"{index}.1",
        )
        for index in range(n)
    ]


def _answered(answer: str = "Yes. Access is reviewed quarterly.", n: int = 3) -> AnsweredQuestion:
    return AnsweredQuestion(
        question=Question(id="q1", text="Are access rights reviewed?", language="en"),
        answer=answer,
        rationale="The policy states a quarterly review.",
        confidence=0.9,
        needs_review=False,
        evidence=_evidence(n),
        citations=["policy-0.pdf §0.1", "policy-1.pdf §1.1"],
    )


class Reply:
    def __init__(self, content: str) -> None:
        self.content = content


class Model:
    """Stands in for the chat model, and records what it was asked."""

    def __init__(self, content: str = "Reworded.", fail: bool = False) -> None:
        self.content = content
        self.fail = fail
        self.messages: list[tuple[str, str]] = []

    async def ainvoke(self, messages):
        self.messages = messages
        if self.fail:
            raise RuntimeError("the model is down")
        return Reply(self.content)


@pytest.fixture
def model(monkeypatch):
    stand_in = Model()
    monkeypatch.setattr(rewrite, "chat_llm", lambda **_: stand_in)
    return stand_in


# --- what a rewrite must preserve ------------------------------------------


@pytest.mark.asyncio
async def test_the_citations_come_through_untouched(model):
    """The sources did not change, so the clause a reader would go and check
    has not moved either. Re-answering could not promise this."""
    original = _answered()
    revised = await rewrite.rewrite(original, "Make it shorter.")

    assert revised.answer == "Reworded."
    assert revised.citations == original.citations
    assert [item.snippet for item in revised.evidence] == [i.snippet for i in original.evidence]


@pytest.mark.asyncio
async def test_the_original_is_not_mutated(model):
    """A caller holding the answer it passed in should still be holding it --
    `revise` writes the copy back to the batch itself."""
    original = _answered()
    await rewrite.rewrite(original, "Make it shorter.")
    assert original.answer == "Yes. Access is reviewed quarterly."


@pytest.mark.asyncio
async def test_the_rationale_records_that_it_was_reworded(model):
    revised = await rewrite.rewrite(_answered(), "Make it shorter.")
    assert "Reworded on request: Make it shorter." in revised.rationale
    assert "The policy states a quarterly review." in revised.rationale


@pytest.mark.asyncio
async def test_a_note_replaces_the_instruction_in_the_rationale(model):
    """A two-paragraph house style pasted under every answer is noise; the
    note says what happened in a sentence."""
    revised = await rewrite.rewrite(
        _answered(), "Open with Yes or No.\nNo clause numbers.", note="Reworded to your house style.",
    )
    assert revised.rationale.endswith("Reworded to your house style.")
    assert "No clause numbers" not in revised.rationale


@pytest.mark.asyncio
async def test_a_reworded_answer_is_the_models_words_whoever_wrote_the_original(model):
    """What keeps model text out of the answer memory. A person's answer run
    through a rewording is no longer theirs, whichever caller asked for it."""
    original = _answered()
    original.by_hand = True

    revised = await rewrite.rewrite(original, "More formal.")

    assert revised.by_hand is False
    assert original.by_hand is True, "and the one passed in is left alone"


@pytest.mark.asyncio
async def test_the_instruction_must_keep_the_answers_position():
    """A questionnaire's compliance dropdown is filled by reading the opening
    clause of the answer -- see `forms.status`. Rewording once turned "Yes. We
    provide training..." into "T2 provides training...", which states no
    position, so the status column came out blank on a sheet that had a
    perfectly good answer beside it.
    """
    assert "Keep the position" in REWRITE_SYSTEM
    for word in ("yes", "no", "partly", "does not apply"):
        assert word in REWRITE_SYSTEM


# --- what a rewrite must not do --------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_rewrite_returns_the_answer_unchanged(monkeypatch):
    """Half a rewrite is worse than none: the answer had passed review."""
    monkeypatch.setattr(rewrite, "chat_llm", lambda **_: Model(fail=True))
    original = _answered()
    assert await rewrite.rewrite(original, "Make it shorter.") is original


@pytest.mark.asyncio
async def test_an_empty_reply_returns_the_answer_unchanged(monkeypatch):
    monkeypatch.setattr(rewrite, "chat_llm", lambda **_: Model(content="   "))
    original = _answered()
    assert await rewrite.rewrite(original, "Make it shorter.") is original


@pytest.mark.asyncio
async def test_a_question_with_no_answer_is_left_alone(model):
    """Rewording a blank is answering it, which is a different operation."""
    blank = _answered(answer="")
    assert await rewrite.rewrite(blank, "Make it shorter.") is blank
    assert model.messages == [], "the model should not have been called at all"


# --- what the model is shown -----------------------------------------------


@pytest.mark.asyncio
async def test_the_sources_are_passed_so_the_instruction_cannot_invent(model):
    await rewrite.rewrite(_answered(n=3), "Add a sentence about encryption.")
    prompt = model.messages[1][1]
    assert "clause 0" in prompt and "clause 2" in prompt
    assert "Add a sentence about encryption." in prompt
    assert "Yes. Access is reviewed quarterly." in prompt


@pytest.mark.asyncio
async def test_only_a_promptful_of_sources_is_shown(model):
    """The drafter cites about this many; the rest is context the rewrite has
    no use for and would pay for on every question."""
    await rewrite.rewrite(_answered(n=30), "Shorter.")
    prompt = model.messages[1][1]
    assert prompt.count("clause ") == rewrite.MAX_SOURCES


@pytest.mark.asyncio
async def test_an_answer_with_no_evidence_still_rewrites(model):
    """Some answers are written from nothing found. Rewording still works, and
    says so rather than leaving a hole where the sources go."""
    revised = await rewrite.rewrite(_answered(n=0), "Shorter.")
    assert revised.answer == "Reworded."
    assert "(none recorded)" in model.messages[1][1]


@pytest.mark.asyncio
async def test_the_answer_stays_in_its_own_language_by_default(model):
    answered = _answered()
    answered.question.language = "ar"
    await rewrite.rewrite(answered, "اجعلها أقصر")
    assert "Arabic" in model.messages[0][1]


@pytest.mark.asyncio
async def test_a_requested_language_wins(model):
    answered = _answered()
    answered.question.language = "ar"
    await rewrite.rewrite(answered, "Shorter.", language="en")
    assert "English" in model.messages[0][1]


@pytest.mark.asyncio
async def test_every_language_has_a_name_to_put_in_the_prompt(model):
    """A missing name would be a KeyError at the point of rewriting, which is
    after the answer has already been paid for."""
    for language in ("en", "ar"):
        await rewrite.rewrite(_answered(), "Shorter.", language=language)
        assert "{language_name}" not in model.messages[0][1]
