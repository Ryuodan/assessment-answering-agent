# Plan 023: Questionnaires and chats carry a product

**Status:** completed

## Goal

A questionnaire and a chat each have a product, or General. Answering a
product's questionnaire draws on that product's knowledge base and answer
memory beside the shared ones (plans 021 and 022). The drafter is told which
sources are the product's own, and that they take precedence (decision 2 of
plan 018). Approving an answer remembers it in the questionnaire's memory
(decision 3). Changing the product later keeps the answers already written
(decision 8). Deleting a product returns its questionnaires and chats to
General with their answers (decision 5).

General keeps today's code path: the same store and the same prompts and
answers in the characterization snapshots.

This plan is the backend and the API. The chip beside the chat box, the
workbench selector and the badges are plan 024.

## Acceptance criteria

- [x] Migration 13 adds `form_batches.product_id` and `conversations.product_id` (`''` is General). A version-12 database upgrades, and its questionnaires and chats are General.
- [x] A questionnaire gets a product when it is opened, or later (`tools.set_product`). Another team's product is `product_not_found`. Changing it keeps the answers already written.
- [x] Answering a product's questionnaire searches the product's knowledge base and the shared one. Each piece of evidence carries `product_id` (`''` for shared). The single-question path and the whole-document path both carry the product.
- [x] General answering is unchanged. The prompts and answers in the pipeline's characterization snapshots are as they were; the one difference is the new `product_id` on each piece of evidence, empty.
- [x] When product evidence is present, the drafter's sources say which are the product's and that they take precedence. Without it, the sources block is byte-identical to before.
- [x] Approving a hand-written answer remembers it in the questionnaire's memory: the product's, or the shared one for General. Approving again after the product changed moves the entry.
- [x] A chat has a product. A questionnaire uploaded in it takes that product, and changing the chat's product changes its questionnaire's. The assistant's policy search covers the product and the shared knowledge base. Its prompt names the product when there is one and is unchanged when there is none.
- [x] Deleting a product returns its questionnaires and chats to General, with their answers.
- [x] Routes:
  - `POST /api/forms` takes `product`;
  - a new `POST /api/forms/{id}/product`;
  - `GET /api/forms` and `GET /api/forms/{id}` show `product_id`;
  - `POST /api/assessments/answer` and `/api/assessments/answer-questions` take `product`;
  - `GET /api/search` takes `product`;
  - `POST /api/chat` and `/api/chat/upload` take `product` for a chat they start, and a new `POST /api/chat/{id}/product` changes an existing chat's;
  - `GET /api/chat` and `GET /api/chat/{id}` show `product_id`.

  Another team's product is `product_not_found` on each.
- [x] Room is made by moves alone, before any product code:
  - `tools.py`: question selection and answer states move to `src/selection.py`;
  - `models.py`: the model-output schemas move to `src/schemas.py`;
  - `service.py`: policy search moves to `src/search.py`;
  - `assistant.py`: its system prompt moves to `src/agents/assistant_prompt.py`;
  - `api.py`: the assistant's routes move to `src/routes/chat.py`.

  The generated contract is byte-identical after the moves. Every file above, and `graph/nodes.py`, ends no longer than it started.
- [x] Tests:
  - the upgrade;
  - choosing and changing a questionnaire's product;
  - retrieval through the product's store, and the evidence labels;
  - the drafter's sources block, with product evidence and without;
  - approval into the product's memory, and moving on re-approval;
  - the chat's product reaching its questionnaire and its search;
  - the deletion returning questionnaires and chats to General;
  - each route, including another team's product.
- [x] `uv run poe check` passes.

## Plan

1. **Make room.** Moves only, behaviour unchanged. The contract is compared before and after.
2. **Records.** Migration 13; `Batch.product_id` and `batches.set_product`; `Conversation.product_id`; product ids in both lists; `products.delete` returns questionnaires and chats to General.
3. **Answering.**
   - `Evidence.product_id`, set on the product's hits by `ScopedStore`.
   - The product goes from `service.answer_questions` and the document flow through the graph's state to `retrieve`, which asks `scoped_knowledge.store_for`.
   - `search.search_knowledge` takes a product.
   - The precedence note in `format_sources_block`, only when product evidence is present.
4. **Operations.**
   - `tools`: `open_form`, `set_product`, `answer` and `search` take or pass the product; `approve_answer` remembers in the questionnaire's memory.
   - The assistant carries the conversation's product into uploads, search and its prompt.
5. **Routes,** then tests, docs and the gate.

## Progress log

- 2026-10-06: Step 1, five moves:
  - `tools.py` 1487 -> 1336 lines. `Scope`, the answer states (`BLANKED`, `HAND`, `APPROVED`) and the checks on them moved to `src/selection.py`; `tools` re-exports the names used through it.
  - `models.py` 421 -> 322. The model-output schemas moved to `src/schemas.py`. Their 13 importers now import from there, and `models.py` drops off the size allow-list.
  - `service.py` 711 -> 607. `search_knowledge` moved to `src/search.py`, re-exported. It looks the store up as `knowledge.get_store` at call time, so six tests that patched `service.get_store` for it now patch `knowledge.get_store`, or drop a patch that had become redundant. Its one log line is now an event (`search.semantic_unavailable`), as ARCH-LOG requires of a new module.
  - `assistant.py` 1742 -> 1496. Its system prompt and the Arabic reminder moved to `src/agents/assistant_prompt.py`, re-exported.
  - `api.py` 1440 -> 1263. The assistant's routes moved to `src/routes/chat.py`, included where they were.

  The moved code's bare `dict` returns were typed, and the mypy baseline went from 256 to 246. `graph/nodes.py` 406 -> 401, from the schema import.

  The generated contract is byte-identical, and the offline suite passes (1,848 tests).

