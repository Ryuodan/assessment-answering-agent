# Plan 033: The team's feedback, part 3: a step-by-step Workbench, faster review, saved lists, retention

**Status:** active

## Goal

The third round of the team's feedback (plans 029 and 030 had the first two). When it is done:

- **The Workbench is a questionnaire page in steps:**
  1. choose the product and load the file, or type the questions;
  2. check what was found;
  3. answer;
  4. review;
  5. fill and download.

  The step in front of you is open; the others are one line each.
- **Review is faster on the cards.** The cards stay, smaller. They open on "Needs review" and can be worked from the keyboard. Each accept moves to the next held answer, with a count of how many are left. There is no "Approve all".
- **A typed list or a PDF's questions is a questionnaire like a file.** It survives a reload, is listed in "Or pick up", and every card action works on it. There is nothing to fill, so it is downloaded instead.
- **Saved work is not kept for ever.** Each questionnaire can be deleted. Questionnaires, lists and chats not opened for 180 days are deleted automatically, and the pages say until when each is kept.
- **The chat's upload is easy to find.**

The chat stays the home page. The user tests this round before the next.

## The user's decisions

On 2026-11-07, choosing between options with Claude's recommendations:

- **Home:** the chat stays home, as decided on 2026-11-05. The Workbench becomes the step-by-step questionnaire page.
- **Review:** cards, made faster. Not a table.
- **Retention:** a Delete button, and automatic deletion after 180 days unused.
- **Reuse:** no verbatim reuse of earlier answers. Consistency is a later plan of its own, drafted from sources as today.

## Acceptance criteria

The Workbench in steps:

- [x] A step header shows the five steps and where the questionnaire is. A done step folds to one line saying what it holds, for example "Msegat · vendor.xlsx · 120 questions in 3 sheets", and can be opened again.
- [x] Step 1: a product and a file are given in one place. Reading starts when both are there, with no second click. A file dropped before the product is chosen waits for it, and says so. Typing questions is the other way in.
- [x] Step 2: "Found N questions in K sheets" is folded unless something was read from the sheet's shape and is worth checking. The column checks stay.
- [x] Step 3: Answer is one button, in a bar that stays in view and shows the progress. The language and wording options are under "More options".
- [x] Step 4: review on the cards (below).
- [x] Step 5: "Fill and download" is one action. It says how many answers were written and how many were held back, and why. "Write them in anyway" stays. The other downloads, rewording and "Ask another question" are under "More".
- [x] What plans 029 to 032 built still works: reopening on reload, the re-upload warning, the running guard, leaving with unsaved work, product choice, the knowledge-base line, search and citations.

Review:

- [x] The cards are more compact. Sources show as chips that open their clause, and a long question folds to two lines.
- [x] Review opens on "Needs review" when anything needs it.
- [x] Keys while no editor has focus:
  - up and down (or K and J) move between cards;
  - A accepts the card in focus;
  - E edits it;
  - Esc closes the editor.

  After an accept, focus moves to the next held answer, and "N of M reviewed" counts. Keys never act while a person is typing.
- [x] There is no "Approve all".

Saved lists and retention:

- [x] Typed questions and a PDF's or a Word text's questions are saved as a questionnaire with no file to write into. It is reopened by the address, listed in "Or pick up", exported like any other, and its card actions work. Fill says there is no file, and offers the downloads.
- [x] Each questionnaire can be deleted by its owner, after a question that names it. A running questionnaire is refused.
- [x] `RETENTION_DAYS` (default 180; 0 keeps everything) deletes questionnaires, lists and chats not opened for that long, with their answers and files.
  - Opening one counts as using it.
  - Never deleted: the knowledge base, the answer memory, products, people and the event log.
  - Each deletion is an event with counts, never content.
  - A read-only command lists what would go next.
- [x] "Or pick up" and the chat's list say until when each item is kept.

The chat:

- [x] Attaching a questionnaire is a labelled control beside the message box. Dragging a file over the page shows where to drop it. The empty chat says it can take a questionnaire.

All:

