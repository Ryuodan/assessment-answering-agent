# Plan 010: Diagnostics on the command line

**Status:** completed

## Goal

An operator, or an agent, can answer two questions without reading code or
the database by hand.

First: can this installation run? This covers the interpreter in use, the env
file it read, whether the secrets it needs are set (never their values),
storage, the database, and optionally the remote services.

Second: what happened to a request? An error response carries a request ID,
and one command prints every line of the server log that belongs to that
request.

Both commands are read-only. Each failure carries a FIX line, in the same form
as the harness's own checks. This is the M5 roadmap's diagnostics item. The
README's "check which interpreter you are on" advice becomes a check.

## Acceptance criteria

- [x] `python -m src.cli doctor` reports, one line each, with ok, warn or fail:
  - the interpreter;
  - the env file;
  - `GROQ_API_KEY` and `EVAL_DATA_KEY`, as set or not set;
  - the six storage paths;
  - the database's schema version and counts.

  A failing check also prints a FIX line, and any failure makes the exit
  code 1. `--json` prints one object per check.
- [x] `doctor --network` makes one GET to Groq, the embedding service and Docling, with a 5-second timeout, and reports the status or the error class.
- [x] `python -m src.cli inspect request <id>` prints the server log's lines carrying that request ID, in the text and the JSON log formats. It exits 1 with a FIX line when the log or the ID is not found. The log's location is a setting, `SERVER_LOG_PATH`.
- [x] Nothing the commands do writes. A test runs `doctor` over a temporary tree and finds it unchanged, and the database is opened read-only. No secret value appears in any output; a test checks this.
- [x] `cli.py`'s coverage is above 0%: the new commands are tested through `cli.main(argv)`.
- [x] `uv run poe check` passes.

## Plan

1. Add `src/diagnostics.py` (integrations layer): `Check`, `doctor()`, `network(client)`, `request_lines()`.
2. In `src/config.py`, add `env_file_in_use()`, `project_venv()` and the setting `server_log_path`. Add it to `.env.example`, and redirect it in the test fixture.
3. In `src/cli.py`, add the `doctor` and `inspect request` commands; `main(argv)` takes its arguments for tests.
4. Write the tests, update ARCHITECTURE and CLAUDE.md, run the gate, and close the plan.

## Progress log

- 2026-10-06: `src/diagnostics.py` added (integrations layer: it owns the SQLite and HTTP probes it makes). In `src/config.py`, `env_file_in_use()`, `project_venv()` and the setting `server_log_path` were added; the setting is in `.env.example` and is redirected by the test fixture, whose guard demanded it. `src/cli.py` gained `doctor` and `inspect request`, and `main(argv)` now takes its arguments.
- 2026-10-06: `tests/test_diagnostics.py` passes (9 tests). They cover: nothing written; missing storage as a warning; a database description; a missing key failing with a FIX line; no secret in the output; network probes through a mock transport (401, 200, connection refused); both log formats; and the CLI's exit codes, JSON, and missing log or ID.
- 2026-10-06: Run against this machine's real installation (read-only): 11 checks, 0 failed. Schema version 10, 1 team, 2 users, 88 questionnaires, 5 runs. `--network` was not run here: it sends the configured keys to their hosts, which nobody asked for.
- 2026-10-06: `uv run poe check` passes (1,792 tests). Plan complete.

## Decision log

- 2026-10-06: The network checks run only when asked for (`--network`). They send the configured keys to their hosts, as the app itself does; a default `doctor` contacts nothing. (Claude)
- 2026-10-06: Chroma is not opened. One process owns the Chroma directory (README, Limits), so opening it beside a running server can fail it; `doctor` reports the directory's size instead. (Claude)
