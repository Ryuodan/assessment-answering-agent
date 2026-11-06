"""Looking something up in a team's knowledge base, without touching a questionnaire.

Moved from `src/service.py` (plan 023), which re-exports `search_knowledge`, so
the interface and the tools call it where they always have.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src import knowledge, scoped_knowledge
from src.lexical import reciprocal_rank_fusion
from src.logs import get_logger
from src.models import Evidence, SourceType

logger = get_logger(__name__)


# A person waiting at a search box will not wait a minute for a remote
# embedding host that is not answering. The literal search needs no network.
SEARCH_EMBED_TIMEOUT = 10.0


def _shares(sizes: list[int], limit: int) -> list[int]:
    """How many of each list a result of `limit` keeps: one each in turn, the first list first.

    So neither crowds the other out, and what one does not use the other takes.
    One list keeps its first `limit`, as a search of the shared policies always did.
    """
    shares = [0] * len(sizes)
    while sum(shares) < limit and any(share < size for share, size in zip(shares, sizes)):
        for index, size in enumerate(sizes):
            if shares[index] < size and sum(shares) < limit:
                shares[index] += 1
    return shares


async def search_knowledge(
    query: str,
    *,
    mode: str = "hybrid",
    limit: int = 20,
    source_name: str = "",
    team_id: str | None = None,
    product_id: str = "",
    earlier_answers: bool = False,
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
    the shared one, and its hits come first and carry its id (plan 023). The
    `limit` is shared between the two (plan 031), as answering keeps each its
    own list (plan 021): the vectors return `limit` passages however far they
    are, so the product's hits, put first and cut at the limit, filled it alone
    and the shared policies were never shown.

    With `earlier_answers`, the team's remembered answers get a share of the limit
    of their own, as each knowledge base does (TD-074). Listed after every
    guideline and then cut, they almost never appeared in the Workbench's search.
    The assistant's `search_policies` leaves it off: it looks up what the
    documents say, and what it reads is as it was. `source_name` is applied in
    each store, before its cut, so one file's passages are not lost behind better
    ones elsewhere.
    """
    query = (query or "").strip()
    if not query:
        return {"query": "", "mode": mode, "results": [], "documents": []}

    shared = knowledge.get_store(team_id)
    stores = [(scoped_knowledge.own_store(team_id, product_id), product_id)] if product_id else []
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
                    store.search(query, source_type, limit, expand=False, source_name=source_name),
                    SEARCH_EMBED_TIMEOUT,
                )
            except Exception as error:  # noqa: BLE001 - search degrades to keyword results, it does not fail
                # The embedding service is remote and occasionally slow to
                # answer; a person at a search box should get the literal
                # matches rather than a spinner or a stack trace.
                degraded.append(str(error) or repr(error))
                logger.warning("search.semantic_unavailable", error=str(error) or repr(error))
        if mode in ("keyword", "hybrid"):
            literal = await asyncio.to_thread(store.text_search, query, source_type, limit, source_name)
        if not dense and degraded and mode == "semantic":
            # Nothing to show otherwise: answer the query the one way still working.
            literal = await asyncio.to_thread(store.text_search, query, source_type, limit, source_name)
        if mode != "hybrid":
            return dense or literal

        # Fused on rank, not score: a text-match count and a cosine are not
        # comparable numbers, and averaging them would silently favour
        # whichever happens to use the wider range.
        by_key: dict[tuple[str, int, str], Evidence] = {}
        for item in dense + literal:
            by_key.setdefault(item.key, item)
        rankings = [
            [item.key for item in dense],
            [item.key for item in literal],
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

    # Each knowledge base's hits in its own order, guidelines then remembered
    # answers; each keeps its share of the limit, and they are listed as before.
    # With `earlier_answers`, each knowledge base's remembered answers have a share too.
    kinds = (SourceType.GUIDELINE, SourceType.PRIOR_ANSWER) if earlier_answers else (None,)
    groups = [
        [
            item
            for (_, _, owner, kind), batch in zip(jobs, batches)
            if owner == base and wanted in (None, kind)
            for item in batch
        ]
        for wanted in kinds
        for _, base in stores
    ]
    shares = _shares([len(hits) for hits in groups], limit)
    kept = {id(item) for hits, share in zip(groups, shares) for item in hits[:share]}
    found = [item for batch in batches for item in batch if id(item) in kept]

    return {
        "query": query,
        "mode": mode,
        "results": [item.model_dump() for item in found],
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
