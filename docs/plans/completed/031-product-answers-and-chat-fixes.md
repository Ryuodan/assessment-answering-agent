# Plan 031: Product answers keep shared material apart; ingest asks which knowledge base; the chat's fixes; search per product

**Status:** completed 2026-11-07

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

- [x] A product's questionnaire tells the drafter and the reviewer which product it is about, its description if it has one, and the team's other products.
- [x] Every source is marked FOR the product, or SHARED. A line above the sources says which are the product's own, or that none is.
- [x] The drafter states a shared policy as the organisation's policy, and takes no product-specific fact from a shared source.
- [x] The reviewer holds an answer that states a product-specific fact that only shared sources support.
- [x] The assistant's own searches in a product's conversation mark shared clauses the same way.
- [x] A General questionnaire's prompts are unchanged, byte for byte. A test pins it.
- [x] Measured before and after on the same 24 product questions.

Adding documents:

- [x] The Knowledge base page starts with no knowledge base chosen. Adding, removing and clearing wait for a choice.
- [x] The page's address can name the shared knowledge base, so a reload keeps that choice. The Workbench's "Manage" link names the choice the Workbench made.

The chat and the Knowledge base page:

- [x] The chat's "Documents" button and drawer are gone. The document viewer that opens cited clauses stays.
- [x] "Your documents" is gone from the Knowledge base page. "view" still opens a document and the text read from it.
- [x] A conversation working on a turn keeps its message and progress when you switch away and back, and after a reload. Its reply lands in its own conversation, and the conversation on screen is untouched.
- [x] Another conversation can be used meanwhile. A second message to the busy conversation is refused (409 `conversation_busy`).
- [x] The conversation list can be resized by dragging or with the keyboard. The width is remembered.

Search:

- [x] The Workbench's search searches a product's knowledge base as well as the shared one, following the Workbench's product. A "Search in" choice changes it, and a product's hits carry its badge.

All:

- [x] The assistant's evaluation (`scripts/eval_assistant.py`) is run, and its result recorded.
- [x] Every change has a test that fails without it. `uv run poe check` passes.
- [x] The docs are updated: ARCHITECTURE.md, decisions, tech-debt, and the generated docs.
- [x] A "How to test it yourself" section covers each item.

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
- 2026-11-06: the assistant's evaluation, all 42 cases once. It ran against a copy of the index (`CHROMA_DIR`) and the script's own scratch database; the hashes of `data/app.db` and `chroma_db/chroma.sqlite3` were the same before and after.
  - 98% overall. `reword-only-never-re-answers` returned an empty reply once, then passed 3 of 3.
  - `arabic-compound` passed only 1 of 4 runs. Asked in Arabic to "answer all of it, one short sentence each", the assistant skipped `reword_answers`.
  - On the code before plan 030 (`2c41f2e`) it passed 3 of 3. The cause was plan 030's "never restate, translate, summarise or reword the answer", a rule about the model's own reply that it applied to the answers.
  - Reworded in the prompt and in `answer_directly`'s result: "do not repeat the drafted text in your reply", and `reword_answers` still rewords on request. Then `arabic-compound` passed 3 of 3. The six cases that draft in the chat passed, as did `compound-answer-then-reword`.
  - A test now pins that the rule does not say "reword".

- 2026-11-06: the two builders' branches merged into main.
  - **The Knowledge base page and search** (`cf07bb2`, `3fcff46`, D-027):
    - the page opens with no knowledge base chosen; `?product=general` names the shared one;
    - "Your documents" is removed;
    - the Workbench's search has "Search in", follows the Workbench's product, reloads its file filter and badges a product's hits.
    - **A server bug found and fixed (`src/search.py`):** a product's hits came first and were cut at the limit. A product with as many passages as the limit filled the list alone, so a product's search never showed a shared policy, in the Workbench or in the assistant's `search_policies`. The limit is now shared between the two knowledge bases. A test failed before the fix.
    - Recorded, not fixed: TD-074.
  - **The chat** (`5825033`, `5c36025`, D-028):
    - `src/chat_running.py` holds a running turn by its conversation; 409 `conversation_busy`;
    - `running` is reported on `GET /api/chat/{id}` and `GET /api/chat`;
    - the page follows turns by run id; the Documents drawer is gone; the conversation list can be resized (`#sideResizer`).
    - Also: only the last conversation clicked is drawn, which fixes an earlier click race, and the history list ignores late responses.
    - 12 unit tests and 10 browser tests; 9 of the 10 failed on the old page.
    - Recorded, not fixed: TD-075.

