# Plan 022: Product answer memories

**Status:** completed

## Goal

Each product gets an answer memory of its own beside the team's shared one.
An answer remembered for a product is indexed in that product's knowledge
base, so a product's search (plan 021) finds it before the shared ones. The
disagreement sweep compares it only with answers in the same memory: a
product answer that differs from a shared one is that product's own answer,
not a conflict (decision 2).

The memory page shows one memory at a time, Shared or a product. An answer
can be taught to either, or moved between them. Deleting a product deletes
its remembered answers.

Approved answers follow their questionnaire's product once questionnaires
have one (plan 023). Until then they go to the shared memory, as today.

## Acceptance criteria

- [x] Migration 12 adds `memory_entries.product_id` (`''` is shared), and existing entries stay shared. A database at version 11 upgrades and keeps its data.
- [x] `answer_memory.record`, `entries`, `count`, `stats` and `conflicts` take a product. Left out, `entries` and `count` read every memory, as before; the routes always name one, with Shared the default. An entry is indexed in its own memory's knowledge base.
- [x] The sweep searches only the entry's own memory, so supersession and conflicts stay inside one scope. A test shows a product answer and a contradictory shared answer raising no conflict.
- [x] `answer_memory.move(entry, product)` moves an entry to the shared memory or another product's. It is re-indexed there and compared again with its new neighbours.
- [x] Deleting a product deletes its entries and their conflicts, and the product's collection goes with them.
- [x] Routes:
  - `GET /api/memory` and `GET /api/memory/conflicts` take `product`;
  - `POST /api/memory` takes `product`;
  - a new `POST /api/memory/{id}/move`;
  - another team's product is `product_not_found`.

  The memory routes move to `src/routes/memory.py`, included where they were.
- [x] The memory page has a selector, Shared or a product. The list, the counts, the disagreements and "teach an answer" follow it, and each entry can be moved.
- [x] Tests:
  - records per scope;
  - the scoped sweep;
  - moving;
  - the deletion cascade;
  - the routes, including another team's product;
  - an upgrade from version 11;
  - a browser test of the selector and the move.
- [x] `answer_memory.py` and `api.py` are no longer than before. `uv run poe check` passes.

## Plan

1. Move the sweep (`scan`, `scan_pending` and their helpers) from `answer_memory.py` to a new `src/memory_sweep.py`. `answer_memory.scan` and `answer_memory.scan_pending` stay, as thin wrappers, so every caller is unchanged. The tests that patch the sweep's helpers follow them to the new module.
2. Add migration 12. `Entry` gets `product_id`. Scope `record`, the readers, indexing and the sweep. Add `move` and `forget_product`.
3. Move the memory routes to `src/routes/memory.py`, with `product` and `move`. `products.delete` forgets the product's entries.
4. Add the selector and the move to the memory page. Write the tests and the docs, run the gate, and close the plan.

## Progress log

- 2026-10-06: Step 1. The sweep moved to `src/memory_sweep.py` (148 lines): `_same_question`, `_cosine`, `_close_questions`, `scan` and `scan_pending`. Calls back into the record go through `answer_memory.<name>`, and its two log lines are now events (`memory.same_question_unparsed`, `memory.scan_failed`), as ARCH-LOG requires of a new module. `answer_memory.scan` and `scan_pending` are wrappers, so the routes, tools, CLI and scripts are unchanged. The tests that patch or call `_same_question` and `_close_questions` now do so on `memory_sweep`. `answer_memory.py` went from 918 to 783 lines before this plan's own code.
- 2026-10-06: A mistake of mine, recorded: right after the move I ran `poe arch-lower`, which set `answer_memory.py`'s ceiling to 783, before the code that the room was made for existed. The working-tree allow-list was restored to its committed value (918) and lowered again at the end of the plan, so the committed ceilings only ever went down.
- 2026-10-06: Step 2:
  - migration 12 (`memory_entries.product_id`, and an index on `(team_id, product_id)`);
  - `Entry.product_id`;
  - `record`, `entries`, `count`, `stats` and `conflicts` take a product (`entries` and `count` read every memory when it is left out);
  - indexing and unindexing go to the entry's own memory's store (`scoped_knowledge.own_store`), and `remove` reads the entry first so it unindexes from the right one;
  - `move` and `forget_product`;
  - the sweep searches `own_store(team, entry.product_id)`.

  The memory tests (answer memory, memory, import, team isolation, store): 131 passed.
- 2026-10-06: Step 3:
  - The memory routes and the background sweep moved to `src/routes/memory.py` (266 lines). `api._scan_memory` is still importable, as a test calls it.
  - `product` was added to listing, conflicts and teaching, and a new `POST /api/memory/{id}/move`. The contract gained that path and changed only `/api/memory` and `/api/memory/conflicts`, keeping its order.
  - `products.delete` forgets the product's entries after dropping its collection.
  - The moved routes' bare `dict` returns were typed. The restore route, typed, showed it could pass `None` to the payload if the entry vanished between the restore and the re-read; it now answers 404 instead of failing with a 500. The mypy baseline went from 266 to 256.
  - Size: `api.py` 1700 -> 1440, `answer_memory.py` 918 -> 836.
- 2026-10-06: Step 4:
  - The memory page has a selector, Shared or a product. The list, counts, disagreements and "Remember this" follow it, and each entry has a "Move to…" menu.
  - `tests/test_product_memory.py`: 7 tests, passing on the first run. They cover one memory per answer, indexed in its own store; a product answer against a contradictory shared one raising nothing, while the same pair inside one memory raises one disagreement; moving with re-indexing and re-comparison; the deletion cascade; the routes per memory; another team's product refused on four routes; and an upgrade from version 11.
  - The scoped-sweep test was checked against its regression: with the sweep searching the shared memory again, it fails.
  - `tests/browser/test_memory_scope.py`: the page shows one memory, and an answer is moved from Availo's to the shared one.

- 2026-10-06: The first full gate failed one test. It patched `api.answer_memory.scan_pending`, and `api.py` no longer imports `answer_memory` now that the memory routes live in `src/routes/memory.py`. It now patches `answer_memory.scan_pending`, the same function it always meant.

- 2026-10-06: `uv run poe check` passes (1,848 tests, 11 browser tests). Plan complete.

## Decision log

- 2026-10-06: Read without a product, `entries` and `count` still return every memory, so the scripts, the evaluation and the tests that read the whole memory see what they saw before. The routes always name a scope, Shared by default, so the page shows exactly what it showed before products while no entry has one. (Claude)
- 2026-10-06: A moved entry is compared again (its `scanned_at` is cleared). Its neighbours are now different answers, and supersession and conflicts are only meaningful among them. The links it had in its old memory (what it superseded, open conflicts) are left as they were: they record what was true where they were raised. (Claude)