- [x] Every change has a test that fails without it. Existing tests that pinned the old layout are changed on purpose and listed. `uv run poe check` passes.
- [x] The docs are updated: ARCHITECTURE.md, decisions, tech-debt, settings and the generated docs.
- [x] A "How to test it yourself" section covers each item.

## Plan

1. Three builders, each on its own branch with disjoint files:
   - A: the Workbench's steps and the cards (`index.html`, `cards.js`, `cards.css`);
   - B: saved lists, deletion and retention on the server;
   - C: the chat's upload (`chat.html`).
2. Merge. A then puts B's lists, Delete and "kept until" into the Workbench, and C or Claude does the same for the chat's list.
3. Review adversarially; fix; run `uv run poe check`; docs and test notes; commit. The user tests.

## Progress log

- 2026-11-07: plan written from the user's decisions above and plan 029's analysis of the feedback (R1, R3, R4, D6, D10, D11).
- 2026-11-07: the three builders' first phase, merged.
  - **A, the Workbench** (`f127eb0`):
    - the five steps, reading on drop, the sticky Answer bar, Fill and download, and More;
    - smaller cards, and the keyboard review (J/K or the arrows, A, E, Esc, "N of M reviewed").
    - 12 browser tests, each failing on the old page. About 30 existing tests changed on purpose, most of them to drop the "Read questions from file" click, which is gone.
  - **B, the server** (`0916a38`, `1783a8a`, `8f112c7`):
    - TD-046 first: `src/migration_steps.py`;
    - room in `tools.py` (1302 to 1151) and `api.py` (1221 to 1179), behaviour-neutral;
    - `POST /api/forms/list` (`src/lists.py`);
    - `DELETE /api/forms/{id}`;
    - `RETENTION_DAYS` with `src/retention.py`, migration 15's `used_at`, `kept_until` on the routes, and `inspect retention`.
    - 46 tests: 19 changes were each undone to show a test fails.
  - **C, the chat** (`4cbf06e`): a labelled Attach control, the drop target, unsupported types refused, and the empty chat's attach area. 9 browser tests.
- 2026-11-07: the second phase, merged.
  - **A** (`27c6a34`):
    - typed lists and PDF/Word text lists are kept through `POST /api/forms/list` when Answer is pressed;
    - their cards say "Ready to use" (`Cards.fileless`);
    - Delete on each "Or pick up" row and on the open questionnaire;
    - "Kept until".
    - 7 browser tests.
  - **C** (`84ecdfd`): the chat's list is dated by last use and says "Kept until"; a chat whose questionnaire was deleted says so when the page can tell. 8 browser tests.
- 2026-11-07, fixed while merging:
  - **Forced language for lists.** A list is answered through the questionnaire's route, which took no language, so "Force English/Arabic" stopped reaching typed questions. `POST /api/forms/{id}/answer` now takes `language`, and the page sends it for a list. A spreadsheet's or Word form's own rows never had it; that is TD-077, for the user to decide.
  - **A flaky chat test**, `test_new_conversation_suggests_the_chat_that_was_open`. It expected "General" after a reload, but opening a chat now counts as using it, and the two chats' last use often fell in the same second. The test now dates them apart and expects the chat just opened.
  - **A flaky run-id test** from plan 031 (`ab2b97a`).
