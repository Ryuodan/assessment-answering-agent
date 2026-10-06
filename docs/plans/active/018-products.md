# Plan 018: Products, each with its own knowledge and memory (milestone M7)

**Status:** active

## Goal

The security team answers questionnaires for several products. Each product
needs knowledge and past answers of its own, on top of what the whole team
shares.

When this milestone is done:

- **The shared layer is unchanged.** A team keeps one shared knowledge base
  and answer memory, as today.
- **Each product has its own.** A product (Availo, Msegat, Ole5, RICH,
  SouqT2 to start) can have its own knowledge base and answer memory.
- **Products can be managed.** They can be added, edited and deleted, and
  each product's documents and answers can be managed.
- **Every questionnaire and chat has a product.** Before or after uploading,
  a person picks a product or "General". A product's answers draw on the
  shared material and that product's own; General draws on the shared
  material only. The choice is visible:
  - as a coloured chip beside the chat box;
  - at the top of the workbench's questionnaire panel;
  - as a badge on every questionnaire.

The product data (files and answers) arrives later. Everything here works,
and is tested, with empty products.

This plan is the milestone's design and sequence. Each step below becomes its
own plan (019 to 025) with its own acceptance criteria, checked off and
committed one at a time.

## How it fits what exists

*Read from the code on 2026-10-06 (Claude).*

- **Knowledge base.** A team's knowledge base is one Chroma collection
  (`knowledge.collection_for(team)`). Guidelines and the answer memory's
  vectors share it, told apart by a `source_type` filter.
- **Answer memory.** It is also SQLite rows (`memory_entries`, keyed by team).
- **Questionnaires and chats.** These are `form_batches` and `conversations`,
  both keyed by team.
- **Products follow the team's pattern, one level down.** Each product gets a
  collection of its own beside the team's. The shared collection is not
  touched: General keeps today's code path exactly, and no stored vector is
  migrated. A product's answers search the shared collection and the
  product's, with the same query vector, and merge the results by score.
  Deleting a product drops its collection.
- **Size limits shape the work.** `api.py`, `store.py`, `knowledge.py`,
  `tools.py` and `answer_memory.py` are all at their size ceilings (ARCH-SIZE
  only lets them shrink). So the new logic goes into new modules:
  - `src/products.py` (records): the products themselves;
  - `src/scoped_knowledge.py` (integrations): searching shared plus product.

  The routes that change move out of `api.py` into routers under
  `src/routes/`. That shrinks `api.py` (TD-006) instead of growing it.
- **Schema changes.** Three new migrations: a `products` table, and a
  `product_id` column on `memory_entries`, `form_batches` and
  `conversations`. Existing rows get `''`, meaning General / shared. The
  migrations move first from `store.py` into `src/migrations.py`, unchanged,
  behind the existing database-upgrade tests. Shipped migrations are never
  edited.

## Decisions needed (the user's)

Each is listed with Claude's recommendation; none is built until it is decided.

1. **Whose products.** Products belong to a team: each team has its own list,
   and the five defaults go to the default team (cybersecurity).
   *Recommended.* The alternative is one global list for every team.
2. **When product and shared material disagree.** For a product's
   questionnaire, the product's own material wins. The drafter is told which
   sources are product-specific (a prompt change, measured on the dev split
   when there is product data to measure with). The memory's
   disagreement-finder compares answers only within the same scope, so a
   product answer that differs from a shared one is an override, not a
   conflict. *Recommended.*
3. **Where an approved answer is remembered.** In the questionnaire's
   product; a General questionnaire's answers go to the shared memory. The
   memory page can move an entry between a product and the shared memory.
   *Recommended.*
4. **Who manages products.** Administrators add, edit and delete products.
   Everyone can choose a product and add documents and answers to it, as
   they can today for the shared knowledge base. *Recommended.*
5. **Deleting a product.** It asks for the product's name to be typed, then
   deletes its documents and remembered answers. Questionnaires and chats
   that used it become General and keep their answers. *Recommended.* The
   alternatives are to refuse deletion until the product is empty, or to
   archive it (hidden, data kept).
6. **The five defaults.** A `SEED_PRODUCTS` setting, applied once on first
   start like `ALLOWED_EMAILS`, so deleting one is not undone by a restart.
   `.env.example` lists the five, and Claude adds the line to your `.env` if
   you agree. *Recommended.* The alternative is to add them by hand on the
   new Products panel.
7. **Where the choice is made.** All three places: the chip beside the chat
   box, the selector at the top of the workbench, and a badge on
   questionnaires in every list. Each product has a colour, editable with
   its name. *Recommended.*
8. **When the product changes after answering.** The answers already written
   stay; anything answered afterwards uses the new product. Answering again
   is a separate, explicit action. *Recommended.*

## Acceptance criteria

For the milestone as a whole; each step's plan has its own.

- [ ] Products can be listed, added, edited (name, colour, description) and deleted. Names are unique per team regardless of case. Every refusal is an `AppError` with a code (`product_not_found`, `product_name_taken`). The five defaults exist on first start.
- [ ] A document can be added to, listed in and removed from the shared knowledge base or a product's.
- [ ] Answering for a product uses shared plus product evidence, and each piece of evidence says which it is. Answering for General is unchanged: the pipeline's characterization snapshots stay as they are.
- [ ] The answer memory holds shared and per-product entries. Approval, teaching by hand, supersession and the disagreement sweep all respect the scope.
- [ ] Every questionnaire and chat has a product (General by default), chosen before or after upload, shown as a coloured chip or badge, and changeable.
- [ ] Deleting a product follows decision 5, and a test shows nothing of it is left in Chroma or SQLite.
- [ ] Browser tests cover the main path:
  - create a product;
  - choose it beside the chat box;
  - upload a questionnaire under it;
  - see the badge;
  - switch the knowledge-base panel to it.
