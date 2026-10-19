"""LLM relevance grading of retrieved chunks.

The property under test is not "the grader is accurate" — that is measured in
eval/, not asserted here. It is that a *wrong* grader cannot break the system:
the answer must still be written when grading fails, the chunk carrying the
answer must survive a false negative, and a numbered series must not be torn in
half because the model disliked one of its parts.
"""

from __future__ import annotations

import pytest

from src import relevance
from src.config import settings
from src.models import Evidence, SourceType
from src.schemas import RelevanceVerdict, RelevanceVerdicts


def chunk(n: int, unit: str = "", name: str = "policy.pdf") -> Evidence:
    return Evidence(
        source_type=SourceType.GUIDELINE,
        source_name=name,
        snippet=f"content of chunk {n}",
        chunk=n,
        unit_id=unit or f"u{n}",
        score=0.7,
    )


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setattr(settings, "relevance_filter_enabled", True)
    monkeypatch.setattr(settings, "relevance_filter_keep", 2)
    monkeypatch.setattr(settings, "relevance_filter_batch", 12)


def grader(verdicts: dict[int, bool]):
    """Stand in for the model, returning the verdicts a test dictates."""

    async def fake(question, batch):
        return {index: verdicts.get(index, True) for index, _ in batch}

    return fake


@pytest.mark.asyncio
async def test_off_target_chunks_below_the_floor_are_dropped(monkeypatch):
    """Demoting instead was measured to do nothing: the evidence budget is
    rarely binding, so re-ordering a list nothing is cutting changes nothing."""
    monkeypatch.setattr(relevance, "_grade_batch", grader({2: False, 3: False}))
    evidence = [chunk(n) for n in range(6)]

    out = await relevance.filter_evidence("q", evidence)

    assert [c.chunk for c in out] == [0, 1, 4, 5]


@pytest.mark.asyncio
async def test_the_top_chunks_survive_a_false_negative(monkeypatch):
    """The grader is one more thing that can be wrong, and a false negative on
    the only chunk carrying the answer leaves nothing to recover from."""
    monkeypatch.setattr(relevance, "_grade_batch", grader(dict.fromkeys(range(6), False)))
    evidence = [chunk(n) for n in range(6)]

    out = await relevance.filter_evidence("q", evidence)

    assert [c.chunk for c in out] == [0, 1], "the keep floor is absolute"


@pytest.mark.asyncio
async def test_a_grading_failure_leaves_the_evidence_alone(monkeypatch):
    async def explode(question, batch):
        raise RuntimeError("the model went away")

    monkeypatch.setattr(relevance, "_grade_batch", explode)
    evidence = [chunk(n) for n in range(6)]

    assert await relevance.filter_evidence("q", evidence) == evidence


@pytest.mark.asyncio
async def test_a_series_is_judged_as_one_unit(monkeypatch):
    """One relevant part vouches for the whole unit, so the drafter never sees
    three items of nine and calls it the list."""
    monkeypatch.setattr(relevance, "_grade_batch", grader({3: True, 4: False, 5: False}))
    evidence = [chunk(n) for n in range(3)] + [chunk(n, unit="series") for n in (3, 4, 5)]

    out = await relevance.filter_evidence("q", evidence)

    assert [c.chunk for c in out] == [0, 1, 2, 3, 4, 5], "the series stays together"


@pytest.mark.asyncio
async def test_a_relevant_remembered_answer_does_not_keep_an_irrelevant_one(monkeypatch):
    """Plan 027: every remembered answer is "Answer memory", chunk 0, and judged as
    one unit they all stood or fell with whichever the grader liked."""

    def remembered(entry_id: str) -> Evidence:
        return Evidence(
            source_type=SourceType.PRIOR_ANSWER,
            source_name="Answer memory",
            snippet=entry_id,
            chunk=0,
            entry_id=entry_id,
        )

    monkeypatch.setattr(relevance, "_grade_batch", grader({2: True, 3: False}))
    evidence = [chunk(0), chunk(1), remembered("mem-on-topic"), remembered("mem-off-topic")]

    out = await relevance.filter_evidence("q", evidence)

    assert [c.entry_id for c in out] == ["", "", "mem-on-topic"]


