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

from pydantic import TypeAdapter

from src import store
from src.formatting import wording_key

_QUERIES = TypeAdapter(list[str])
"""A kept plan, as `keep` wrote it: a list of search strings."""


def recall(team_id: str, product_id: str, language: str, question: str) -> list[str] | None:
    """The searches kept for this question, or None. Using one counts as using it."""
    key = wording_key(question)
    if not key:
        return None
    conn = store.connect()
    where = "team_id = ? AND product_id = ? AND language = ? AND wording = ?"
    found = conn.execute(f"SELECT queries FROM search_plans WHERE {where}", (team_id, product_id, language, key))
    row = found.fetchone()
    if row is None:
        return None
    conn.execute(
        f"UPDATE search_plans SET used_at = ? WHERE {where}", (store.utcnow(), team_id, product_id, language, key)
    )
    conn.commit()
    return _QUERIES.validate_json(row["queries"]) or None


def keep(team_id: str, product_id: str, language: str, question: str, queries: list[str]) -> None:
    """Keep the searches a question was planned into, replacing any kept before."""
    key = wording_key(question)
    if not key or not queries:
        return
    now = store.utcnow()
    conn = store.connect()
    conn.execute(
        "INSERT OR REPLACE INTO search_plans (team_id, product_id, language, wording, queries, created_at, used_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (team_id, product_id, language, key, json.dumps(queries, ensure_ascii=False), now, now),
    )
    conn.commit()


def forget_unused(cutoff: str) -> int:
    """Delete the plans not used since `cutoff` (an ISO time); how many went."""
    conn = store.connect()
    gone = conn.execute("DELETE FROM search_plans WHERE used_at < ?", (cutoff,)).rowcount
    conn.commit()
    return gone
