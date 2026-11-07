"""The searches a question was answered with, kept so that it is searched the same way again (plan 034).

Every answer starts by asking a model to turn the question into searches
(`graph.nodes.plan`, through `graph.kept_searches`), and the model words them differently each time, even at
temperature 0. Measured on one question, no two of three runs searched alike,
so they found different clauses and one run was held for review on a
regulator's guide instead of our own policy. Keeping the first plan that worked
means the same question finds the same sources, and only the knowledge base
changing changes what they return.

A plan is kept per team, product and language, under the question's wording
(`formatting.wording_key`): the same words, case, punctuation and the digits'
script aside. A plan that failed is never kept, so it is planned again next
time. It holds the question's words, so it goes when it has not been used for
`RETENTION_DAYS`, like the work it came from (`retention`).
"""

from __future__ import annotations

import json

import hashlib

from pydantic import TypeAdapter

from src import store
from src.config import settings
from src.formatting import asks_on_its_own, wording_key
from src.prompts import QUERY_PLAN_SYSTEM

_QUERIES = TypeAdapter(list[str])
"""A kept plan, as `keep` wrote it: a list of search strings."""


def key(question: str, section: str = "") -> str:
    """What a plan is kept under: the planner that wrote it, the question's section and its words (plan 034's review).

    The planner is its prompt and its model, so a plan written by an older one is
    planned again rather than kept for good. The section is in it because the
    planner is shown the section. A question that does not ask on its own words
    is never kept ("" means: plan it every time).
    """
    if not asks_on_its_own(question):
        return ""
    planner = hashlib.sha1(f"{settings.groq_chat_model}\n{QUERY_PLAN_SYSTEM}".encode()).hexdigest()[:10]
    return f"{planner}|{wording_key(section)}|{wording_key(question)}"


def recall(team_id: str, product_id: str, language: str, question: str, section: str = "") -> list[str] | None:
    """The searches kept for this question, or None. Using one counts as using it."""
    key_ = key(question, section)
    if not key_:
        return None
    conn = store.connect()
    where = "team_id = ? AND product_id = ? AND language = ? AND wording = ?"
    found = conn.execute(f"SELECT queries FROM search_plans WHERE {where}", (team_id, product_id, language, key_))
    row = found.fetchone()
    if row is None:
        return None
    conn.execute(
        f"UPDATE search_plans SET used_at = ? WHERE {where}", (store.utcnow(), team_id, product_id, language, key_)
    )
    conn.commit()
    return _QUERIES.validate_json(row["queries"]) or None


def keep(team_id: str, product_id: str, language: str, question: str, queries: list[str], section: str = "") -> None:
    """Keep the searches a question was planned into, replacing any kept before."""
    key_ = key(question, section)
    if not key_ or not queries:
        return
    now = store.utcnow()
    conn = store.connect()
    conn.execute(
        "INSERT OR REPLACE INTO search_plans (team_id, product_id, language, wording, queries, created_at, used_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (team_id, product_id, language, key_, json.dumps(queries, ensure_ascii=False), now, now),
    )
    conn.commit()


def forget(team_id: str, product_id: str, questions: list[tuple[str, str]]) -> int:
    """Delete the plans kept for these (question, section) pairs, in every language: a questionnaire deleted."""
    keys = [found for question, section in questions if (found := key(question, section))]
    if not keys:
        return 0
    conn = store.connect()
    marks = ", ".join("?" for _ in keys)
    gone = conn.execute(
        f"DELETE FROM search_plans WHERE team_id = ? AND product_id = ? AND wording IN ({marks})",
        (team_id, product_id, *keys),
    ).rowcount
    conn.commit()
    return gone


def forget_unused(cutoff: str) -> int:
    """Delete the plans not used since `cutoff` (an ISO time); how many went."""
    conn = store.connect()
    gone = conn.execute("DELETE FROM search_plans WHERE used_at < ?", (cutoff,)).rowcount
    conn.commit()
    return gone
