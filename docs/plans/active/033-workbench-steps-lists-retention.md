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

- [ ] A step header shows the five steps and where the questionnaire is. A done step folds to one line saying what it holds, for example "Msegat · vendor.xlsx · 120 questions in 3 sheets", and can be opened again.
- [ ] Step 1: a product and a file are given in one place. Reading starts when both are there, with no second click. A file dropped before the product is chosen waits for it, and says so. Typing questions is the other way in.
- [ ] Step 2: "Found N questions in K sheets" is folded unless something was read from the sheet's shape and is worth checking. The column checks stay.
- [ ] Step 3: Answer is one button, in a bar that stays in view and shows the progress. The language and wording options are under "More options".
- [ ] Step 4: review on the cards (below).
- [ ] Step 5: "Fill and download" is one action. It says how many answers were written and how many were held back, and why. "Write them in anyway" stays. The other downloads, rewording and "Ask another question" are under "More".
- [ ] What plans 029 to 032 built still works: reopening on reload, the re-upload warning, the running guard, leaving with unsaved work, product choice, the knowledge-base line, search and citations.

Review:

- [ ] The cards are more compact. Sources show as chips that open their clause, and a long question folds to two lines.
- [ ] Review opens on "Needs review" when anything needs it.
- [ ] Keys while no editor has focus:
  - up and down (or K and J) move between cards;
  - A accepts the card in focus;
  - E edits it;
  - Esc closes the editor.

  After an accept, focus moves to the next held answer, and "N of M reviewed" counts. Keys never act while a person is typing.
- [ ] There is no "Approve all".

Saved lists and retention:

- [ ] Typed questions and a PDF's or a Word text's questions are saved as a questionnaire with no file to write into. It is reopened by the address, listed in "Or pick up", exported like any other, and its card actions work. Fill says there is no file, and offers the downloads.
- [ ] Each questionnaire can be deleted by its owner, after a question that names it. A running questionnaire is refused.
- [ ] `RETENTION_DAYS` (default 180; 0 keeps everything) deletes questionnaires, lists and chats not opened for that long, with their answers and files.
  - Opening one counts as using it.
  - Never deleted: the knowledge base, the answer memory, products, people and the event log.
  - Each deletion is an event with counts, never content.
  - A read-only command lists what would go next.
- [ ] "Or pick up" and the chat's list say until when each item is kept.

The chat:

- [ ] Attaching a questionnaire is a labelled control beside the message box. Dragging a file over the page shows where to drop it. The empty chat says it can take a questionnaire.

All:

- [ ] Every change has a test that fails without it. Existing tests that pinned the old layout are changed on purpose and listed. `uv run poe check` passes.
- [ ] The docs are updated: ARCHITECTURE.md, decisions, tech-debt, settings and the generated docs.
- [ ] A "How to test it yourself" section covers each item.

## Plan

1. Three builders, each on its own branch with disjoint files:
   - A: the Workbench's steps and the cards (`index.html`, `cards.js`, `cards.css`);
   - B: saved lists, deletion and retention on the server;
   - C: the chat's upload (`chat.html`).
2. Merge. A then puts B's lists, Delete and "kept until" into the Workbench, and C or Claude does the same for the chat's list.
3. Review adversarially; fix; run `uv run poe check`; docs and test notes; commit. The user tests.

## Progress log

- 2026-11-07: plan written from the user's decisions above and plan 029's analysis of the feedback (R1, R3, R4, D6, D10, D11).

## Decision log

- 2026-11-07, by the user: the four decisions above.
