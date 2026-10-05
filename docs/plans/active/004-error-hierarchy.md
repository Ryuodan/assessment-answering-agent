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
- 2026-10-05: Step 2. `tests/characterization/test_error_responses.py` records 29 error scenarios on the current code (23 in open mode, 6 signed in), stable over two runs. Status codes in use: 400, 401, 403, 404, 415, 422, 500, 503. Two of them confirm the leak concretely: previewing or extracting a corrupt Word file answers with the server's own file path ("Package not found at '...\people\...\uploads\corrupt.docx'").
- 2026-10-05: Step 3. `src/errors.py`; nine domain errors re-parented, keeping their built-in bases (checked: `PreferenceError` and `NotADocument` are still `ValueError`, `ExportError` still `RuntimeError`, messages unchanged). Two of the import insertions landed inside multi-line import blocks and were moved.
- 2026-10-05: Step 4. `src/api.py` rewritten by a syntax-tree-guided script with a reviewed table of class and code per site: 35 raises replaced, the four wrappers and their 26 call sites removed, three try statements unwrapped or trimmed; 68 edits, proven disjoint. Handlers for `AppError`, FastAPI's `HTTPException`, validation errors and the 500, all with a code.
- 2026-10-05: Step 5. The preview and extracted-text paths now say what failed without the exception text (it is still logged); the preferences `TypeError` path answers a fixed sentence.
- 2026-10-05: Step 7 (out of order, to check early). Re-recorded the error snapshots and audited the full diff: 29 codes added, one per scenario; 0 statuses changed; 2 messages changed, the two that leaked a server path. The full suite (before the class move below): 1711 passed, 1 failed, `layers.md` stale because `src.errors` was added to a layer.
- 2026-10-05: The ARCH-SIZE ratchet then failed 7 oversized modules: an import and a `code` line per domain error had grown them past their ceilings. Rather than raising ceilings, the nine domain error classes moved into `src/errors.py`, each module importing its class back (verified to be the same class objects). Net effect: 8 ceilings lowered, 75 lines out of the oversized modules.
- 2026-10-05: Step 6. ARCH-ERROR (`harness/error_rules.py`): one violation found, `DoclingError`, allow-listed against the new TD-027 (Docling diagnostics can reach a person when the local fallback is off). 7 rule tests, 7 hierarchy tests (`tests/test_errors.py`: unique class codes, one status per code, code format, built-in bases kept, the API's shape). `docs/generated/errors.md`: 17 classes and 23 codes named at raise sites, located by function rather than line so ordinary edits do not stale it.
- 2026-10-05: mypy strict caught two mistakes in this plan's code: the moved error classes were imported back implicitly, which strict mode does not treat as part of a module's interface (`tools.ToolError` used from `agents/assistant.py`), now explicit `X as X` re-exports; and the catalogue typed classes as plain `type`. It also found 39 baseline errors gone, mostly with the deleted wrappers: baseline 324 -> 285.
- 2026-10-05: The first full `check` after that failed `arch`: the explicit re-export lines, with a trailing comment, were long enough for the formatter to wrap, which grew `documents.py` and `identity.py` past their ceilings again. The comment went (the `X as X` form says it). `uv run poe check`: all tasks pass, 1727 passed.

## Decision log

- 2026-10-05: Behaviour is preserved where it is pinned, even where it looks inconsistent: a questionnaire that is not yours, or does not exist, answers 400 ("No questionnaire ..."), while a missing run, conversation or memory entry answers 404, and `tests/test_private_work.py` asserts the 400. Recorded as TD-026 for the user rather than changed here. My choice.
- 2026-10-05: The response keeps `detail` and adds `code`, rather than a new shape: the pages read `detail`. My choice.
- 2026-10-05: The domain error classes live in `src/errors.py` rather than beside the code that raises them, so the hierarchy is in one file and the oversized modules shrink instead of growing; alternative rejected: raising seven size ceilings. My choice.
