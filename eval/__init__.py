"""Offline evaluation against the golden question set."""


def plan_afresh() -> None:
    """For an evaluation run: no kept search plans, read or written (plan 034's review).

    An evaluation measures planning as it is now, and writes nothing to the
    database it reads. A kept plan from an earlier run would hide a planner
    change, and it would keep the house set's question wording in `search_plans`.
    Each runner calls it as it starts; importing this package changes nothing.
    """
    from src.config import settings

    settings.reuse_search_plans = False
