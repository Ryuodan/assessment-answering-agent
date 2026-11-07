# Plan 035: The open debts fixed, and the system tested from A to Z for use

**Status:** active

## Goal

The user's request: "Fix the debts. Test the system from A to Z and make sure it is ready to be used. Then do a cleaning round." The cleaning round is plan 036.

- **TD-076:** on a phone, the chat's conversation list can be closed, and starts closed.
- **TD-077:** "Force English" or "Force Arabic" reaches a spreadsheet's and a Word form's own questions, not only lists.
- **TD-078:** a file being read is not removed by deleting other work made from it.
- **A to Z:** every page and flow is used as a person would, with the real model and the real knowledge base, on a copy of the local data. Anything that does not work is fixed or recorded. The installation's own checks pass.

## Acceptance criteria

- [ ] TD-076, TD-077 and TD-078 are fixed, each with a test that fails without the fix.
- [ ] The A-to-Z run covers:
  - signing in;
  - the products;
  - the knowledge base: choose, add, view, remove;
  - the Workbench: a file, read, answered, reviewed from the keyboard, filled and downloaded, deleted;
  - a typed list;
  - search;
  - the chat: a question, an attached questionnaire answered, switching conversations;
  - the answer memory, preferences, signing out;
  - `src.cli doctor`, `inspect retention` and `inspect fills`.
- [ ] The run uses a copy of `data/` and `chroma_db/`, and a test account made for it on the copy. The hashes of the real `data/app.db` and `chroma_db/chroma.sqlite3` are the same after.
- [ ] No page logs a JavaScript error, and the server logs no unhandled error.
- [ ] What it finds is fixed, with tests, or recorded in tech-debt for the user.
- [ ] `uv run poe check` passes. The docs are updated.

## Plan

1. The three debts, each with its test. (Done; see the log.)
2. A Playwright script, outside the repository, drives the real app on the copy through every flow, with the real model. Read its log, the server's log and the pages' consoles.
3. Fix or record what it finds. Run it again until it is clean.
4. `uv run poe check`, docs, commit.

## Progress log

- 2026-11-07: the debts.
  - **TD-076** (`chat.html`): at 860 px and below the list starts closed. It has its own ✕, Escape closes it, and it closes when a conversation is chosen or a new one started. 4 browser tests (`test_chat_narrow.py`); 3 fail on the old page.
  - **TD-077** (`index.html`): the page sends the forced language for a file's own rows too, and the note under "More options" says so. 2 browser tests (`test_forced_language.py`); the one forcing Arabic fails on the old page.
  - **TD-078** (`src/reading.py`):
    - reading a kept upload holds its name, in `POST /api/forms`, `POST /api/forms/list` and a chat upload's turn;
    - deleting a questionnaire, and a list that found nothing, leave a held file alone.
    - 4 tests (`test_files_being_read.py`); their module does not import without the fix.
  - Also: a "new" test file first overwrote the tracked `tests/test_reading.py`. It was restored from git at once, and the new tests renamed. A memory note now says to check a name is free.

## Decision log

- 2026-11-07, by the user: fix TD-076, TD-077 and TD-078. Test from A to Z, then a cleaning round.
