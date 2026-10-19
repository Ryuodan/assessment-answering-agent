# Plan 027: The pre-deploy fixes

**Status:** active

## Goal

Yesterday's pre-deploy tests (TD-037 to TD-044) found that the products feature
works and that production upgrades cleanly, but also found problems a user
would meet. The user decided on each one on 2026-10-19. This plan carries out
those decisions, so that the release handed to the server manager:

- answers a product chat's questions from that product;
- removes everything of a product when it is deleted, after a clear warning;
- fixes a questionnaire's or chat's product once chosen;
- stops the assistant's search loop and invented quotations;
- reads short questionnaires reliably;
- has a chat page that fits and behaves.

Importing the products' clean data, and testing the system with it, is the
next plan (028).

## Acceptance criteria

- [ ] **TD-037.** A product chat's direct answers are drafted with the chat's product. A test proves the product reaches the pipeline and its sources carry it.
- [ ] **TD-043, search loop.** One chat message searches at most three times, and a repeated search is not run again. A turn's sources are listed once. The model sees whole clauses, and the product's own are marked FOR THIS PRODUCT. A turn that stops early says what it did, never claims answers that were not written, and never repeats the previous reply.
- [ ] **TD-043, quotations.** Words set out as a quotation that are in no source or tool result make the model write the reply again, once. Any still unfound are shown as a paraphrase, with a note.
- [ ] **TD-043, opening a document.** Asking to open a knowledge-base document as a questionnaire gets a clear answer that says what the tool can and cannot open.
- [ ] **TD-043, Excel reader.** A short questionnaire (one or two numbered questions under Question and Answer headings) is read by the rules. The reading agent cannot end without recording each sheet. The workbench says why when a file yields no questions.
- [ ] **TD-039.** A product's knowledge-base files live in the product's own folder and are deleted with the product, including files uploaded before this change. Removing one document from a product's knowledge base, or clearing it, also deletes its file. The library shows which product a file belongs to.
- [ ] **TD-039, warning.** The delete dialog is a clear warning. It counts what will be deleted: documents and their files, and remembered answers, including those moved in from Shared. It says what happens to the product's questionnaires and chats, and still needs the typed word.
- [ ] **TD-040, fixed product.** A questionnaire's and a chat's product cannot be changed after it is created: the server refuses with 409 `product_locked`. The pages show the product as fixed. The workbench can close a questionnaire to open another file for another product.
- [ ] **TD-040, marking.** Product evidence is marked FOR THIS PRODUCT in the drafter's and reviewer's prompt, shared evidence carries no mark, and tests pin both.
- [ ] **TD-041.** Every page's header wraps without clipping and has the same links. The history column keeps its width. A deleted product chosen before the first message is refused beside the message box, and the chip goes back to General. Chat sources carry the product badge. The memory page's Move menu sits with Edit and Forget.
- [ ] The decisions on TD-038, TD-040's member rights and TD-044 are recorded.
- [ ] `uv run poe check` passes. The tech-debt entries, ARCHITECTURE.md, decisions.md and the generated docs are updated.

## Plan

1. Record the user's decisions (tech-debt).
2. Map each area: code sites, design, tests. Six read-only readers, 2026-10-19.
3. Build in four parallel branches with disjoint files:
   - the assistant and the product lock's server side;
   - the Excel reader;
   - product deletion and its files;
   - the pages.
4. Merge, regenerate the generated docs, and reconcile the size ceilings and layers.
5. Adversarial review of the merged change, then fixes.
6. `uv run poe check`. Update the docs and tech-debt, and commit.

## Progress log

- 2026-10-19: decisions recorded in tech-debt (TD-038 handled through the deploy's `.env`; TD-040's precedence, lock, deletion and member rights; TD-044 intended). Six readers mapped the areas. Each design names its code sites, tests and risks; the outputs stay in the session's scratchpad.

## Decision log

- 2026-10-19, by the user: fix TD-037, TD-039, TD-041 and TD-043, the search loop first. TD-039 also deletes the product's files, and its dialog must be a clear warning that states the consequences. TD-040: mark product evidence only; a product is fixed once chosen; deleting a product deletes its answers, including those moved in from Shared; member rights stay. TD-038: the deploy uses a copy of the user's current `.env`. TD-044: intended.
- 2026-10-19, Claude, on defaults the user did not set (each can be reversed):
  - three searches per chat message;
  - an unverified quotation is asked about once, then shown as a paraphrase;
  - a turn that stops early names the documents it found rather than quoting a "best" clause, because search scores did not track relevance in the tests;
  - the chat's search results carry the FOR THIS PRODUCT mark, as the drafter's do;
  - New chat keeps the last product chosen, and the chip can be changed until the first message;
  - the chat page gets Sign out like the other pages;
  - removing one product document deletes its file. Shared documents keep today's behaviour.
- 2026-10-19, Claude: deliberately not changed here, because they are behaviour changes the user has not asked for:
  - which reading wins when the Excel agent and the rules find the same number of questions;
  - reading short unnumbered sheets.
  Both are recorded as questions in TD-043.
