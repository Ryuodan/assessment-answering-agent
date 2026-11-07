"""The searches `nodes.plan` uses again for a question it planned before (plan 034, `search_plans`).

The planner words a plan differently on each run, even at temperature 0, and the
sources an answer is drafted from follow the searches. So the first plan that
worked is kept per team, product and language, and the same question is
searched the same way the next time. Off with `REUSE_SEARCH_PLANS=false`, or with
query expansion off, when there is no plan to keep.
"""

from __future__ import annotations

from src import search_plans
from src.config import settings
from src.graph.state import QuestionState


def _where(state: QuestionState) -> tuple[str, str, str]:
    return state.get("team_id") or settings.default_team, state.get("product_id", ""), state.get("language", "en")


def _on() -> bool:
    return settings.query_expansion and settings.reuse_search_plans


def recall(state: QuestionState) -> list[str] | None:
    """The searches kept for this question, or None to plan them."""
    return search_plans.recall(*_where(state), state["question"].text) if _on() else None


def keep(state: QuestionState, queries: list[str]) -> None:
    """Keep a plan that worked. A failed or empty one is never kept, so it is planned again."""
    if _on():
        search_plans.keep(*_where(state), state["question"].text, queries)
