"""Looking something up in a team's knowledge base, without touching a questionnaire.

Moved from `src/service.py` (plan 023), which re-exports `search_knowledge`, so
the interface and the tools call it where they always have.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src import knowledge
from src.lexical import reciprocal_rank_fusion
from src.logs import get_logger
from src.models import Evidence, SourceType

logger = get_logger(__name__)


# A person waiting at a search box will not wait a minute for a remote
# embedding host that is not answering. The literal search needs no network.
SEARCH_EMBED_TIMEOUT = 10.0


async def search_knowledge(
    query: str,
    *,
    mode: str = "hybrid",
    limit: int = 20,
    source_name: str = "",
    team_id: str | None = None,
    product_id: str = "",
) -> dict[str, Any]:
    """Search a team's indexed corpus directly, for a person rather than the drafter.

    Two ways of matching, because they fail in opposite ways and someone
    verifying a claim needs to choose. `semantic` finds material that means the
    same thing in either language; `keyword` matches the literal text, which is
    what you want when checking whether a policy really says "90 days", and
    understands `"quoted phrases"` and `-exclusions`. `hybrid` fuses both by
    reciprocal rank.

    Units are deliberately not expanded here. The answering path completes a
    split series so the drafter never mistakes a fragment for the whole list; a
    search result should be the chunk that actually matched.

    With a `product_id`, the product's knowledge base is searched as well as
    the shared one, and its hits come first and carry its id (plan 023).
    """
    query = (query or "").strip()
    if not query:
        return {"query": "", "mode": mode, "results": [], "documents": []}

    shared = knowledge.get_store(team_id)
    stores = [(knowledge.get_store(team_id, product_id=product_id), product_id)] if product_id else []
    stores.append((shared, ""))
    limit = max(1, min(limit, 50))
    # An empty collection still costs an embedding round trip to search, and
    # the prior-answers one is usually empty.
    counts = await asyncio.gather(*(asyncio.to_thread(store.counts_by_type) for store, _ in stores))
    degraded: list[str] = []

    async def for_type(
        store: knowledge.KnowledgeStore, count: dict[str, int], source_type: SourceType
    ) -> list[Evidence]:
        if not count.get(source_type.value):
            return []

        dense: list[Evidence] = []
        literal: list[Evidence] = []
        if mode in ("semantic", "hybrid"):
            try:
                dense = await asyncio.wait_for(
                    store.search(query, source_type, limit, expand=False), SEARCH_EMBED_TIMEOUT
                )
            except Exception as error:  # noqa: BLE001 - search degrades to keyword results, it does not fail
                # The embedding service is remote and occasionally slow to
                # answer; a person at a search box should get the literal
                # matches rather than a spinner or a stack trace.
                degraded.append(str(error) or repr(error))
                logger.warning("search.semantic_unavailable", error=str(error) or repr(error))
        if mode in ("keyword", "hybrid"):
            literal = await asyncio.to_thread(store.text_search, query, source_type, limit)
        if not dense and degraded and mode == "semantic":
            # Nothing to show otherwise: answer the query the one way still working.
            literal = await asyncio.to_thread(store.text_search, query, source_type, limit)
        if mode != "hybrid":
            return dense or literal

        # Fused on rank, not score: a text-match count and a cosine are not
        # comparable numbers, and averaging them would silently favour
        # whichever happens to use the wider range.
        by_key: dict[tuple[str, int], Evidence] = {}
        for item in dense + literal:
            by_key.setdefault((item.source_name, item.chunk), item)
        rankings = [
            [(item.source_name, item.chunk) for item in dense],
            [(item.source_name, item.chunk) for item in literal],
        ]
        return [by_key[key] for key in reciprocal_rank_fusion(rankings) if key in by_key]

    # Both collections at once: they are independent queries and running them
    # in sequence doubled the wait for no reason.
    jobs = [
        (store, count, owner, source_type)
        for source_type in (SourceType.GUIDELINE, SourceType.PRIOR_ANSWER)
        for (store, owner), count in zip(stores, counts)
    ]
    batches = await asyncio.gather(*(for_type(store, count, kind) for store, count, _, kind in jobs))
    for (_, _, owner, _), batch in zip(jobs, batches):
        for item in batch:
            item.product_id = owner or item.product_id
    found = [item for batch in batches for item in batch]

    if source_name:
        found = [item for item in found if item.source_name == source_name]

    return {
        "query": query,
        "mode": mode,
        "results": [item.model_dump() for item in found[:limit]],
        "documents": list(
            dict.fromkeys(
                name
                for names in await asyncio.gather(*(asyncio.to_thread(s.documents_indexed) for s, _ in stores))
                for name in names
            )
        ),
        # Set when meaning-based search could not run, so the interface can say
        # so rather than implying the corpus holds nothing.
        "degraded": bool(degraded),
    }
