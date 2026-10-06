# Plan 018: Products, each with its own knowledge and memory (milestone M7)

**Status:** active (awaiting the user's decisions; no code written yet)

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
own plan (019 onwards) with its own acceptance criteria, checked off and
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

1. **Plan 019, products as records:**
   - move the migrations to `src/migrations.py`, behind the upgrade tests;
   - add migration 11, the `products` table;
   - write `src/products.py`, with create, edit, delete, list and validation;
   - add a router `src/routes/products.py`, administrator-only for writes;
   - add new errors;
   - seed from `SEED_PRODUCTS`;
   - add a Products section to the Access panel;
   - write tests, including a browser test that adds a product.
2. **Plan 020, product knowledge bases:**
   - give each product its own collection;
   - choose the upload target (shared or a product), and list or remove documents per scope;
   - write `src/scoped_knowledge.py`, which merges shared and product search, dense and lexical;
   - label the evidence;
   - add a scope switch to the knowledge-base panel;
   - deleting a product drops its collection;
   - move the knowledge routes into `src/routes/knowledge.py`;
   - write tests that General's snapshots are unchanged.
3. **Plan 021, product answer memories:**
   - migration 12, `memory_entries.product_id`;
   - index entries in their product's collection;
   - route approvals by the questionnaire's product;
   - choose the target when teaching an answer by hand;
   - add "move to shared" and "move to product";
   - scope the disagreement sweep and supersession;
   - add a scope switch to the memory page;
   - deleting a product deletes its entries;
   - move the memory routes out of `api.py`.
4. **Plan 022, choosing the product:**
   - migration 13, `form_batches.product_id` and `conversations.product_id`;
   - choose the product at upload or later;
   - carry the scope through `tools`, `service` and the graph to retrieval;
   - the chat chip beside the chat box, the workbench selector and the badges in lists;
   - tell the assistant the conversation's product;
   - the drafter's precedence rule (decision 2);
   - write browser tests for the main path.
5. **Plan 023, cleanup round 4,** after M7.

Evaluation stays on General, the shared scope, so plans 013 and 014 still
apply. A product-level evaluation needs product questionnaires and answers,
which do not exist yet.

## Progress log

- 2026-10-06: Plan drafted from a reading of the code. It waits for the user's decisions 1-8 before plan 019 starts.

## Decision log
