# Plan 004: One error hierarchy with stable codes

**Status:** active

## Goal

Every error the application raises on purpose belongs to one hierarchy rooted
in `src/errors.py`. Each class carries a stable code and an HTTP status, and its
message is written to be shown to a person. The API turns all of them into a
response the same way, `{"detail": <message>, "code": <code>}`, in one handler,
instead of four wrapper functions and about 45 hand-built `HTTPException`s
(TD-008). A client or a test can branch on `code`; the UI keeps reading
`detail`; no response carries the text of an internal exception. A check stops
new errors from being invented outside the hierarchy.

## Acceptance criteria

- [ ] Before any change, the error responses of the API's error paths (status and body) are pinned by a characterization test; afterwards their diff is reviewed, and every difference is one this plan intends: an added `code`, and the messages listed below made safe.
- [ ] `src/errors.py` (foundation layer) defines `AppError` and one subclass per HTTP status in use (400, 401, 403, 404, 415, 422, 503); the existing domain errors derive from them with their own codes, keeping their current built-in bases so code that catches `ValueError` still does.
- [ ] `src/api.py` has one handler for `AppError`; the wrappers `_guard`, `_tool`, `_atool`, `_preference` are gone, and `HTTPException` is no longer used. FastAPI's own errors (unknown route, validation) and the catch-all 500 also answer with a `code`.
- [ ] No response includes the text of an internal exception: the document preview, extracted text and preference paths that do today are fixed.
- [ ] ARCH-ERROR fails when a class in `src/` derives from a built-in exception without deriving from `AppError` (private classes excepted), and when `src/` uses `HTTPException`; tests with failing examples.
- [ ] `docs/generated/errors.md` lists every error class with its code, status and meaning, generated from the code; codes are unique (tested).
- [ ] Existing status codes are unchanged (the suite's status assertions still pass), TD-008 updated, `uv run poe check` passes.

## Plan

1. This plan; roadmap.
2. Characterization of error responses, recorded on the current code.
3. `src/errors.py`; re-parent the domain errors.
4. One handler in `src/api.py`; remove the wrappers; replace `HTTPException`; handlers for FastAPI's errors and the 500.
5. Safe messages where internal text leaks.
6. ARCH-ERROR and its tests; `docs/generated/errors.md`.
7. Review the characterization diff, re-record; docs; `check`; close.

## Progress log

- 2026-10-05: Plan written after the user approved plan 004 ("Yes, go ahead"). Survey: 11 exception classes with no common base; four wrappers in `api.py` mapping `ToolError`, `FormatError`, `NotAllowed`, `PreferenceError` to 400 or 422; 45 `HTTPException` sites using 400, 401, 403, 404, 415, 422 and 503; three responses that include an internal exception's text (`api.py` document preview and extracted text, and a `TypeError` in preferences).

## Decision log

- 2026-10-05: Behaviour is preserved where it is pinned, even where it looks inconsistent: a questionnaire that is not yours, or does not exist, answers 400 ("No questionnaire ..."), while a missing run, conversation or memory entry answers 404, and `tests/test_private_work.py` asserts the 400. Recorded as TD-026 for the user rather than changed here. My choice.
- 2026-10-05: The response keeps `detail` and adds `code`, rather than a new shape: the pages read `detail`. My choice.