- 2026-11-06: an adversarial review of the merged change. It found nothing wrong in product drafting or in search, and five defects elsewhere, four reproduced. All are fixed, each with a test that failed before:
  - **A reply that arrived while its conversation was being opened** left it showing neither the message nor the reply. The route reads `running` before the transcript now, and the page reads the conversation again when a reading reports a turn it knows has ended.
  - **A turn ending in the background discarded the conversation the person had just clicked.** Background redraws apply only to the conversation last asked for.
  - **A turn sent without a run id** (scripts, not the page) made an open conversation redraw itself every 2.4 s. The routes mint one.
  - **An upload to a busy conversation could be saved and then refused.** The hold is taken before the file is saved.
  - **"Index guidelines" kept its hidden hint as its accessible description** after a choice was made (`53c6528`).
  - Two lesser things, also fixed. A reply lost to a proxy timeout no longer reads "That did not work" while the turn goes on: the page checks the server and follows the turn. Running turns are watched through the list, `GET /api/chat`, instead of re-reading each whole conversation every 2.4 s.
  - TD-075's duplicate message is fixed too: a pending message the transcript already ends with is not drawn again.
- 2026-11-07: tested end to end at the user's request ("Test the system from A to Z and make sure it is ready to be used"): plan 035's A-to-Z run, the real app and model on a copy of the local data, 20 of 20 steps passed, with no page or server errors. Plan complete.

## Decision log

- 2026-11-06, Claude, on defaults the user has not decided (each can be reversed):
  - The shared knowledge base is `?product=general` in the Knowledge base page's address, the value the Workbench uses for General.
  - Workbench search follows the Workbench's product, because searching changes nothing; "Search in" changes it.
  - The product's search shares its limit with the shared knowledge base, a builder's fix of a bug the brief allowed.
  - The wording of plan 030's chat rule was changed after the evaluation found it read as "never reword".
- 2026-11-06, by the user:
  - the prompt is reworked so shared material does not read as the product's;
  - the assistant's evaluation is run;
  - ingesting asks for the knowledge base, as answering asks for the product;
  - the chat's Documents drawer and "Your documents" go;
  - switching conversations mid-turn is fixed;
  - the conversation list is resizable;
  - search works per product.

## How to test it yourself

On your local copy. Start the app with `uv run python -m uvicorn src.api:app --reload` and open http://127.0.0.1:8000.

### Product answers

1. In the Assistant, start a chat for Msegat (or open a Msegat questionnaire on the Workbench) and ask about something only shared material covers, such as "Is data stored by Msegat encrypted at rest?" or "Where is Msegat hosted?".
2. The answer states our policy as the organisation's ("T2's organisation-wide cryptography policy requires..."), and says when Msegat's own documents do not give the detail. It does not say "Msegat uses AES-256", and does not name another product's hosting.
3. An answer that still states a Msegat detail from shared material shows "Needs review" with "Not backed by our documents", at 30% or less.
4. Ask the same in a General chat: the answer reads as it always did.
5. Optional: on the Products page, give Msegat a one-line description ("an SMS gateway for businesses"). The drafter is now told it.

### Adding documents

1. Open the Knowledge base page from any header. Nothing is chosen ("Choose a knowledge base…"): "Index guidelines" is disabled, with a line saying why, and the list asks you to choose.
2. Choose "Shared, for every product": the shared list appears, and the address ends with `?product=general`. Reload: still shared.
3. Choose Msegat: its list appears, the address names it, and a document you add goes to Msegat.
4. Open `/knowledge` with no address part: nothing is chosen again.
5. On the Workbench, choose General and click "Manage": the page opens on the shared knowledge base. Choose Msegat and click it: Msegat's opens. With nothing chosen, nothing is chosen there either.
6. "Your documents" is gone. Click "view" beside an indexed source: the document opens, with "Extracted text" beside it.

### The chat

1. The Assistant's header has no "Documents" button. A source chip on an answer card still opens its clause and document.
2. In a chat, attach a questionnaire and ask it to answer everything. While it works, click another conversation, then come back: your message and the progress bar are there, still moving.
3. While it works, open another conversation and ask a question there: it answers. The working conversation's row says "Working…", and when it finishes, "New reply". Its reply is not drawn into the conversation on screen, and the answers panel on screen is not replaced.
4. Reload the page while a turn works and open that conversation: its message and progress are shown, then the reply when it ends.
5. Try to forget a conversation while it works: it is refused, with the reason.
6. Drag the right edge of the conversation list to make it wider or narrower (or Tab to it and use the arrow keys). Reload: it keeps the width. Double-click the edge: back to the default. ☰ still hides and shows the list.

### Search

1. On the Workbench, choose Msegat and open Search. "Search in" shows "Msegat and shared policies", and the file filter lists Msegat's files and the shared ones.
2. Search for something both cover: Msegat's passages carry its badge, and shared policies are listed too. Before this plan, a product with many passages pushed every shared policy out of the list.
3. Change "Search in" to "Shared policies": the search runs again, without Msegat's passages or files.
4. Choose General on the Workbench and open Search: it searches the shared policies.
