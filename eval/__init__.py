"""Offline evaluation against the golden question set."""

from src.config import settings

# An evaluation measures planning as it is now, and writes nothing to the database it reads:
# no kept search plans (plan 034's review). A kept plan from an earlier run would hide a
# planner change, and it would keep the house set's question wording in `search_plans`.
settings.reuse_search_plans = False