- 2026-10-06: Step 2:
  - migration 13;
  - `Batch.product_id` and `batches.set_product`;
  - `Conversation.product_id`, written by `conversations.save`;
  - the product id in both lists;
  - `products.chosen`, which checks a product asked for is the caller's team's;
  - `products.delete` returns the product's questionnaires and chats to General.

  165 related tests passed.
- 2026-10-06: Step 3:
  - `Evidence.product_id`. `ScopedStore` labels the product's hits.
  - `retrieve` asks `scoped_knowledge.store_for`. The single-question and whole-document paths carry the product in the graph's state.
  - `search_knowledge` searches the product's knowledge base first, then the shared one, and lists both's documents.
  - `format_sources_block` marks a product's sources FOR THIS PRODUCT, and puts `PRODUCT_SOURCES_NOTE` above them when there are any.

  The two pipeline snapshots changed by one line each, `"product_id": ""` on the evidence. Nothing else in them changed, prompts included. They were re-recorded with `poe snapshots`, and the criterion was reworded to say exactly that (decision log).
- 2026-10-06: Step 4:
  - `tools.open_form` takes the product, `tools.set_product` changes it, and `inspect` shows it.
  - `answer` passes the product to the pipeline only when there is one, so General's call is the one it was.
  - `approve_answer` remembers into the questionnaire's memory, and moves an entry approved under another product.
  - `search` takes the product.
  - The assistant carries the chat's product into uploads and `search_policies`. Its prompt names the product (`FOR_PRODUCT`), only when there is one: `_agent` is called with a `product` keyword only then, so a General turn is the call it was. `assistant.choose_product` sets the chat's product and its questionnaire's. A new `PRODUCT_CHOSEN` event records either.
- 2026-10-06: Step 5:
  - The routes in the criteria.
  - The new request model was first named `ProductRequest`. That collided with the products routes' model of the same name, and FastAPI then qualified both schema names, which changed `/api/products` in the contract. Renamed `ChooseProductRequest`.
  - The chat routes first took `product` on every message, with "left out" meaning keep the chat's. Reviewing the diff showed that cannot work on the multipart upload route. FastAPI reads an empty form field as one not given, so General and "keep" would be the same request, and a chat switched back to General before an upload would have stayed on its product. Now a message names the product only of a chat it starts, and `POST /api/chat/{id}/product` changes an existing chat's, as `POST /api/forms/{id}/product` does a questionnaire's (decision log).
  - Against the contract saved before the plan:
    - two new paths;
    - `product` on `/api/forms`, `/api/search`, `/api/assessments/answer`, `AnswerQuestionsRequest`, `SayRequest` and the chat upload's form;
    - `product_id` on `Evidence`.

    The order is kept.
- 2026-10-06: Tests, in `tests/test_product_questionnaires.py`. 13 tests cover:
  - a questionnaire for a product, changed later with its answers kept;
  - retrieval through the product's store, with labels;
  - a product's search;
  - the whole-document path;
  - the sources block, with and without product evidence;
  - approval into the product's memory, and the move on re-approval;
  - the chat's product reaching its questionnaire and its search;
  - the prompt naming the product only when there is one;
  - the deletion returning work to General;
  - the upgrade from version 12;
  - the routes, including another team's product refused on seven routes.

  Five were checked against their regressions. Each failed with its fix undone: retrieval without the product; approval without the move; chat search without the product; deletion without the reset; and the sources block without the note.
- 2026-10-06: Docs. ARCHITECTURE describes a questionnaire's and a chat's product and the new modules. CLAUDE.md's map names them, with the operation and page counts brought up to date: 77 and 6. They had said 70 and 5 since plans 020-022. `boundaries.md` counts 33 request models for 35 JSON bodies. Plan 018's sequence and the roadmap name plans 024 and 025.
- 2026-10-06: The first full gate failed one browser test, and the cause was not this plan. Deleting a product on the Products page reached a real Chroma collection in the test's directory. The DELETE answered 200, but after 5.1 s, past the 5 s the page test waits for the dialog to close. It passed when run again. The test now fakes the vector store, as the other browser tests do (its file went from 9.4 s to 4.4 s).
- 2026-10-06: `uv run poe check` passes: 1,861 tests and 11 browser tests. Plan complete.

## Decision log

- 2026-10-06: Same-named sources in the shared knowledge base and a product's are the same bytes. `save_upload` gives different content with an existing name a numbered sibling, in one directory per team, which product uploads share. So the pipeline's evidence keys (`source_name`, `chunk`) are left as they are: two hits with one key are one document, and merging them is right. On a tie in score the product's copy is kept, since the product's hits come first.
- 2026-10-06: A chat's questionnaire always comes from an upload in that chat (`open_questionnaire`). So the chat's product and its questionnaire's are kept equal: an upload takes the chat's product, and choosing one for the chat sets it on the chat's questionnaire too.
- 2026-10-06: General's snapshots changed by one serialised field, so the criterion was reworded rather than kept. Adding `product_id` to `Evidence` adds `"product_id": ""` to every serialised piece of evidence, General's included. The other way was to drop the field from the output when it is empty, with a custom serializer. That would keep the snapshots byte-identical, but the API's evidence would then have the field sometimes and not others. Retrieval, the prompts and the answers for General are unchanged, and the snapshots show it.
- 2026-10-06: A chat's product is named when the chat starts and changed by its own route, not by each message. A multipart form cannot tell General ("") from a field left out, so "change with every message" could not be offered on the upload route. Two rules for one chat would be worse than one. The page (plan 024) calls `POST /api/chat/{id}/product` when the chip changes on an open chat, which also updates the chat lists at once.
