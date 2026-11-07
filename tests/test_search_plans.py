"""The same question is searched the same way again (plan 034, `search_plans`).

Measured before: no two of three runs of one question searched alike, so they
found different clauses, and one run was held for review on a regulator's guide
instead of our own policy.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src import search_plans, store
from src.config import settings
from src.graph import nodes
from src.models import Question

TEAM = settings.default_team
ASKED = "Do you have a documented incident response plan?"


def _state(text: str = ASKED, **overrides) -> dict:
    base = {
        "question": Question(id="1", text=text, language="en"),
        "language": "en",
        "team_id": TEAM,
        "product_id": "",
        "search_queries": [text],
        "attempt": 0,
        "evidence": [],
    }
    return {**base, **overrides}


class Planner:
    """The model that plans searches: says a different plan each time it is asked, as it does."""

    def __init__(self) -> None:
        self.asked = 0
        self.fail = False

    def __call__(self, *args, **kwargs):
        planner = self

        class Runnable:
            async def ainvoke(self, _messages):
                planner.asked += 1
                if planner.fail:
                    raise RuntimeError("the provider is down")

                class Response:
                    content = f"incident response plan documented\nincident plan testing round {planner.asked}"

                return Response()

        return Runnable()


@pytest.fixture
def planner(monkeypatch) -> Planner:
    model = Planner()
    monkeypatch.setattr(settings, "query_expansion", True)
    monkeypatch.setattr(settings, "reuse_search_plans", True)
    monkeypatch.setattr(nodes, "chat_llm", model)
    return model


@pytest.mark.asyncio
async def test_a_question_planned_once_is_searched_the_same_way_again(planner) -> None:
    first = (await nodes.plan(_state()))["search_queries"]
    again = (await nodes.plan(_state("do you have a documented incident-response plan")))["search_queries"]

    assert planner.asked == 1, "the second run used the kept plan"
    assert again == first == [ASKED, "incident response plan documented", "incident plan testing round 1"]


@pytest.mark.asyncio
async def test_a_plan_is_kept_per_product_and_language(planner) -> None:
    await nodes.plan(_state())
    await nodes.plan(_state(product_id="p-availo"))
    await nodes.plan(_state(language="ar"))
    assert planner.asked == 3, "a product's questionnaire, or another language, is planned for itself"


@pytest.mark.asyncio
async def test_a_failed_plan_is_planned_again_next_time(planner) -> None:
    planner.fail = True
    assert (await nodes.plan(_state()))["search_queries"] == [ASKED], "the question alone, as before"
    planner.fail = False
    planned = (await nodes.plan(_state()))["search_queries"]
    assert planner.asked == 2 and len(planned) == 3, "nothing was kept from the failure"


@pytest.mark.asyncio
async def test_switched_off_it_plans_every_time(planner, monkeypatch) -> None:
    monkeypatch.setattr(settings, "reuse_search_plans", False)
    await nodes.plan(_state())
    await nodes.plan(_state())
    assert planner.asked == 2
    assert search_plans.recall(TEAM, "", "en", ASKED) is None, "and keeps nothing"


def test_a_kept_plan_is_found_by_the_same_words_only() -> None:
    search_plans.keep(TEAM, "", "en", ASKED, [ASKED, "incident response"])
    assert search_plans.recall(TEAM, "", "en", ASKED.upper().rstrip("?")) == [ASKED, "incident response"]
    assert search_plans.recall(TEAM, "", "en", "Do you have a documented business continuity plan?") is None
    assert search_plans.recall("another-team", "", "en", ASKED) is None


def test_unused_plans_go_with_the_work_they_came_from(monkeypatch) -> None:
    """They hold the question's words, so they go after RETENTION_DAYS unused, as the work does."""
    from src import retention

    monkeypatch.setattr(settings, "retention_days", 180)
    search_plans.keep(TEAM, "", "en", ASKED, [ASKED])
    search_plans.keep(TEAM, "", "en", "Is data encrypted at rest?", ["Is data encrypted at rest?"])
    old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat(timespec="seconds")
    conn = store.connect()
    conn.execute("UPDATE search_plans SET used_at = ? WHERE wording LIKE 'do you%'", (old,))
    conn.commit()

    retention.sweep()

    assert search_plans.recall(TEAM, "", "en", ASKED) is None
    assert search_plans.recall(TEAM, "", "en", "Is data encrypted at rest?") == ["Is data encrypted at rest?"]
