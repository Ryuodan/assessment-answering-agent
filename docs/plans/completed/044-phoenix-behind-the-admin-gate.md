# Plan 044: Phoenix behind the admin gate, again

**Status:** completed 2026-11-10

## Goal

The user, after the deployment was restarted onto plan 042: "Can we up phoenix for the system", then "Okay let's go ahead and fix it". Phoenix, the trace collector, was running and receiving traces, but its UI at `https://ds.t2.sa/assessment/phoenix/` answered 404. The proxy that published it was a commit made on the server on 2026-09-24 (`91c17a9`, "Publish Phoenix behind the admin gate, and let it ask for a sign-in"). It was not carried into this repository when the project moved to it on 2026-10-20, and the process started before the move kept it in memory until the restart of 2026-11-10. The same move took `serve-phoenix.sh`, which the server's `phoenix` screen session starts the collector with. This plan brings both back, written to today's rules (D-013 errors, D-014 log events, the layers, the routes package). Phoenix holds a copy of every prompt, so the page stays open to administrators only.

## Acceptance criteria

- [x] `/phoenix/` reaches Phoenix for a signed-in administrator, with the app's session cookie not forwarded and Phoenix's cookies not set on the app's origin.
- [x] Anyone else is refused, in open (local) mode too: a browser opening the page gets a sign-in form (401), and a script gets a JSON error with a code (401 `phoenix_sign_in_required`, 403 `admin_required`).
- [x] The sign-in form posts to `/api/auth/session` spelled without the deployment's prefix, as the other pages do (nginx rewrites `/api/` in served HTML).
- [x] Phoenix not running is a 503 `phoenix_unavailable`, not a 500.
- [x] Nothing in a request can change the upstream host.
- [x] `serve-phoenix.sh` starts the collector with its server settings read through `src/config.py`, without sourcing `.env` as shell code.
- [x] Every new setting is in `src/config.py` and `.env.example`. ARCHITECTURE, SECURITY and the tracing doc are updated.
- [x] `uv run poe check` passes, but for the 18 tests that fail on this server at HEAD as well (TD-084). The deployment serves the page again through nginx.

## Plan

1. Settings for Phoenix's server, in `src/config.py` and `.env.example`.
2. `src/phoenix_upstream.py` (integrations): carry one request to Phoenix on loopback and its answer back.
3. `src/routes/phoenix.py` (interfaces): the gate, the sign-in page, the two routes. `src/static/phoenix_sign_in.html`.
4. `scripts/serve_phoenix.py` and `serve-phoenix.sh`.
5. `tests/test_phoenix.py`.
6. Docs, `poe gen`, the gate. Restart the deployment and check the page through nginx.

## How to test it yourself

Open <https://ds.t2.sa/assessment/phoenix/> in a private window: a sign-in form. Sign in as a member: it says the account is not an administrator. Sign in as an administrator: Phoenix, with the project `assessment-answer`. `python -m scripts.serve_phoenix --check` prints the command and settings `serve-phoenix.sh` would start Phoenix with, and starts nothing.

## Progress log

- 2026-11-10: found the cause. `git merge-base --is-ancestor 91c17a9 HEAD` is false; the commit is only on the local branch `backup/main-before-repo-switch-20261020`. Phoenix itself was up: its newest spans were from 08:08 to 08:09 UTC, after the app's restart at 07:37.
- 2026-11-10: done as above. `tests/test_phoenix.py`, 15 tests, pass. The two new error codes and their sentences have Arabic in `ar-server.js` (the browser test of every code's Arabic found them missing; the catalog test then found "Phoenix" left in English, so the Arabic says "the tracing tool"). `src/api.py` is 980 lines, its ceiling lowered from 982. `python -m scripts.serve_phoenix --check` on the deployment's `.env` names the same executable and settings the running collector was started with.
- 2026-11-10: the gate, run on the testing server for the first time (a `.venv` built with `uv sync --inexact`): fmt, lint, types, arch, docs and rules pass. `test` fails 18, all in filling snapshots, the PDF snapshot and two Arabic PDF tests; the same 18 fail on an untouched checkout of `e6d1fa2`, so they are recorded as TD-084, not fixed. `browser`: 292 of 293 passed in the first run (the one failure was the missing Arabic, fixed); a second run lost headless Chromium mid-way (`TargetClosedError`, 240 errors after it), and a run on its own passed 293 of 293 (the server had 6 of its 61 GB free).
- 2026-11-10: the gate on the final tree: fmt, lint, types, arch, docs, rules and browser (293) pass; `test` fails the 18 of TD-084 and nothing else, 2442 passed.
- 2026-11-10: deployed. Through nginx: `/assessment/phoenix/` with no session is the sign-in form (401) and its endpoint reads `/assessment/api/auth/session`, the prefix once; a script gets 401 `phoenix_sign_in_required`. With an administrator's session, on a throwaway database against the real collector: Phoenix's page (200) and its API listing `assessment-answer`, no cookie of Phoenix's passed back. Not signed in as the deployment's own administrator, so as not to write a sign-in to its history.
- 2026-11-10: rebased onto `origin/main`, which had meanwhile taken the number 043 for "the review keeps its place; the answers can go to any column". This plan was not pushed yet, so it became 044; only the roadmap conflicted.

## Decision log

- 2026-11-10: renumbered 043 → 044 on the rebase, since 043 was already pushed. (Mine.)
- 2026-11-10: brought back by rewriting, not cherry-picking. The old code raised `HTTPException` and logged prose, which D-013 and D-014 now forbid, and it lived in `src/api.py`, which is at its size ceiling. (Mine.)
- 2026-11-10: the refusal is returned by a dependency rather than raised as an exception of its own. The page answer needs no new error class and no handler, and a script still gets an `AppError`. (Mine.)
- 2026-11-10: the redirect from `/phoenix` to `/phoenix/` is relative, like `/chat`'s, rather than built from `root_path` as before. Same result under the prefix, one less place that knows it. (Mine.)
- 2026-11-10: `PHOENIX_WORKING_DIR` is a string, empty meaning Phoenix's own default, rather than a path under `data/`. The app never reads it, and a path setting would join the test suite's storage redirection for nothing. (Mine.)
- 2026-11-10: the sign-in page stays in English. It is for administrators, it was English before, and no page catalog covers it. (Mine; the user can overrule it.)
