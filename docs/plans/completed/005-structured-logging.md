# Plan 005: Structured logs and request IDs

**Status:** completed

## Goal

A log line says which event happened, with its facts as named fields, and
which request it belongs to; the same request ID is in the response's
`X-Request-ID` header and in every error body, so "it failed" from a person can
be found in the server log in one search. Logs can be read as text on a laptop
or as one JSON object per line on a server. Nothing secret, and nothing a
customer wrote, is written to them by the request logging. Today log lines are
prose sentences with no event names and no request context (TD-009). The modules
converted here set the pattern; a check stops new prose logging, and the
remaining modules are allow-listed until converted.

## Acceptance criteria

- [x] `src/logs.py` (foundation) provides `get_logger(name)` whose calls take a dotted event name and keyword fields (`log.info("storage.files_removed", person=..., files=3)`), and configures output as `text` or `json` by a new `LOG_FORMAT` setting; records from other loggers still render.
- [x] Every request has an ID: a well-formed incoming `X-Request-ID` is kept, anything else is replaced; it is on every log record made while the request runs, in the response's `X-Request-ID` header, and in every error body (`{"detail", "code", "request_id"}`).
- [x] Each request is logged once (`http.request`: method, route template, status, milliseconds); never the raw path or the query string, which can carry file names and search text.
- [x] Configured secret values (`GROQ_API_KEY`, `LANGSMITH_API_KEY`, `EMBEDDING_API_KEY`, `ADMIN_PASSWORD`, `EVAL_DATA_KEY`) and key-shaped strings are replaced by `[redacted]` in every log line, from any logger (tested).
- [x] `src/api.py`, `src/storage.py`, `src/identity.py` and `src/config.py` log events only; the request middleware and the error handlers live in a new interfaces module, so `src/api.py` shrinks.
- [x] ARCH-LOG fails when a module uses `logging.getLogger` instead of `get_logger` (existing modules allow-listed, TD-028), and when an event name is not a dotted lower-case literal; tests with failing examples.
- [x] The error-response snapshots differ only by the added `request_id`; decision recorded; `uv run poe check` passes.

## Plan

1. This plan; TD-028, TD-029.
2. `src/logs.py` and its tests (rendering, context, redaction).
3. `src/web.py` (interfaces): request-ID middleware, the error handlers moved from `api.py`, `request_id` in error bodies; the snapshot diff reviewed.
4. Convert `api.py`, `storage.py`, `identity.py`, `config.py`; `LOG_FORMAT` setting.
5. ARCH-LOG and its tests; allow-list.
6. Docs; `check`; close.

## Progress log

- 2026-10-05: Plan written after the user approved structured logging as plan 005. Survey: 90 log calls in 24 modules (27 info, 25 warning, 23 exception, 15 debug), all prose with %-arguments; one `basicConfig` in `src/config.py`; no request context. Found: `src/identity.py` writes a generated team access code to the log on upgrade (TD-029, for the user).
- 2026-10-05: Before this plan's work, TD-026 was done as the user decided (commit `3eb8ac6`): questionnaires answer 404 when absent or not yours.
- 2026-10-05: Step 2. `src/logs.py` (event logger, text and JSON formatter, request-ID filter, redaction) with 9 tests. Two suppressions were avoided rather than written: a handler subclass instead of an attribute marker, and `StreamHandler[TextIO]` (generic at runtime) instead of `# type: ignore`.
- 2026-10-05: Step 3. `src/web.py`: a pure ASGI middleware (so background work keeps the ID) and the error handlers, moved out of `src/api.py` (2,101 -> 2,045 lines; ceiling lowered). Handlers take `Exception` and `cast`, again instead of `# type: ignore`. A first check found `X-Request-ID` set twice on error responses (helper and middleware); the middleware now adds it only when missing. That check was run, by mistake, against the real `data/app.db` (a read: it answered 401 from the real user list); later checks used scratch storage. The error snapshots, compared as data with `request_id` removed, are identical to before in all 29 scenarios.
- 2026-10-05: Step 4. `api`, `storage`, `identity` and `config` converted (22 calls). An event's record message is now its rendered form (`event key=value`), so the existing tests that read log text kept passing, except one that looked for the old sentence ("Could not save run"), now `run.save_failed`. `EventLogger.warning` takes `exc_info` so a failed file removal keeps its traceback at warning level. `LOG_FORMAT` setting added. The access code is still logged (TD-029, for the user). 5 tests in `tests/test_web.py`; writing them, I used a real customer's name as a test file name and replaced it before committing; searching for that showed real customer names already in six tracked files (TD-030, for the user).
- 2026-10-05: Step 5. ARCH-LOG (`harness/log_rules.py`): 23 modules still make a standard-library logger (some never call it) and are allow-listed against TD-028; every event call in the converted modules passes. 8 rule tests.
- 2026-10-05: Step 6. D-014; ARCHITECTURE.md and SECURITY.md sections; GP-09 updated, GP-22; TD-009 partly resolved; TD-028 corrected (23 modules, not 20); TD-031 found: uvicorn's own access log, started by `serve.sh` and `run.sh`, records raw paths and queries outside this handler (for the user).
- 2026-10-05: The first full `check` failed 14 tests in `tests/harness/test_arch.py`: their clean tree made a standard-library logger, which ARCH-LOG now flags (1735 passed). The second time a new rule broke another rule's test tree (plan 003 was the first), found only after the four-minute suite each time. Two fixes: the tree uses `get_logger`, and the gate gained a `rules` task that runs the harness's own tests (about 11 s) before the full suite. Also traced the recurring stray newlines in my edit scripts to Git Bash collapsing doubled backslashes in heredocs; scripts with backslashes are now written as files (a note for future sessions, not the repository).
- 2026-10-05: All criteria met; `uv run poe check` passes (1749 passed). Plan moved to `completed/`. For the user: TD-029, TD-030, TD-031.

## Decision log

- 2026-10-05: Standard library only (a logger wrapper, a formatter, a filter, a context variable) rather than adding structlog: the needs are small and a new dependency would be one more thing to own. My choice.
- 2026-10-05: Not every module is converted in this plan; 23 modules are allow-listed (first estimated as 20 with 68 calls, before ARCH-LOG counted modules that make a logger without calling it) and the list may only shrink, as with the other rules. My choice.
- 2026-10-05: The request middleware is pure ASGI rather than Starlette's `BaseHTTPMiddleware`: the ID must survive streamed responses and background tasks, which that class has handled badly in the past. My choice.
- 2026-10-05: A malformed incoming `X-Request-ID` is replaced, not rejected, and only 8 to 64 of `[A-Za-z0-9._-]` are accepted: the ID is echoed into headers, bodies and logs, so it must not carry markup or line breaks. My choice.
- 2026-10-05: The gate runs the harness's own tests as a separate `rules` task before `test`, at the cost of running them twice: a broken rule should be found in seconds, and its verdict should not be trusted until its tests pass. My choice.