@pytest.mark.asyncio
async def test_an_omitted_verdict_is_not_read_as_a_rejection(monkeypatch):
    async def partial(question, batch):
        return {batch[0][0]: True}  # the model answered about one only

    monkeypatch.setattr(relevance, "_grade_batch", partial)
    evidence = [chunk(n) for n in range(6)]

    assert await relevance.filter_evidence("q", evidence) == evidence


@pytest.mark.asyncio
async def test_the_filter_is_inert_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "relevance_filter_enabled", False)

    async def explode(question, batch):
        raise AssertionError("must not grade when disabled")

    monkeypatch.setattr(relevance, "_grade_batch", explode)
    evidence = [chunk(n) for n in range(6)]

    assert await relevance.filter_evidence("q", evidence) == evidence


@pytest.mark.asyncio
async def test_a_short_evidence_list_is_not_worth_a_call(monkeypatch):
    async def explode(question, batch):
        raise AssertionError("must not grade below the keep floor")

    monkeypatch.setattr(relevance, "_grade_batch", explode)
    evidence = [chunk(n) for n in range(2)]

    assert await relevance.filter_evidence("q", evidence) == evidence


def test_batches_cover_every_chunk_exactly_once():
    evidence = [chunk(n) for n in range(29)]
    batches = relevance._batches(evidence, 12)

    assert [len(b) for b in batches] == [12, 12, 5]
    assert [index for batch in batches for index, _ in batch] == list(range(29))


def test_an_excerpt_carries_its_locator_and_is_bounded():
    item = chunk(1)
    item.clause_start = "3.1.1"
    text = relevance._excerpt(7, item, limit=10)

    assert text.startswith("[7] ")
    assert "3.1.1" in text, "the grader should see what it is judging"
    assert len(text.splitlines()[1]) <= 10


def test_the_schema_round_trips_a_batch_verdict():
    parsed = RelevanceVerdicts(verdicts=[RelevanceVerdict(id=3, relevant=False)])
    assert parsed.verdicts[0].id == 3 and parsed.verdicts[0].relevant is False


@pytest.mark.asyncio
async def test_a_relevant_chunk_is_promoted_past_the_protected_floor(monkeypatch):
    """The floor protects chunks from deletion, not from being overtaken.

    Without promotion the grader could only delete from the back of the prompt
    -- and the drafter cites about eight sources however many it is shown, so
    the back is the one region where a change cannot reach the answer.
    """
    monkeypatch.setattr(relevance, "_grade_batch", grader({0: False, 1: False, 4: True}))
    evidence = [chunk(n) for n in range(6)]

    out = await relevance.filter_evidence("q", evidence)

    assert out[0].chunk == 2, "relevant material leads"
    assert {c.chunk for c in out[-2:]} == {0, 1}, "protected but off-target falls behind"
    assert {c.chunk for c in out} == {0, 1, 2, 3, 4, 5}, "the floor still forbids deletion"


@pytest.mark.asyncio
async def test_promotion_keeps_a_series_together(monkeypatch):
    monkeypatch.setattr(relevance, "_grade_batch", grader({0: False, 1: False}))
    evidence = [chunk(n) for n in range(2)] + [chunk(n, unit="series") for n in (2, 3, 4)]

    out = await relevance.filter_evidence("q", evidence)

    order = [c.chunk for c in out]
    assert order[:3] == [2, 3, 4], "the series is promoted whole and in order"


@pytest.mark.asyncio
async def test_promotion_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(settings, "relevance_filter_promote", False)
    monkeypatch.setattr(relevance, "_grade_batch", grader({0: False, 1: False, 4: True}))
    evidence = [chunk(n) for n in range(6)]

    out = await relevance.filter_evidence("q", evidence)

    assert [c.chunk for c in out] == [0, 1, 2, 3, 4, 5], "retrieval order preserved"
