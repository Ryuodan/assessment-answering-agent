# Plan 031: Product answers keep shared material apart; ingest asks which knowledge base; the chat's fixes; search per product

**Status:** active

## Goal

The user's findings after testing plan 030. When it is done:

- **A product's answers say what is the product's and what is the organisation's.**
  An answer about Msegat states nothing about Msegat's own hosting, build, tools,
  figures or tests that only shared material supports. A shared policy is stated
  as the organisation's policy, covering every product.
- **Adding documents asks which knowledge base they go to,** as answering asks
  which product. Nothing is added to the shared knowledge base by default.
- **The chat has no "Documents" drawer,** and the Knowledge base page has no
  "Your documents" list: the Knowledge base page is where documents are managed.
- **Switching conversations while one is working loses nothing.** Its message
  and progress are there when you come back, and its reply lands in its own
  conversation.
- **The conversation list can be resized.**
- **Search works for each product.**
- **The assistant's evaluation is run** after the prompt changes (TD-071).

The user tests this round before the next.

## What the user found, and what was measured

"Answers with a selected product mix unrelated information from the
general/shared knowledge base, and it sounds like it is information related to
the product."

Measured before any change, on 24 questions about three products: eight each
for Msegat, Ole5 and RICH, about hosting, encryption, MFA, penetration tests,
RTO, DDoS protection, the security policy and leaving staff. They ran on a copy
of the local data, where Msegat and Ole5 have no documents of their own and RICH
has a few. Several answers with no source of the product's own were released to
the file as facts about the product:

- "Msegat is hosted on cloud infrastructure that is located in the Kingdom of
  Saudi Arabia", at 0.90.
- "Data stored by Ole5 is encrypted at rest... primarily AES-256", at 0.86.

They came from the organisation's shared policies, and from the shared answer
memory: the team's earlier answers, given about whichever product a past
questionnaire was for. One of them put Msegat on Alibaba Cloud.

The cause: the drafter was told that some sources were "FOR THIS PRODUCT", but
never which product, and nothing about the rest.

## Acceptance criteria

Product answers:

- [ ] A product's questionnaire tells the drafter and the reviewer which product it is about, its description if it has one, and the team's other products.
- [ ] Every source is marked FOR the product, or SHARED. A line above the sources says which are the product's own, or that none is.
- [ ] The drafter states a shared policy as the organisation's policy, and takes no product-specific fact from a shared source.
- [ ] The reviewer holds an answer that states a product-specific fact that only shared sources support.
- [ ] The assistant's own searches in a product's conversation mark shared clauses the same way.
- [ ] A General questionnaire's prompts are unchanged, byte for byte. A test pins it.
- [ ] Measured before and after on the same 24 product questions.

Adding documents:

- [ ] The Knowledge base page starts with no knowledge base chosen. Adding, removing and clearing wait for a choice.
- [ ] The page's address can name the shared knowledge base, so a reload keeps that choice. The Workbench's "Manage" link names the choice the Workbench made.

The chat and the Knowledge base page:

- [ ] The chat's "Documents" button and drawer are gone. The document viewer that opens cited clauses stays.
- [ ] "Your documents" is gone from the Knowledge base page. "view" still opens a document and the text read from it.
- [ ] A conversation working on a turn keeps its message and progress when you switch away and back, and after a reload. Its reply lands in its own conversation, and the conversation on screen is untouched.
- [ ] Another conversation can be used meanwhile. A second message to the busy conversation is refused (409 `conversation_busy`).
- [ ] The conversation list can be resized by dragging or with the keyboard. The width is remembered.

Search:

- [ ] The Workbench's search searches a product's knowledge base as well as the shared one, following the Workbench's product. A "Search in" choice changes it, and a product's hits carry its badge.

All:

- [ ] The assistant's evaluation (`scripts/eval_assistant.py`) is run, and its result recorded.
- [ ] Every change has a test that fails without it. `uv run poe check` passes.
- [ ] The docs are updated: ARCHITECTURE.md, decisions, tech-debt, and the generated docs.
- [ ] A "How to test it yourself" section covers each item.

## Plan

1. Product answers myself: prompts, nodes, the assistant's search marks, and tests. Measure them on a copy of the local data.
2. In parallel, two builders on their own branches:
   - the chat page: the drawer, switching, and resizing;
   - the Knowledge base page and the Workbench's search.
3. Merge, review adversarially, fix, run `uv run poe check`.
4. Run the assistant's evaluation; record it.
5. Docs and test notes; commit. The user tests.

## Progress log

- 2026-11-06: plan written. Before any change, the 24 product questions were run on a copy of the local data (`%TEMP%`, deleted after); the repository's `data/` and `chroma_db/` were not used.
- 2026-11-06: product answers (D-026).
  - New: `src/product_prompts.py` (the product's block for the drafter and the reviewer, the SHARED mark, the line above the sources) and `src/graph/product_scope.py` (looks the product up). `nodes.draft` and `nodes.review` add them for a product's questionnaire. The assistant's searches mark shared clauses SHARED in a product's conversation, and its prompt says what that means.
  - Measured three times after, each a step:
    1. the system block alone;
    2. plus the line above the sources;
    3. plus the reviewer told that saying a policy applies to the product is grounded.

    On the same 24 questions:

    | | before | step 1 | step 2 | step 3 (shipped) |
    |---|---|---|---|---|
    | released with a product fact only shared material supports | 6 | 4 | 0 | 0 to 1 |
    | held for review | 7 | 11 | 13 | 11 |

    - Step 1 still released "Ole5 is hosted on cloud services... in Saudi Arabia" with no source of Ole5's own.
    - Step 2 over-held "T2 maintains a documented Information Security Policy that applies to all of its products, including RICH".
    - Step 3 released it again.
    - Left: one answer infers from a policy ("Therefore Msegat supports MFA"). "Alibaba Cloud" was held each time it was drafted.
  - A General questionnaire's prompts are unchanged, byte for byte (`tests/test_product_scoped_answers.py`). The house set is General, so its numbers stand.
  - Found and recorded, not fixed: TD-072 and TD-073.

## Decision log

- 2026-11-06, by the user:
  - the prompt is reworked so shared material does not read as the product's;
  - the assistant's evaluation is run;
  - ingesting asks for the knowledge base, as answering asks for the product;
  - the chat's Documents drawer and "Your documents" go;
  - switching conversations mid-turn is fixed;
  - the conversation list is resizable;
  - search works per product.
