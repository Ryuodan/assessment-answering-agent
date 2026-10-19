"""A team's knowledge base, shared or for one product (plan 021).

The team keeps one shared knowledge base. A product has one of its own beside
it, in a collection of its own (`vector_names.collection_for`):

    store_for(team)            the shared store, exactly as before products
    store_for(team, product)   the product's material first, then the shared

Searching for a product embeds the query once and asks both collections with
that one vector. The product's results come first, each list up to its own `k`:
merged by score, a large shared corpus could crowd a product's few documents out
(plan 021's decision log). Uploads, lists and removals go to one knowledge base
or the other, never both.

The knowledge-base management functions moved here from `src/service.py`, which
re-exports them, and took a `product_id`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from src import knowledge, store, uploads
from src.config import settings
from src.errors import NotADocument, ProductDeleted
from src.knowledge import KnowledgeStore
from src.logs import get_logger
from src.models import Evidence, SourceType

logger = get_logger(__name__)


def own_store(team_id: str | None, product_id: str = "") -> KnowledgeStore:
    """The one knowledge base an upload or a removal goes to: the shared one, or a product's."""
    return _product_store(team_id, product_id) if product_id else knowledge.get_store(team_id)


def _product_store(team_id: str | None, product_id: str) -> KnowledgeStore:
    """A product's knowledge base, refused once the product is deleted (plan 027).

    Asking for one makes its collection, so a deleted product's -- asked for by a
    questionnaire, a chat or a remembered answer that still names it -- would
    come back, empty, and never be dropped again. `src.products` writes
    `deleted_products`; this only reads it.
    """
    query = "SELECT name FROM deleted_products WHERE team_id = ? AND product_id = ?"
    gone = store.connect().execute(query, (team_id or settings.default_team, product_id)).fetchone()
    if gone:
        raise ProductDeleted(f"{gone['name']} was deleted, and its knowledge base with it.")
    # Looked up on the module at call time, so a test's fake store is the one used.
    return knowledge.get_store(team_id, product_id=product_id)


class ScopedStore:
    """A product's knowledge base read together with the team's shared one.

    Offers what retrieval asks of a store (`counts_by_type`, `search_types`), so
    the answering pipeline can be handed either.
    """

    def __init__(self, team_id: str | None, product_id: str) -> None:
        self.product_id = product_id
        self.shared = knowledge.get_store(team_id)
        self.product = _product_store(team_id, product_id)

    def counts_by_type(self) -> dict[str, int]:
        counts = dict(self.shared.counts_by_type())
        for kind, count in self.product.counts_by_type().items():
            counts[kind] = counts.get(kind, 0) + count
        return counts

    async def search_types(
        self, query: str, wanted: list[tuple[SourceType, int]], *, expand: bool = True
    ) -> dict[SourceType, list[Evidence]]:
        """The product's hits, labelled with its id, then the shared ones, for each source type asked for."""
        wanted = [(source_type, k) for source_type, k in wanted if k > 0]
        if not wanted or not query.strip():
            return {}
        vector = await self.shared._embed_query(query)
        own, shared = await asyncio.gather(
            self.product.search_types(query, wanted, expand=expand, vector=vector),
            self.shared.search_types(query, wanted, expand=expand, vector=vector),
        )
        for item in (item for items in own.values() for item in items):
            item.product_id = self.product_id
        return {source_type: own.get(source_type, []) + shared.get(source_type, []) for source_type, _ in wanted}


def store_for(team_id: str | None, product_id: str = "") -> KnowledgeStore | ScopedStore:
    """What answering for this scope searches: the shared store, or a product's beside it."""
    return ScopedStore(team_id, product_id) if product_id else knowledge.get_store(team_id)


def drop_product(team_id: str, product_id: str) -> None:
    """Delete a product's knowledge base. Called when the product is deleted."""
    knowledge.drop_store(team_id, product_id)


def knowledge_stats(team_id: str | None = None, *, product_id: str = "") -> dict[str, Any]:
    """Counts and indexed file names, for the UI's knowledge panel."""
    return own_store(team_id, product_id).stats()


def delete_source(
    source_name: str, team_id: str | None = None, *, product_id: str = "", also: Sequence[Path] = ()
) -> list[str]:
    """Remove one previously uploaded policy document from a knowledge base.

    Only documents. Previous answers are indexed too, but they belong to the
    answer memory, where each has a row -- who approved it, what it replaced --
    that a delete by source name would orphan by the hundred.

    A product's document takes its file with it (plan 027), and `also`: its
    file from before it had a folder, which `src.products` finds. A shared
    one's file stays in the team's folder, as it always has. Returns the files
    that could not be removed.
    """
    index = own_store(team_id, product_id)
    kind = index.source_type_of(source_name)
    if kind == SourceType.PRIOR_ANSWER.value:
        raise NotADocument("Previous answers are part of the answer memory. Manage them on the Answer memory page.")
    if not kind:
        # Said, rather than reported as deleted: a name that was never indexed,
        # or already removed by somebody else, is not something this removed.
        raise KeyError(source_name)
    index.delete_source(source_name)
    return _remove_files(team_id, product_id, also, [source_name]) if product_id else []


def clear_knowledge(team_id: str | None = None, *, product_id: str = "", also: Sequence[Path] = ()) -> list[str]:
    """Remove every policy document from a knowledge base, and leave the answer memory standing.

    It used to drop the whole collection, which took the memory's 698 vectors
    with it and left their rows on the memory page -- listed, and never
    retrieved again. Clearing the corpus and forgetting what the team has said
    are different decisions, made in different places.

    A product's documents take their files with them (plan 027), `also` as for
    `delete_source`; the shared ones' files stay in the team's folder. Returns
    the files that could not be removed.
    """
    own_store(team_id, product_id).delete_type(SourceType.GUIDELINE)
    return _remove_files(team_id, product_id, also) if product_id else []


def _remove_files(
    team_id: str | None, product_id: str, also: Sequence[Path], names: list[str] | None = None
) -> list[str]:
    """Delete a product's files, those named or all of them, and `also`, with the text read out of each.

    From its own folder, which holds its knowledge base and nothing else. The
    team's folder also holds the shared documents and questionnaires from
    before they were kept per person, so only the files of it named in `also` go.
    """
    files = uploads.document_files(settings.product_upload_dir(team_id, product_id))
    left = uploads.remove([path for path in files if names is None or path.name in names] + list(also))
    if left:
        logger.warning("knowledge.files_remove_failed", product=product_id, files=left)
    return left