- Recorded: TD-076 (the chat's list on a narrow screen), TD-077.
- 2026-11-07: an adversarial review of plans 033 and 034 together. It checked the timestamps (all `store.utcnow()`), migrations 15 and 16 on an older database, the `[n]` citations, the owner checks and the keyboard review, and found them sound. Fixed, each with a test in `tests/test_review_033_034.py` that fails without the fix:
  - **The same words are not always the same question.** "If yes, please provide details." under Encryption lent its kept searches to the same words under Access control (reproduced), and its earlier answer was put first, marked SAME QUESTION, whatever its score.
    - `formatting.asks_on_its_own`: a follow-up, or anything of fewer than four words, is never matched by its words alone.
    - A kept plan is keyed by the planner too (its prompt and model) and by the question's section.
  - **A chat turn about a questionnaire deleted while it ran was lost**: its save failed on the foreign key (reproduced). `conversations.save` now saves it without the questionnaire.
  - **Kept plans outlived what wrote them.** They are cut to today's `MAX_SEARCH_QUERIES`, a one-line reply is not kept as a plan, and a new planner prompt or model plans again.
  - **The evaluations read and wrote kept plans**, so the house set's wording would have reached `data/app.db`. The `eval` package turns `REUSE_SEARCH_PLANS` off for every runner.
  - **With the reranker's order, the same question's earlier answer was cut.** It is now kept before the cut.
  - **Deleting a questionnaire left its questions' wording in the kept plans.** It takes them now.
  - **The retention pass deleted what was opened after it listed it.** It checks last use again first.
  - Recorded rather than fixed: TD-078, a file removed under a new read of the same file.
- Also while merging: `tools.answer` passes `product_id` only for a product again, as General's call always was. Two tests pinned it.
- 2026-11-07, the full gate's own findings:
  - **The evaluation switch moved out of the package's import.** Turning kept plans off when `eval` was imported leaked into the test suite (`test_every_setting_is_its_declared_default`). Each runner now calls `eval.plan_afresh()` as it starts, and a test checks all six do.
  - **The Workbench searched twice.** A search typed while the drawer's file list loaded ran again when the list arrived, for the same words, scope and file (`test_the_workbench_still_searches_the_knowledge_base`, flaky). It now runs again only if one of those changed.
  - **The keyboard-attach test** listens for the file chooser early. Playwright turns interception on without waiting, and under load Enter reached the page first. A test fix only.

## Decision log

- 2026-11-07, by the user: the four decisions above.

## How to test it yourself

On your local copy. Start the app with `uv run python -m uvicorn src.api:app --reload` and open http://127.0.0.1:8000.

### The Workbench in steps

1. Open the Workbench. A step header shows five steps; step 1, "Choose and load", is open.
2. Drop a spreadsheet before choosing a product: it says it is waiting for the product, and nothing is read. Choose Msegat: it is read at once, with no "Read" button.
3. Step 2 says "Found N questions in K sheets", folded unless something is marked worth checking.
4. Step 3: the Answer button stays at the bottom of the window as you scroll; language and wording are under "More options". Answer: the bar shows the progress.
5. Step 4 opens on "Needs review". Without clicking into a box, press J and K (or the arrow keys on a card) to move, A to accept, E to edit and Esc to close the editor. After A, the next held answer is in focus, and "N of M reviewed" counts. Typing in a box never triggers a key. There is no "Approve all".
6. Step 5: "Fill and download" fills the file and downloads it, saying how many were written and how many held back, and why. Other downloads, rewording and "Ask another question" are under "More".
7. Reload: the questionnaire reopens where it was.

### Lists, Delete and "kept until"

1. With nothing open, choose a product, type two questions, and press Answer. Reload: the list reopens, is listed in "Or pick up" with a "list" mark, and its cards say "Ready to use". There is no Fill; the downloads are under More.
2. Choose "Force English" under More options with an Arabic typed question: the answer is in English.
3. Drop a PDF of questions: it is kept as a list the same way.
4. In "Or pick up", each row says "used <date>" and "Kept until <date>", about 180 days on. Click "Delete" on one: it asks, naming it and its answer count. Cancel keeps it; OK deletes it.
5. Open a questionnaire and use "Delete questionnaire" in its header: after the question, the page goes back to step 1.
6. Try to delete a questionnaire while it is being answered: it is refused, with the reason.

### The chat

1. Beside the message box is "Attach a questionnaire". Tab to it from the message and press Enter: the file chooser opens.
2. Drag a file over the page: a drop target appears; drop it, and it is attached. Drop a PDF: it is refused, with the reason.
3. A new chat's empty page offers attaching above the starters.
4. In the conversation list, each row is dated by when it was last opened, and says "Kept until <date>". Opening one moves it to the top.
5. Delete a chat's questionnaire on the Workbench, then open that chat: it says, once, that its questionnaire was deleted.

### Retention, from the command line

```bash
uv run python -m src.cli inspect retention --days 30
```

It lists what the next 30 days would delete, by kind and owner, with no names. It changes nothing.
