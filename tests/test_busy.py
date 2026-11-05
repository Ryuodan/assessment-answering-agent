"""One run at a time on a questionnaire (plan 029, 1.4).

`busy` is what keeps a second run, paid for twice, and an edit the run would
overwrite, off a questionnaire that is being answered. Another task is
simulated with a fresh context: what makes a hold "mine" is the task's
context, and a separate request or chat turn runs in its own.
"""

from __future__ import annotations

import asyncio
import contextvars

import pytest

from src import busy, progress
from src.errors import QuestionnaireBusy


def elsewhere(work):
    """Run `work` as another task would: in a context that holds nothing."""
    return contextvars.Context().run(work)


def test_a_second_hold_from_another_task_is_refused():
    with busy.hold("b1", "run-1"):
        with pytest.raises(QuestionnaireBusy) as refused:
            elsewhere(lambda: busy.hold("b1", "run-2").__enter__())

    assert refused.value.status == 409 and refused.value.code == "questionnaire_busy"
    assert "being answered right now" in str(refused.value)


def test_a_hold_nested_in_the_same_task_passes():
    """A run that shortens its own answers is not refused by itself."""
    with busy.hold("b1", "run-1"):
        with busy.hold("b1", "run-1"):
            busy.refuse("b1")
        busy.refuse("b1")  # still its own
        assert busy.state("b1")["run_id"] == "run-1"


def test_a_hold_is_let_go_when_the_run_fails():
    with pytest.raises(RuntimeError):
        with busy.hold("b1", "run-1"):
            raise RuntimeError("the pipeline fell over")

    assert busy.state("b1") is None
    elsewhere(lambda: busy.refuse("b1"))
    with busy.hold("b1", "run-2"):
        pass


def test_another_questionnaire_is_free():
    with busy.hold("b1", "run-1"):
        elsewhere(lambda: busy.refuse("b2"))
        assert busy.state("b2") is None


def test_refusing_from_another_task_names_how_far_the_run_has_got():
    progress.start("run-1", stage="answering")
    progress.set_total("run-1", 59)
    for _ in range(12):
        progress.advance("run-1")

    with busy.hold("b1", "run-1"):
        with pytest.raises(QuestionnaireBusy, match=r"right now \(12 of 59 done\)\. Wait until it finishes"):
            elsewhere(lambda: busy.refuse("b1"))


def test_state_carries_the_runs_progress():
    progress.start("run-1", stage="answering")
    progress.set_total("run-1", 4)
    progress.advance("run-1")

    with busy.hold("b1", "run-1"):
        now = busy.state("b1")

    assert now["run_id"] == "run-1" and now["started_at"]
    assert (now["stage"], now["total"], now["completed"], now["remaining"]) == ("answering", 4, 1, 3)
    assert busy.state("b1") is None


def test_state_without_progress_says_answering():
    with busy.hold("b1", "never-started"):
        now = busy.state("b1")
    assert (now["stage"], now["total"], now["completed"]) == ("answering", 0, 0)


async def test_two_tasks_cannot_both_hold_one_questionnaire():
    started, release = asyncio.Event(), asyncio.Event()

    async def first():
        with busy.hold("b1", "run-1"):
            started.set()
            await release.wait()

    async def second():
        await started.wait()
        try:
            with busy.hold("b1", "run-2"):
                return "held"
        except QuestionnaireBusy:
            return "refused"
        finally:
            release.set()

    _, said = await asyncio.gather(first(), second())

    assert said == "refused"
    assert busy.state("b1") is None
