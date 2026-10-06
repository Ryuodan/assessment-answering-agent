# Plan 024: Choosing the product on the pages

**Status:** completed

## Goal

The product a questionnaire or a chat is for is chosen, seen and changed on
the pages (decision 7 of plan 018):

- a coloured chip beside the chat box;
- a selector at the top of the workbench's questionnaire panel;
- a badge on every chat and questionnaire for a product, in the lists.

An answer card also marks a source that came from a product's own knowledge
base, so a reviewer can see what the drafter was told takes precedence.

The routes are plan 023's. This plan changes the pages, the shared card
script, and their browser tests.

## Acceptance criteria

- [x] **Chat page chip.** A coloured chip beside the chat box chooses General or a product.
  - A new chat starts for the chip's product, by a message or an upload.
  - On an open chat, changing the chip changes the chat's product (`POST /api/chat/{id}/product`), and with it its questionnaire's.
  - Opening a chat shows its product.
  - "New conversation" keeps the chip's choice, so a person working on one product all day does not choose it again each time.
- [x] **Chat history.** A chat for a product shows that product's badge in the history.
- [x] **Workbench selector.** A Product selector sits at the top of the questionnaire panel.
  - A questionnaire is opened for the chosen product, and typed or extracted questions are answered for it.
  - With a questionnaire open, changing the selector changes the questionnaire's product (`POST /api/forms/{id}/product`). The page says the answers already written stay.
  - Picking up an earlier questionnaire shows its product.
- [x] **Workbench list.** Questionnaires offered to pick up show their product's badge.
- [x] **Answer cards.** A source from a product's knowledge base carries that product's badge, on the cited chip and in the opened clause.
- [x] **Tests.** Browser tests cover plan 018's main path:
  - creating a product (plan 020's test);
  - choosing it beside the chat box, and the chat starting for it;
  - its badge in the history;
  - changing an open chat back to General;
  - choosing it on the workbench and uploading a questionnaire under it;
  - the badge on the pick-up list;
  - changing it after upload;
  - switching the knowledge-base panel (plan 021's test).
- [x] `uv run poe check` passes.

## Plan

1. `cards.js`: `Cards.setProducts` and `Cards.productBadge`, and the badge on product sources.
2. The chat page: the chip, its colour, sending it with a chat's first message, changing it on an open chat, and the badges in the history.
3. The workbench: the selector, opening and answering under it, changing it on an open questionnaire, and the badges on the pick-up list.
4. Browser tests, docs, and the gate.

## Progress log

- 2026-10-06: Step 1. `cards.js` has `Cards.setProducts` and `Cards.productBadge`, a product's name in its own colour (`.tag.product` in `cards.css`). An answer card puts the badge on a cited source that came from a product's knowledge base, on the chip and in the opened clause.
- 2026-10-06: Step 2, the chat page:
  - The chip sits in the chat box, between the attach button and the text: a dot and a select, tinted with the product's colour.
  - Its product goes with every message and upload. The server reads it only when that message starts the chat (plan 023).
  - Changing it on an open chat calls `POST /api/chat/{id}/product`.
  - Opening a chat, or a reply, shows the chat's product.
  - The history shows each chat's badge.
- 2026-10-06: Step 3, the workbench. A Product row heads the questionnaire panel: a select, a swatch in the product's colour, and a hint saying what is answered from.
  - The product goes with the upload (`POST /api/forms`) and with typed or extracted questions (`/api/assessments/answer-questions`).
  - With a questionnaire open, changing it calls `POST /api/forms/{id}/product`, re-reads the questionnaire, and says the answers already written stay.
  - The pick-up list shows each questionnaire's badge.
- 2026-10-06: Step 4, browser tests in `tests/browser/test_product_choice.py`, both passing on the first run.
  - The chat test:
    - chooses Availo, and checks the chip's colour;
    - uploads a questionnaire;
    - checks the chat and its questionnaire are Availo's, and the badge is in the history;
    - changes back to General, and checks both on the server;
    - checks "New conversation" keeps the chip's choice, and opening a chat shows its own.
  - The workbench test:
    - chooses Availo and uploads;
    - answers, and sees the product badge on the cited source;
    - reloads, and sees the badge on the pick-up list;
    - reopens the questionnaire, which shows Availo, and changes it to General.

  Plan 018's main path is covered by these with plan 020's products page test and plan 021's knowledge-base test.
- 2026-10-06: Screenshots of both pages, light and dark, were looked at before the tests were final. With the chip in the chat box, the example in the box's placeholder wrapped onto a cut-off second line at 1280 px. Its example was shortened to "answer the governance questions briefly", which fits. At 900 px it still wraps, as the longer one did there before.
- 2026-10-06: `uv run poe check` passes: 1,861 tests and 13 browser tests. Plan complete.

## Decision log

- 2026-10-06: The chip sends its product with every message rather than only the first. The server reads it only when the message starts a chat (plan 023's decision), so sending it always costs nothing and keeps the page from having to know which message is the first.
- 2026-10-06: "New conversation" keeps the chip's choice rather than resetting it to General. A person answering one product's questionnaires all day would otherwise choose it every time. The chip is in the box they type in, so the choice is in front of them when they send.
