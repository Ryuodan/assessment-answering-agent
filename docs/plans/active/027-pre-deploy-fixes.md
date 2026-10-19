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
- [ ] **Deleted product's work.** A deleted product's questionnaires and chats stay listed, marked as from a deleted product, and are read-only. Reading them and downloading filled files work; answering, editing, approving and chatting are refused. The pages say so.
- [ ] **Previous-answer collision.** Each remembered answer reaches the drafter as its own evidence, and a shared one no longer hides a product's. A test pins this, and the effect is measured on the dev split before and after.
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
- 2026-10-19: built in four branches, merged into main with no conflicts.
  - **Assistant and lock** (`e24fa93`): new `src/agents/assistant_turn.py`; `assistant.py` 1524 → 1472 lines. On its branch, `check` passed everything except two browser tests, which pinned the old product switching and were rewritten by the pages branch.
  - **Excel reader** (`2386c2e`, `178f6aa`, `f296722`): `check` passed. Its reviewer found that the guard's extra graph node costs each read a third step, so multi-sheet workbooks run out of steps. The reviewer also found that Groq does not enforce `tool_choice=required` for gpt-oss. Both are to be fixed.
  - **Product deletion** (`62f6f5c`): new `src/uploads.py`; `service.py` 614 → 591 lines; `check` passed.
  - **Pages** (`80e8a50`): `check` passed, with 22 browser tests, up from 13.
  - The reviews of three branches were cut off by a usage limit and are re-run on the merged code.
- 2026-10-19: the second round. Reviewers re-read the merged code per area and across areas, and two readers designed the user's new decisions.
  - **Findings fixed:**
    - the Excel guard: no extra graph step, and the reply is checked;
    - the assistant: the search budget ends a turn that keeps searching, and the quotation check covers blockquotes and the whole conversation;
    - legacy product files go on remove and clear;
    - page fixes.
  - **Built:**
    - **read-only deleted products:** the `deleted_products` tombstone (migration 14), 409 `product_deleted`, and a store guard;
    - **the collision fix:** `Evidence.key` includes the entry id, so each remembered answer is its own evidence.
  - Four branches were merged with no conflicts. `check` passes: 2,049 tests and 36 browser tests.
- 2026-10-19: the collision measurement, run A (before the fix, commit `3f6d505`).
  - **The copy:** the dev split ran on a copy of the index. In the copy, the 694 shared answers were re-filed as the app files remembered answers ("Answer memory", chunk 0, same entry id and text, no re-embedding). The live index has no such entries, so a run on it could not show the defect.
  - **Result:** 82 cases graded; agreement 81.7%; verdicts: 59 broader, 13 contradicts, 6 same, 3 narrower, 1 declined.
  - **Live data:** the hashes of `chroma_db/chroma.sqlite3` and `data/app.db` were unchanged before and after.
- 2026-10-19: run B (with the fix, commit `92d4b7e`), on the same copy.
  - **Result:** 82 graded, 0 failed; agreement 84.1% (81.7% before). Where the memory had been asked something similar: 91.2% (87.5%). Where it had not: 82.4% (80.3%). Verdicts: 60 broader, 11 contradicts (13 before), 6 same, 5 narrower.
  - **Item by item** (`scripts.compare_runs` against the plan 014 noise): 3 better, 0 worse, 74 the same, 5 moved within noise.
  - **Reading:** the +2.4 points is below the 4.9 points that plan 014 measured as the smallest change between two single runs that means anything. The run shows no harm and a consistent direction, not a proven gain. The mechanism is proven by the tests: `tests/test_previous_answers.py` and the merge and fusion tests.
  - **Live data:** hashes unchanged again.

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
- 2026-10-19, by the user, answering Claude's questions:
  - A deleted product's questionnaires and chats are kept but become read-only. People can read them and download filled files, but cannot answer, edit, approve or chat in them. Rejected: keeping them usable as General, which would let a later approval file the product's wording as a shared answer; and deleting them.
  - The previous-answer collision is to be fixed and measured. Today every remembered answer is indexed as "Answer memory", chunk 0, and evidence is de-duplicated by name and chunk, so only one reaches the drafter per question.
  - The 49 cleaned answer pairs go into production's memory typed by hand on the memory page, not through an import feature or a server script.
  - The clean data is imported into a copy of the local data for testing. Production gets it after the deploy, and the local data is unchanged.
- 2026-10-19, Claude, on further defaults from the review rounds (each can be reversed):
  - **The search budget.** Searches and direct answers share one budget of three per message. A single model step that asks for more is answered once: three run and the rest are refused. A refused call in a later step ends the turn. A stopped turn relays the answers it drafted, word for word.
  - **Attributions.** A quotation's attribution counts as a citation when every word in it names a document found, says where (a section, a page, a number beside either), or only says that a document said it, in English or Arabic. "set", "put" and "لما" count only in "set out", "puts it" and "لما ورد/جاء". A `>` before a number is "more than", not a quotation.
  - **Exports.** The Word and PDF exports list a citation name once, even when two remembered answers share it. The answer card and the chat list each one.
- 2026-10-19, Claude: deliberately not changed here, because they are behaviour changes the user has not asked for:
  - which reading wins when the Excel agent and the rules find the same number of questions;
  - reading short unnumbered sheets.
  Both are recorded as questions in TD-043.
