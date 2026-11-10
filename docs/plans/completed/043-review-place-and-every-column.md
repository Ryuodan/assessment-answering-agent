# Plan 043: The review keeps its place; the answers can go to any column

**Status:** completed 2026-11-10

## Goal

The user's two problems after the deploy: "in the assistant answers review panel, when a user approve an answer the page scrolls to the top automatically which is quite annoying to deal with. The second problem is that in Workbench "Check what was found" I can not pick a specific column to be written as the answers, it only offer one or two columns and they are gone once I choose an option for them. I needed to test because a questionnaire file only wrote status of the answer and not the answers themselves due to mislabeled columns by the agent. But I do not want to change is because it might start to fail other files, so we need to at least provide a workaround in workbench."

## Acceptance criteria

- [x] Approving, or anything else that draws the chat's answers again, leaves the panel where it was scrolled. Choosing another tab starts at its top.
- [x] "Write to another column", under "Where the answers will be written", lists every column beside the questions: its letter, its heading, a value from it, and a picker. The blank column after the last is listed too.
- [x] The question and number columns are shown, never offered: "the questions — never written".
- [x] A column given a role, or set to "do not write here", stays in the list, and the list stays open for the next choice.
- [x] Nothing changes how a file is read: detection, the agent and other files are as before. The choice goes through the existing `POST /columns`.
- [x] English and Arabic, light and dark, a phone's width. `uv run poe check` passes.

## Plan

1. The chat: keep the panel's scroll across a redraw of the same questionnaire and tab.
2. `src/sheet_columns.py` and `GET /api/forms/{id}/columns/every`; the Workbench's list; tests; docs; the gate.

## How to test it yourself

1. Chat: open a questionnaire with many answers, scroll the answers panel down, and approve a card. The panel stays where it was.
2. Workbench: open a spreadsheet and expand "Check what was found". Under "Where the answers will be written", open "Write to another column". Every column is listed with its heading. Choose "the written answer" for the column you want; the line above changes to it, and the list stays open. Fill the file: the answers are in that column.

## Progress log

- 2026-11-10: the jump happened only once the conversation list had been given a width of its own (dragging its edge). The width is kept, and each redraw of the answers re-checked it while the panel was empty; measuring the page then put the empty panel back at its top. The tests had never dragged the list, so none saw it. The panel's place is now kept whatever measures the page. `tests/browser/test_review_keeps_its_place.py` fails without the fix.
- 2026-11-10: the column list is read from the file only when opened, so the Workbench's redraws do not read the workbook each time.

## Decision log

- 2026-11-10: a list of every column under the existing one, rather than changing the existing one: the columns that will be written stay a short line, and the full list is there when it is wrong. (Mine.)
- 2026-11-10: the question and number columns are shown but not offered, in the page only. The server accepts them as it did, since the assistant's tool uses the same route. (Mine.)
- 2026-11-10: a column's heading is the nearest cell above the first question, up to three rows up; a value from beside the questions is shown too, for a file with no headings. (Mine.)