- [ ] `api.py`, `store.py`, `knowledge.py`, `tools.py` and `answer_memory.py` are no longer than they are today. ARCHITECTURE.md describes scopes, and D-016 records the design.
- [ ] `uv run poe check` passes after every plan.

## Plan

Each step is its own plan.

1. **[Plan 019](../completed/019-room-for-products.md), room for products.** Moves only; behaviour unchanged:
   - the sign-in dependencies and the admin routes out of `api.py` into `src/routes/`;
   - the migrations out of `store.py` into `src/migrations.py`.

   The generated API contract must come out byte-identical, and the upgrade and error snapshots must pass.
2. **[Plan 020](../completed/020-products-and-leads.md), products and the team lead:**
   - the `lead` role ("Team lead"), with the role constants in `src/roles.py`;
   - migration 11, the `products` table;
   - `src/products.py`: create, edit, delete, list and validation;
   - `src/routes/products.py`: anyone on the team lists; the team's leads and administrators manage;
   - a `Conflict` (409) error for a taken name;
   - seeding from `SEED_PRODUCTS`;
   - a Products page: list, add, edit, and delete behind the coloured warning and a typed "confirm";
   - tests, including browser tests for adding and deleting.
3. **[Plan 021](../completed/021-product-knowledge-bases.md), product knowledge bases:**
   - give each product its own collection;
   - choose the upload target (shared or a product), and list or remove documents per scope;
   - write `src/scoped_knowledge.py`, which merges shared and product search, dense and lexical;
   - label the evidence;
   - add a scope switch to the knowledge-base panel;
   - deleting a product drops its collection;
   - move the knowledge routes into `src/routes/knowledge.py`;
   - write tests that General's snapshots are unchanged.
4. **[Plan 022](../completed/022-product-answer-memories.md), product answer memories:**
   - migration 12, `memory_entries.product_id`;
   - index entries in their product's collection;
   - route approvals by the questionnaire's product;
   - choose the target when teaching an answer by hand;
   - add "move to shared" and "move to product";
   - scope the disagreement sweep and supersession;
   - add a scope switch to the memory page;
   - deleting a product deletes its entries;
   - move the memory routes out of `api.py`.
5. **[Plan 023](../completed/023-questionnaires-carry-a-product.md), questionnaires and chats carry a product.** The backend and the API:
   - migration 13, `form_batches.product_id` and `conversations.product_id`;
   - choose the product at upload or later;
   - carry the scope through `tools`, `service` and the graph to retrieval;
   - tell the assistant the conversation's product;
   - the drafter's precedence rule (decision 2).
6. **[Plan 024](../completed/024-choosing-the-product.md), choosing the product on the pages:**
   - the chat chip beside the chat box;
   - the workbench selector;
   - the badges in lists;
   - browser tests for the main path.
7. **Plan 025, cleanup round 4,** after M7.

Evaluation stays on General, the shared scope, so plans 013 and 014 still
apply. A product-level evaluation needs product questionnaires and answers,
which do not exist yet.

## Progress log

- 2026-10-06: Plan drafted from a reading of the code. It waits for the user's decisions 1-8 before plan 019 starts.
- 2026-10-06: The user decided (below). Two changes to the sequence follow from it:
  - Plan 019 becomes a pure refactor that makes room. `api.py`, `store.py` and `identity.py` are at their size ceilings, and products, the new role and their routes cannot be added without first moving code out.
  - Product management gets its own page, not a section of the Access panel. Team leads are not administrators, and the Access panel is for administrators only.

- 2026-10-06: Plan 019 done: `api.py` 2036 -> 1862 lines, `store.py` 475 -> 132, and the contract byte-identical.

- 2026-10-06: Plan 020 done. It added the products, the team lead role, the Products page and the delete confirmation; `api.py` went from 1862 to 1811 lines and `identity.py` from 615 to 612.

- 2026-10-06: Plan 021 smaller than first sketched: carrying the product into answering moves to plan 023, where a questionnaire gets its product, so 021 is the knowledge bases and the search alone.

- 2026-10-06: Plan 021 done: product knowledge bases, the selector on both pages, and the knowledge routes moved out of `api.py` (1811 -> 1700 lines).

- 2026-10-06: Plan 022 done. It added product answer memories, the scoped sweep and moving; the sweep moved to `src/memory_sweep.py`; `api.py` went from 1700 to 1440 lines and `answer_memory.py` from 918 to 836.

- 2026-10-06: Plan 023 split from the pages. The backend, the API and the moves that made room for them were one plan's worth on their own, so the chip, the selector and the badges are plan 024, and cleanup round 4 becomes plan 025.

- 2026-10-06: Plan 023 done:
  - questionnaires and chats carry a product, and answering, approval, search and the assistant use it;
  - five moves made room, and the files they came from shrank: `api.py` 1440 -> 1296 lines, `tools.py` 1487 -> 1376, `service.py` 711 -> 614, `assistant.py` 1742 -> 1524, `models.py` 421 -> 329.

- 2026-10-06: Plan 024 done: the chip beside the chat box, the workbench's Product selector, the badges in the lists and on a product's sources, and browser tests for the main path.

## Decision log

- 2026-10-06, by the user: go with the recommendations for decisions 1, 2, 3, 6, 7 and 8. Two are changed:
  - **Decision 4.** A new role in the team manages that team's products; administrators can too. Named `lead`, shown as "Team lead" (Claude's choice of name, as the user asked).
  - **Decision 5.** Deleting a product shows a clear confirmation, with a coloured warning that its documents and remembered answers will be deleted. The person must type "confirm" to go ahead. Claude adds a server-side check that the request carries that word, so the API cannot delete a product without the same confirmation.
