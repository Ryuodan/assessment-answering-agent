# Plan 035: The open debts fixed, and the system tested from A to Z for use

**Status:** completed 2026-11-07

## Goal

The user's request: "Fix the debts. Test the system from A to Z and make sure it is ready to be used. Then do a cleaning round." The cleaning round is plan 036.

- **TD-076:** on a phone, the chat's conversation list can be closed, and starts closed.
- **TD-077:** "Force English" or "Force Arabic" reaches a spreadsheet's and a Word form's own questions, not only lists.
- **TD-078:** a file being read is not removed by deleting other work made from it.
- **A to Z:** every page and flow is used as a person would, with the real model and the real knowledge base, on a copy of the local data. Anything that does not work is fixed or recorded. The installation's own checks pass.

## Acceptance criteria

- [x] TD-076, TD-077 and TD-078 are fixed, each with a test that fails without the fix.
- [x] The A-to-Z run covers:
  - signing in;
  - the products;
  - the knowledge base: choose, add, view, remove;
  - the Workbench: a file, read, answered, reviewed from the keyboard, filled and downloaded, deleted;
  - a typed list;
  - search;
  - the chat: a question, an attached questionnaire answered, switching conversations;
  - the answer memory, preferences, signing out;
  - `src.cli doctor`, `inspect retention` and `inspect fills`.
- [x] The run uses a copy of `data/` and `chroma_db/`, and a test account made for it on the copy. The hashes of the real `data/app.db` and `chroma_db/chroma.sqlite3` are the same after.
- [x] No page logs a JavaScript error, and the server logs no unhandled error.
- [x] What it finds is fixed, with tests, or recorded in tech-debt for the user.
- [x] `uv run poe check` passes. The docs are updated.

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
- 2026-11-07, before the A-to-Z run: the real `data/app.db` was found at schema version 16. It had been at 14 at 01:25 UTC, read by plan 033/034's reviewer, and changed at 01:35 UTC.
  - **Only the schema changed:** migrations 15 and 16, which add the empty `used_at` columns and the empty `search_plans` table. There are no rows newer than the day before, no events since, and no plan or `used_at` set. It is exactly the upgrade the app makes when it next starts on this code.
  - **What did it was not found.** Not the reviewer (by its own account), and not `poe gen`, `arch`, `types`, `docs` or the test runs of that window: each was run again against a version-14 copy, which none changed. No app server was running.
  - **One way it could happen is closed:** `inspect retention` and `inspect fills`, documented as read-only, read through the app's connection, which upgrades an older database first. They now ask the version on a read-only connection, as `doctor` does, and refuse with a FIX when the database is older (`src/cli.py`, `diagnostics.schema_version`). 4 tests in `tests/test_inspect_older_database.py`; 2 fail on the old CLI.
  - From here, the real data's hashes are taken at the new version, before the A-to-Z run.
- 2026-11-07: the A-to-Z run.
  - **How:** a Playwright script outside the repository started the app in a thread on a copy of `data/` and `chroma_db/` (448 MB), with the real model and embedding service and a test admin account made on the copy. It drove every page as a person would, and collected the pages' JavaScript errors and the server's errors.
  - **First run: 15 of 16 steps passed.** The one failure was the script's, twice over:
    - it typed the product's name where the dialog asks for the word "confirm";
    - its first "Delete" button was Availo's, so it deleted Availo, on the copy. The page asked, as it should, and deleted the product chosen.
  - **Final run, on a fresh copy of the final tree: 20 of 20 steps passed, with 0 page errors and 0 server errors:**
    - signing in, and signing out;
    - a product added, then deleted behind its typed confirmation;
    - a document added to that product's knowledge base, viewed with its text, then removed;
    - the Workbench: a spreadsheet read on drop and answered by the model (4 answers, all "will be written"), one accepted from the keyboard, filled and downloaded (the file had the 4 answers), then deleted;
    - a typed list answered, reopened by its address, then deleted;
    - search: 20 passages, 10 of them earlier answers;
    - the chat: a question answered as a card; the same in Arabic, answered in Arabic and right to left; a questionnaire attached and answered while the person switched to another chat and back; the list resized from the keyboard;
    - the answer memory listed, searched and added to;
    - preferences saved;
    - on a phone, the list closed and the box usable.
  - The hashes of the real `data/app.db` and `chroma_db/chroma.sqlite3` were unchanged after both runs.
  - **The command line:** `doctor` passes everything but Docling, which is not running on this machine. Without it, documents are read by the local fallback, as the run's knowledge-base step did; the server is expected to run Docling. `inspect retention` and `inspect fills` work on the copy: nothing is due in 30 days, and the fills audit lists the 34 fills from before plan 029's fix, as before.
  - **The gate's own findings:**
    - `test_a_long_conversation_title_does_not_widen_the_history` measured the list at 768 px without opening it. It now starts closed there (TD-076), so the test opens it first: changed on purpose.
    - The chat test's turn watcher counted the working bubble and then read it, and the reply could replace it in between. It reads it in one step now (flaky, a test fix only).
- 2026-11-07: tested end to end at the user's request ("Test the system from A to Z and make sure it is ready to be used"): plan 035's A-to-Z run, the real app and model on a copy of the local data, 20 of 20 steps passed, with no page or server errors. Plan complete.

## Decision log

- 2026-11-07, by the user: fix TD-076, TD-077 and TD-078. Test from A to Z, then a cleaning round.
