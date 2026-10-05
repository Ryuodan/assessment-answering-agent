# Plan 005: Structured logs and request IDs

**Status:** active

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

- [ ] `src/logs.py` (foundation) provides `get_logger(name)` whose calls take a dotted event name and keyword fields (`log.info("storage.files_removed", person=..., files=3)`), and configures output as `text` or `json` by a new `LOG_FORMAT` setting; records from other loggers still render.
- [ ] Every request has an ID: a well-formed incoming `X-Request-ID` is kept, anything else is replaced; it is on every log record made while the request runs, in the response's `X-Request-ID` header, and in every error body (`{"detail", "code", "request_id"}`).
- [ ] Each request is logged once (`http.request`: method, route template, status, milliseconds); never the raw path or the query string, which can carry file names and search text.
- [ ] Configured secret values (`GROQ_API_KEY`, `LANGSMITH_API_KEY`, `EMBEDDING_API_KEY`, `ADMIN_PASSWORD`, `EVAL_DATA_KEY`) and key-shaped strings are replaced by `[redacted]` in every log line, from any logger (tested).
- [ ] `src/api.py`, `src/storage.py`, `src/identity.py` and `src/config.py` log events only; the request middleware and the error handlers live in a new interfaces module, so `src/api.py` shrinks.
- [ ] ARCH-LOG fails when a module uses `logging.getLogger` instead of `get_logger` (existing modules allow-listed, TD-028), and when an event name is not a dotted lower-case literal; tests with failing examples.
- [ ] The error-response snapshots differ only by the added `request_id`; decision recorded; `uv run poe check` passes.

## Plan

1. This plan; TD-028, TD-029.
2. `src/logs.py` and its tests (rendering, context, redaction).
3. `src/web.py` (interfaces): request-ID middleware, the error handlers moved from `api.py`, `request_id` in error bodies; the snapshot diff reviewed.
4. Convert `api.py`, `storage.py`, `identity.py`, `config.py`; `LOG_FORMAT` setting.
5. ARCH-LOG and its tests; allow-list.
6. Docs; `check`; close.

## Progress log

- 2026-10-05: Plan written after the user approved structured logging as plan 005. Survey: 90 log calls in 24 modules (27 info, 25 warning, 23 exception, 15 debug), all prose with %-arguments; one `basicConfig` in `src/config.py`; no request context. Found: `src/identity.py` writes a generated team access code to the log on upgrade (TD-029, for the user).

## Decision log

- 2026-10-05: Standard library only (a logger wrapper, a formatter, a filter, a context variable) rather than adding structlog: the needs are small and a new dependency would be one more thing to own. My choice.
- 2026-10-05: Not every module is converted in this plan; 20 modules with 68 prose calls are allow-listed and the list may only shrink, as with the other rules. My choice.
