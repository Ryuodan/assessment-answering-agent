# Plan 021: Product knowledge bases

**Status:** completed

## Goal

Each product gets a knowledge base of its own, beside the team's shared one.
A person can add a policy to the shared knowledge base or to a product's, see
what each holds, and remove from either. Deleting a product (plan 020) also
deletes its knowledge base.

A search for a product reads both its own and the shared material, the
product's first. Answering questionnaires for a product (plan 023) will use
that search, and General keeps today's path.

## Acceptance criteria

- [x] Each product has its own Chroma collection, named within Chroma's rules (3-63 characters) and distinct from every team collection. The team's shared collection is untouched, and nothing already indexed moves.
- [x] `src/scoped_knowledge.py` returns the shared store for General and, for a product, a store that searches the product collection and the shared one with one embedding of the query. It lists the product's results first, each list up to its `k`.
- [x] `GET /api/knowledge`, `POST /api/knowledge/guidelines`, `DELETE /api/knowledge/sources/{name}` and `DELETE /api/knowledge` take an optional `product`. With none they behave exactly as before. With a product they work on that product's knowledge base only, and a product that is not the caller team's is `product_not_found`. The four routes move to `src/routes/knowledge.py`, included where they were.
- [x] Deleting a product drops its collection.
- [x] The workbench's knowledge-base panel and the assistant page's knowledge-base drawer both have a selector: Shared, or a product. Upload, list, remove and clear act on the chosen one.
- [x] Tests:
  - collection names;
  - search for a product against General, with fake stores;
  - one embedding per query;
  - the routes per scope, with General unchanged and another team's product refused;
  - deletion dropping the collection;
  - a browser test of the selector.

  The characterization snapshots are unchanged.
- [x] `knowledge.py`, `service.py` and `api.py` are no longer than before. `uv run poe check` passes.

## Plan

1. Move `collection_for` and `cosine_from_relevance` from `knowledge.py` to a new `src/vector_names.py`, re-exported where tests read them. Add the product collection name.
2. `KnowledgeStore` and `get_store` take a `product_id` (keyword only, so every existing call and test fake is unchanged). `search_types` can be given a vector, and a store can `drop()` its collection.
3. Write `src/scoped_knowledge.py`: `store_for`, `ScopedStore`, and `drop_product`. Move the knowledge-base management functions (`knowledge_stats`, `delete_source`, `clear_knowledge`) from `service.py` there, scoped. `service.ingest` takes a product.
4. Move the knowledge routes to `src/routes/knowledge.py` with `product`. Make `products.delete` drop the collection.
5. Add the selector to both pages, write the tests and the docs, run the gate, and close the plan.

## Progress log

- 2026-10-06: Steps 1 and 2:
  - `collection_for` and `cosine_from_relevance` moved to `src/vector_names.py`, re-exported by `knowledge`.
  - A product's collection is `<base>-p-<16 hex of team/product>`.
  - `KnowledgeStore` and `get_store` take `product_id`, as a keyword only, so the test fakes written as `lambda team_id=None` still fit every existing call. `search_types` takes a `vector`, and `drop_store` deletes a product's collection (never a shared one).
- 2026-10-06: Step 3:
  - `src/scoped_knowledge.py` has `own_store`, `ScopedStore`, `store_for`, `drop_product`, and the three management functions moved from `service.py`. `service` re-exports them, so the tests that patch `service.knowledge_stats` and `service.delete_source` still reach them.
  - The scoped module looks `knowledge.get_store` up at call time, so a fake patched into `src.knowledge` is the one used.
  - `service.ingest` takes `product_id`.
  - The tests that patch the store (team isolation, hostile input, team workflow, question list, memory import, diagnostics): 145 passed.
- 2026-10-06: Step 4:
  - The four knowledge routes, `_ingest_files`, `_record_indexing` and `check_suffix` moved to `src/routes/knowledge.py` (114 lines), included where they were.
  - Each route takes `product`, and passes it on only when one is chosen, so General's calls are byte-for-byte the old ones; a test that stubs `delete_source` with two arguments still fits.
  - The contract keeps its path order; only `/api/knowledge` and `/api/knowledge/sources/{name}` changed, gaining `product`.
  - `products.delete` drops the collection first.
  - Size: `api.py` 1811 -> 1700, `knowledge.py` 827 -> 788, `service.py` 741 -> 711.
  - mypy: 6 baseline errors fixed. One of them was the `get_store.cache_clear` assignment, re-keyed when the signature changed; it is now set with `setattr`, not re-baselined. Baseline 272 -> 266.
- 2026-10-06: Step 5:
  - The workbench's step 1 and the assistant's knowledge-base drawer both have a "Knowledge base" selector, Shared or a product. Listing, upload, remove and clear follow it, and the hint says which questionnaires it is used for.
  - `tests/test_product_knowledge.py`: 12 tests, passing on the first run. They cover collection names; product-first search with one embedding; General being the shared store itself; uploads, listing, removal and clearing per scope with the shared one untouched; another team's product refused on all three routes; ingest indexing into the product's store only; deletion removing the collection from real Chroma; and the shared collection refusing to be dropped.
  - `tests/browser/test_knowledge_scope.py`: 2 tests, for the workbench selector (list, hint, upload with the product, back to shared) and the drawer's.

- 2026-10-06: The first gate attempt was stopped early. ruff found two unused imports in the new browser test, and `knowledge.py` was one line over its ceiling, because a two-line comment had replaced a one-line one. Both fixed. `uv run poe check` passes (1,841 tests, 10 browser tests). Plan complete.

## Decision log

- 2026-10-06: A product's search lists its own results first, then the shared ones, each up to its own `k`, rather than merging by score. Merged by score, a large shared corpus could crowd out the product's few documents. Order is what the drafter reads first, and plan 023 tells it that a product's material wins. The evidence budget (`MAX_EVIDENCE_CHUNKS`) still caps what reaches the drafter. (Claude)
- 2026-10-06: Product documents are saved in the team's upload folder, like shared ones. Removing a document from a knowledge base only removes it from that index, as it already does, so a file of the same name in both cannot be lost from one by removing it from the other. (Claude)
