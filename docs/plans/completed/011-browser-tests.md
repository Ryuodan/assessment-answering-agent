# Plan 011: Browser tests for the main flows

**Status:** completed

## Goal

The pages are 8,000 lines of HTML and JavaScript that no test has opened. A
regression in them is invisible to the suite. For example, TD-021: a switch
from `textContent` to `innerHTML` in a status line would pass every test.

After this plan, the main flows run in headless Chromium against the real app:

- signing in, and being refused;
- reading a questionnaire, answering it, and seeing the answer cards;
- the Access panel showing a code generated at startup (TD-029);
- a file name made of markup shown as text (TD-021).

An agent changing a page gets the same feedback it gets from the API tests.
This is the M5 roadmap's browser item. The user approved Playwright and its
Chromium download on 2026-10-06.

## Acceptance criteria

- [x] `playwright` is in the dev dependency group, with `uv.lock` updated, and `uv run python -m playwright install chromium` is documented as a once-per-machine step.
- [x] `tests/browser/` serves the app in-process, so the suite's fixtures apply: temporary storage, no real `.env`, faked model calls. It drives the page in headless Chromium. If Chromium is missing, the run fails with a FIX line that names the install command.
- [x] The tests cover:
  - signing in with the team code;
  - a wrong code refused on the page;
  - the Access panel showing a generated code (TD-029);
  - a spreadsheet read, answered, and shown as four cards;
  - a markup file name shown as text, with no element created and no script run (TD-021).
- [x] Browser tests carry the `browser` marker. The offline `test` task leaves them out; `poe browser` runs them; `check` includes `browser` as its own task.
- [x] TD-021 is resolved.
- [x] `uv run poe check` passes.

## Plan

1. Add Playwright as a dev dependency, and install Chromium.
2. Write `tests/browser/conftest.py`, with server, browser and page fixtures, and the tests.
3. Add the marker, the `browser` task, and the gate entry.
4. Update the docs, run the gate, and close the plan.

## Progress log

- 2026-10-06: Added `playwright>=1.45` to the dev group; `uv lock` added playwright 1.63.0, greenlet 3.5.6 and pyee 13.0.1. `uv run python -m playwright install chromium` downloaded Chromium, its headless shell and winldd into the user's ms-playwright folder (approved by the user).
- 2026-10-06: `tests/browser/conftest.py` runs uvicorn on a free local port in a thread (one server per test), launches Chromium once per session, and fails a test whose page raised a JavaScript error.
- 2026-10-06: Wrote the five tests. First run, two mistakes of mine: `/` serves the assistant, not the workbench, which lives at `/workbench`; and the extracted questions are editable boxes, so they are found by role and value, not by text. With those fixed, 5 passed in 9.2 s.
- 2026-10-06: Checked the TD-021 test against its regression. `setStatus` was switched to inserting HTML for one run: the test failed, because the `img` became an element and the page raised. The page was then restored, and `git diff` is empty.
- 2026-10-06: `browser` marker registered and left out of `test` by `addopts`; `poe browser` added; the gate runs `browser` after `test` (`tests/harness/test_tasks.py` updated to the new order). TD-021 resolved.
- 2026-10-06: `uv run poe check` passes: 1,792 tests, then the `browser` task with 5 (43.9 s, Chromium start included). Plan complete; milestone M5 done.

## Decision log

- 2026-10-06: The server runs in the test process rather than as a subprocess, so the suite's autouse fixtures (temporary storage, no real `.env`, faked model calls) apply to it without a second configuration path. The cost is that the browser tests share the process's global settings, so they run one at a time. (Claude)
- 2026-10-06: Browser tests are a gate task of their own rather than part of `test`. A machine without Chromium then fails one named task, with the install command as its FIX, and the offline suite still runs everywhere. (Claude)
