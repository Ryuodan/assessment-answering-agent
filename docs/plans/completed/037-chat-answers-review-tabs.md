# Plan 037: The chat's answers panel has the Workbench's review tabs

**Status:** completed 2026-11-07

## Goal

The user's request: "Lets give the assistant answers side-panel the same filters found in the workbench."

The panel beside the chat listed every answer in the file's order, with the set-aside ones at its foot. Finding the few that need a person meant reading all of them. The Workbench has had five tabs since plan 029: Needs review, Will be written, Done by a person, Blank or set aside, and All. The panel gets the same tabs, from the same code, so the same answer is in the same tab on both pages.

## Acceptance criteria

- [x] The panel shows the Workbench's five tabs, each with its count, above the answers. Choosing one shows only its answers.
- [x] The sorting rule and the tabs' drawing live in `cards.js`, shared by both pages. The Workbench draws them from there, unchanged: its 16 browser tests of the review filter pass as before.
- [x] Like the Workbench, the panel opens on "Needs review" when anything needs a person, and on "All" when nothing does. It does the same after a turn that answered, and in another conversation. Otherwise the person's choice stays, across approvals, edits and set-asides.
- [x] "All" is what the panel listed before: the answers, then "Set aside — not written to the file" with its rows. "Blank or set aside" shows the blank answers and the set-aside rows.
- [x] An empty tab says where the answers are, in the Workbench's words.
- [x] The "need review" count above the tabs is the tab's count, as on the Workbench. It used to count only the reviewer's flags, so an unflagged answer under the threshold, held back all the same, was missed.
- [x] A tab chosen from the keyboard keeps the focus.
- [x] Browser tests: `tests/browser/test_chat_review_tabs.py`.
- [x] `uv run poe check` passes.

## Plan

1. Move `REVIEW_TABS`, the bucket rule, the tabs' drawing and the empty-tab sentence from `index.html` into `cards.js`, and their CSS into `cards.css`. The Workbench calls them.
2. The chat's `showAnswers` sorts the answers into the tabs, draws them and keeps the choice. The choice resets on another conversation, another questionnaire, or a reply that brought new answers.
3. Browser tests, the whole browser suite, the gate.

## How to test it yourself

On your local copy. Start the app with `uv run python -m uvicorn src.api:app --reload` and open http://127.0.0.1:8000.

1. In the chat, attach a questionnaire, choose a product, and ask the assistant to answer it.
2. When it has answered, the panel beside the chat shows five tabs with counts. If any answer needs review, "Needs review" is chosen, and only those answers are shown.
3. Approve one: it leaves "Needs review" and is counted under "Done by a person". The tab stays on "Needs review".
4. Choose "All": every answer, then the set-aside ones. Set one aside: "Blank or set aside" counts it.
5. Open the same questionnaire on the Workbench: each tab holds the same answers, with the same counts.

## Progress log

- 2026-11-07: built.
  - `cards.js`: `Cards.reviewBucket`, `Cards.reviewTabs`, `Cards.emptyTab`. `cards.css`: `.review-tabs`.
  - `index.html` calls them; what it shows is unchanged.
  - `chat.html`: `showAnswers` draws the tabs.
  - 6 new browser tests (`test_chat_review_tabs.py`). They and the Workbench's 16 review-filter tests pass.
  - The whole browser suite found one test that expected every card right after a turn (`test_answer_status.py`): it now chooses "All" first, as the new default asks.
  - `uv run poe check`: fmt, lint, types, arch, docs, rules and test passed (2407 tests). Browser: 204 passed. The only failures were plan 038's language-switch tests, written before the pages they test.

## Decision log

- 2026-11-07: the panel opens on "Needs review", as the Workbench does, rather than always on "All". "The same filters" reads as the same behaviour, and that tab is the one a person has work in. (Mine; reversible in one line, `answersTab = counted.review ? "review" : "all"`.)
- 2026-11-07: the "need review" figure above the tabs now counts what the "Needs review" tab holds, as the Workbench's has since plan 029. Otherwise the two numbers above the same answers could differ. (Mine.)
- 2026-11-07: the Workbench's keys (J/K, A, E) and its "N of M reviewed" counter stay on the Workbench. The request was for the filters, and the panel shares the page with the message box, where those letters are typed. (Mine.)
