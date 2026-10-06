# Technical debt

Known problems, each with its impact and the fix. An allow-list entry in a
check must name the item that explains it. When an item is fixed, mark it
**Resolved** with the date and the plan or commit; do not delete it.

Items TD-001 to TD-020 come from the Phase 0 survey (2026-10-05, by Claude).
"Measured" means a command was run; "read" means it comes from reading code
or docs and has not been verified by running anything.

## TD-001: README says embeddings run locally; the code calls a remote endpoint

- **What:** `README.md` (Setup, and the Layout entry for `embeddings.py`) says embeddings "run locally through sentence-transformers" and need no key. `src/embeddings.py` builds `OpenAIEmbeddings` against `settings.embedding_base_url` (default `https://ds.t2.sa/text_embed/v1`); the local variant is commented out at the end of the file. Read.
- **Impact:** a reader or agent believes ingestion works offline and that no policy text leaves the host for embedding.
- **Resolved** 2026-10-06 (Claude, plan 009): the README's Setup says embeddings go to the BGE-M3 service at `EMBEDDING_BASE_URL`, and that indexed text and searches are sent there; the Layout entry is replaced by the generated module table in `docs/generated/layers.md`, which quotes `src/embeddings.py`'s own docstring. The commented-out variant is TD-020, still the user's call.

## TD-002: README "Limits" section is out of date

- **What:** it says filled forms are not written back into the original file (`POST /api/forms/{id}/fill` does exactly that); it says scanned PDFs need OCR turned on (`DOCLING_OCR_AUTO` defaults to true); one bullet ends mid-sentence ("Except when "). Read.
- **Impact:** wrong statements about the product's limits, in the document readers trust most.
- **Resolved** 2026-10-06 (Claude, plan 009): the OCR bullet now says what the code does (`DOCLING_OCR_AUTO` turns OCR on for a PDF with no text layer, `DOCLING_DO_OCR` forces it, the local fallback has none), and the write-back bullet says answers are written into a copy of an .xlsx, .xlsm or .docx questionnaire and never into a PDF. Both read from `src/documents.py`, `src/forms/__init__.py` and the `fill` route.

## TD-003: README API table lists 46 of 70 operations

- **What:** measured: `/openapi.json` has 70 operations; the README table has 46 rows. Missing among others: the memory, preferences and skills routes.
- **Impact:** the API cannot be learned from the docs.
- **Fix:** plan 001 generates `docs/generated/openapi.json`; the README table should link to it instead of listing routes by hand.
- **Partly resolved** 2026-10-05 (plan 001): the generated contract exists and is kept current by a test; the README table is still hand-written.
- **Resolved** 2026-10-06 (Claude, plan 009): the hand-written table is gone; `docs/generated/api.md` lists all 70 operations with the first paragraph of each route's docstring. 17 routes in `src/api.py` have no docstring and show the summary FastAPI derives from the function name ("Admin Add User"); adding docstrings would grow `api.py` past its ceiling, so they come with splitting it (TD-006).

## TD-004: References to the deleted `demo_data` package

- **What:** the demo files were deleted in commit 5da221d, but the README still mentions "bundled English, Arabic and bilingual trial documents", `pyproject.toml` describes a `demo` extra for `python -m demo_data.generate`, and `.claude/settings.json` allows `demo_data.smoke` and macOS-only paths. Read.
- **Impact:** instructions that cannot work; an empty `demo` extra.
- **Fix:** remove the references (small change, no plan needed) once the README is reorganised.
- **Resolved** 2026-10-06 (Claude, plan 009) for the README and `pyproject.toml` (the empty `demo` extra is gone; `uv.lock` changed only in its list of extras). Left: `.claude/settings.json` still allows `demo_data.smoke`, alongside other entries from earlier sessions (macOS `sed -i ''` edits, `/usr/share/fonts`). That file is the agent's own permission list, so it is the user's to prune, not the agent's.

## TD-005: Small configuration doc errors

- **What:** the README configuration table lists `DOCLING_DO_OCR` twice. In `src/config.py` the comment "ME-Central-1 regional endpoint ..." sits above `groq_reasoning_format`, not above `groq_base_url` which it describes. Read.
- **Impact:** minor confusion.
- **Fix:** the generated `docs/generated/settings.md` replaces the hand-written table; move the comment.
- **Partly resolved** 2026-10-05 (plan 001): the comment is above `groq_base_url` again and `docs/generated/settings.md` exists; the README table still lists `DOCLING_DO_OCR` twice.
- **Resolved** 2026-10-06 (Claude, plan 009): the README's table is replaced by a link to `docs/generated/settings.md`. It had also drifted: it gave `TOP_K_GUIDELINES` as 5 and `MAX_EVIDENCE_CHUNKS` as 14, where `src/config.py` has 8 and 38. Its notes for the seven settings that had no comment moved into `src/config.py` as comments, where the generated page reads them.

## TD-006: Eighteen modules in `src/` exceed 400 lines

- **What:** measured 2026-10-05: `api.py` 1987, `agents/assistant.py` 1653, `tools.py` 1403, `chunking.py` 1103, `forms/xlsx.py` 886, `answer_memory.py` 864, `knowledge.py` 836, `service.py` 740, `forms/xlsx_package.py` 705, `identity.py` 644, `export_pdf.py` 643, `config.py` 544, `agents/excel_agent.py` 513, `forms/docx.py` 486, `preferences.py` 479, `store.py` 475, `models.py` 430, `documents.py` 427. The static pages are larger still (`index.html` 3412).
- **Impact:** a module that does many things is hard to change safely and hard to read into an agent's context.
- **Fix:** allow-listed in ARCH-SIZE at their current length so they cannot grow; split them one at a time, behind characterization tests, in later plans.
- **Update** 2026-10-05: after the format commit `4a7c3c6` the count is 19 (`src/graph/nodes.py` went from 399 to 406 lines through formatting alone); the current ceilings are in `harness/arch-allowlist.toml`. Since D-010 (plan 002) `src/config.py` is measured without its Settings class (142 lines) and has left the list: 18 remain.

## TD-007: Import cycles and upward imports

- **What:** read (AST scan of imports, most of them inside functions): `knowledge` and `answer_memory` import each other; `forms.xlsx` and `forms.llm_layout` import each other; `forms.reading` imports `agents.excel_agent`, which imports `forms`; `storage` imports `service`; `rewrite` imports `graph.state` for `order_evidence`; `export_docx` imports `forms.xlsx_package`; `agents.assistant` imports `store`, `service` and `tools` directly.
- **Impact:** no layer can be changed or tested without pulling in the others; function-level imports hide the cycles from readers.
- **Fix:** plan 003 defines layers and an `arch` import rule; existing violations go on its allow-list and are removed one by one.
- **Update** 2026-10-05 (plan 003): under the layers of D-012, two of these are violations, `knowledge` -> `answer_memory` and `storage` -> `service`, allow-listed in ARCH-LAYER. `forms.reading` -> `agents.excel_agent` is now within one layer (answering), as are `rewrite` -> `graph.state`, `export_docx` -> `forms.xlsx_package` and `agents.assistant` -> `store`/`service`/`tools`, which import downwards. The cycle `forms.xlsx` <-> `forms.llm_layout` is inside one layer and is not caught by any rule yet.

## TD-008: No error hierarchy

- **What:** read: eleven unrelated exception classes (`DoclingError`, `UnsupportedDocumentError`, `ExportError`, `FormatError`, `UnsupportedForm`, `AccessDenied`, `NotAllowed`, `PreferenceError`, `NotADocument`, `ToolError`, ...); four separate exception-to-HTTP wrappers in `api.py` (`_guard`, `_tool`, `_atool`, `_preference`) plus 45 direct `HTTPException` uses; 37 `except Exception` blocks in `src/`.
- **Impact:** error codes and user-facing messages are decided case by case; no stable codes for a client or a test to rely on.
- **Fix:** one hierarchy with stable codes and user-safe messages (Phase 2 plan).
- **Partly resolved** 2026-10-05 (plan 004, D-013): one hierarchy in `src/errors.py`, one handler in `src/api.py`, a code on every error response, no internal text in responses on the paths that leaked; ARCH-ERROR guards it. Remaining: the 37 `except Exception` blocks, and Docling's diagnostics (TD-027).

## TD-009: Logging is unstructured, and `config.py` has import-time side effects

- **What:** read: stdlib logging with %-formatted sentences, no event names, no request IDs. `src/config.py` configures tracing (LangSmith, Phoenix) when it is imported and owns `logging.basicConfig`.
- **Impact:** logs cannot be filtered by event or followed through a request; importing settings patches LangChain, which is why `tests/conftest.py` must set `PHOENIX_TRACING` before importing anything.
- **Fix:** structured logs with event names and request IDs, and tracing started from the entry points rather than from config (Phase 2 and 4 plans).
- **Partly resolved** 2026-10-05 (plan 005, D-014): structured logs with event names and request IDs exist (`src/logs.py`, `src/web.py`); `configure_logging` delegates to them. Remaining: tracing is still started when `src/config.py` is imported, and most modules still log prose (TD-028).
- **Update** 2026-10-05 (plan 003): `src/config.py` importing `phoenix` and `openinference` is allow-listed under ARCH-OWNER against this item.

## TD-010: Possibly unused definitions

- **What:** found by name search, so approximate: never referenced: `batches.detail_of`, `documents.load_url_text`, `forms/docx._blocks`, `forms/reading.by_sheet`, `forms/xlsx._has_arabic`, `identity.team_members`, `models.QueryPlan`; referenced only by tests: `identity.is_allowed`.
- **Impact:** dead code misleads readers about what the system does.
- **Fix:** confirm each in the first garbage-collection round, then delete.
- **Resolved** 2026-10-06 (Claude, plan 008): six deleted after reading each; `identity.is_allowed` kept, since its tests pin the allow-list semantics; `documents.load_url_text` is a question for the user (TD-032).

## TD-011: Tests loaded the developer's real `.env`

- **What:** read: `src.config.settings` is built from `.env` at import. The autouse fixtures in `tests/conftest.py` pin storage paths, the allow-list, admin credentials, the reading strategy, tracing and hybrid search, but the other settings (model names, evidence budgets, thresholds, ...) come from whatever `.env` the developer has.
- **Impact:** a test can pass on one machine and fail on another; tests read real configuration, which the harness forbids.
- **Fix:** build test settings from defaults only (no `.env`), then let tests override explicitly.
- **Resolved** 2026-10-06 (plan 006): `tests/conftest.py` sets `ASSESSMENT_ANSWER_ENV_FILE` empty and removes shell variables named like a setting before `src.config` is imported; `tests/test_isolation.py` asserts every setting is its declared default during a test.

## TD-012: Scripts write to the real Chroma index

- **What:** read: `scripts/dev_server.py` (by design, documented in its docstring), `scripts/classify_corpus.py`, `scripts/build_answer_memory.py` and `scripts/index_answer_memory.py` write to the deployment's index; `scripts/selfcheck.py` reads `chroma_db/chroma.sqlite3`.
- **Impact:** a harness run or an agent "just checking" can change the real corpus.
- **Fix:** give each a scratch-directory mode and make it the default where possible; document the ones that must write.

## TD-013: Confidential eval data is in plaintext in git history

- **What:** `eval/house_set.json` (135 question/answer pairs from five named customers' questionnaires) and `eval/answer_memory.json` (698 of the team's answers) are tracked in plaintext in all commits up to and including the start of plan 001. Plan 002 seals them going forward; by the user's decision (2026-10-05) history is not rewritten.
- **Impact:** anyone with a copy of the history has the plaintext. There is no remote today.
- **Fix:** purge them from history (for example with `git filter-repo`) before this repository is ever pushed to a remote. Recorded in `SECURITY.md`.
- **Partly resolved** 2026-10-05 (plan 002): sealed from commit onward (`eval/sealed/`, ARCH-SEALED); the plaintext remains in the history before it.

## TD-014: The evaluation has no clean held-out split

- **What:** read from the README, not verified by running anything: decisions such as "What moved it" and prompt changes were made after runs on the house set, which the README calls held out; there is no separate tuning split; no test checks that benchmark items stay out of prompts; run-to-run noise is measured in places (paired judge passes) but not as a standing procedure.
- **Impact:** reported scores may overstate how the system does on an unseen questionnaire.
- **Fix:** an evaluation plan: dev and held-out splits, noise measured first, contamination test, item-by-item comparison against the last kept version.

## TD-015: Organisation- and machine-specific defaults in the code

- **What:** read: `embedding_base_url` defaults to the organisation's internal host `https://ds.t2.sa/text_embed/v1`; `serve.sh` hard-codes `/home/m.sayed/miniconda3` and a conda env, while the README says the environment is a uv `.venv`.
- **Impact:** the code only runs as intended on one network and one server; two contradictory setup stories.
- **Fix:** move deployment-specific values to `.env` and `.env.example`; make `serve.sh` use the same environment as development.

## TD-016: The browser code has no behavioural tests

- **What:** read: `src/static/index.html` (3412 lines, inline script), `chat.html`, `memory.html`, `preferences.html` and `cards.js` are tested only as served files (`tests/test_pages.py` checks asset fingerprints); nothing exercises their behaviour.
- **Impact:** UI regressions are found by people.
- **Fix:** browser automation tests for the main flows (Phase 4 plan).

## TD-017: The test suite takes 3.5 to 4 minutes, and nobody knows why

- **What:** measured: 242 s and 214 s for 1570 tests. The slowest test takes 7.4 s and the slowest fifteen about 22 s together, so the time is spread across all tests (about 0.13 s each). Not profiled.
- **Impact:** `check` is slow, so it is run less often.
- **Fix:** profile setup and import time (the autouse fixtures rebuild the database per test); consider `pytest-xdist`.

## TD-018: Undefined name in a type annotation

- **What:** measured with ruff F821: `src/prompts.py:184` annotates `list["Evidence"]` without importing `Evidence`. Harmless at runtime (`from __future__ import annotations`), but the annotation refers to nothing.
- **Impact:** wrong for type checkers and readers.
- **Fix:** import `Evidence` under `TYPE_CHECKING`. Part of the mypy baseline until fixed.

## TD-019: Third-party libraries used from several modules

- **What:** read: `python-docx` is imported by `documents`, `export_docx`, `forms.docx` and `service`; `langchain_core` by seven modules.
- **Impact:** a library upgrade or replacement touches many modules; no single owner.
- **Fix:** assign each IO or framework library to one layer and enforce it in `arch` (plan 003).
- **Partly resolved** 2026-10-05 (plan 003): ownership is enforced (ARCH-OWNER); the one remaining exception, `service` importing `docx` for the Word preview, is allow-listed. `langchain_core` is deliberately not owned (D-012).

## TD-020: Commented-out implementation in `src/embeddings.py`

- **What:** read: the second half of the file is a commented-out `HuggingFaceEmbeddings` variant.
- **Impact:** it reads as if local embeddings were supported (see TD-001).
- **Fix:** delete it or turn it into a real, configured option; a product decision for the user.

## TD-021: No test holds "server text is never markup on the page"

- **What:** the README ("Facing a network") says status lines are written as text and that "a test uploads exactly such a name". Searching `tests/` (2026-10-05, Claude) found markup payloads only in `tests/test_document_library.py` (the Word preview) and `tests/test_hostile_input.py` (a search query that must not cause a 500); nothing checks how the pages render a file name or an error.
- **Impact:** a regression to `innerHTML` in a page would pass the suite.
- **Fix:** a browser test (M5) that uploads a file named as markup and asserts it is shown as text; until then, a review rule.
- **Resolved** 2026-10-06 (Claude, plan 011): `tests/browser/test_workbench.py::test_a_file_name_is_shown_as_text_never_as_markup` uploads `<img src=x onerror=...>.txt` and checks the refusal shows the name as text, creates no element and runs no script. Checked against the regression it exists for: with `setStatus` switched to inserting HTML, it fails.

## TD-022: The PDF export reads `WINDIR` directly

- **What:** read: `src/export_pdf.py` builds its font candidate list with `os.environ.get("WINDIR", "C:/Windows")`, outside `src/config.py`. The candidates are hard-coded per operating system; no setting can point the export at a font.
- **Impact:** small: the one environment read outside the settings module (allow-listed in ARCH-ENV), and a deployment without one of the three fonts cannot configure another.
- **Fix:** a `pdf_font_path` setting with the OS candidates as the fallback.

## TD-023: The organisation profile was read from a hard-coded path, in tests too

- **What:** read: `src/organisation.py` loads `PROJECT_ROOT / "data" / "organisation.json"` (`PROFILE_PATH`, bound as a default argument), not a setting. `graph.nodes.draft` and `GET /api/preferences` call `organisation.load()`, and `tests/conftest.py` does not redirect it, so tests that reach either read the developer's real profile (found 2026-10-05 while writing characterization tests, Claude).
- **Impact:** test results can depend on a file in `data/`; the profile cannot be relocated with the rest of the data.
- **Fix:** an `organisation_path` setting under the data directory, redirected by the `isolated_storage` fixture.
- **Resolved** 2026-10-06 (plan 006): `ORGANISATION_PATH` is a setting, redirected per test; a guard fails any test in which a path setting still points into the project, and ARCH-PATH stops modules other than `src/config.py` building paths from `PROJECT_ROOT`.

## TD-024: A bracketed source number in a draft reached the customer's cell

- **What:** found 2026-10-05 by Claude while recording `tests/characterization/snapshots/pipeline/`; not observed in production. The drafting prompt says "Never put a source number in the answer text", but nothing enforces it: `strip_source_markers` removes only the `【1†source】` shape, and `to_cell_text("... 24 hours [1].")` returns the `[1]` unchanged. A model that disobeys writes `[1]` into the answer, the card, the exports and, through `fill`, the customer's file. The pinned behaviour is in `pipeline/grounded-first-draft.json` (the scripted draft contains `[1]`, and so does the final answer).
- **Impact:** a citation that points at nothing, in a document sent to a customer. How often real models do it is unmeasured.
- **Fix (needs a decision):** strip `[n]` markers mechanically where plain text becomes an answer, as `without_reasoning` does for thinking, or count their occurrence in the evaluation first. Not fixed: changing what reaches a customer's file is the user's call.
- **Decision** 2026-10-05, by the user: measure how often, and strip automatically if it is often enough.
- **Measured** 2026-10-05 (Claude), read-only, counts only, no new model calls: answers written since the prompt forbade source numbers (`a9af237`, 2026-08-20). Stored model answers in `data/app.db`: 115 of 2,121 (5.4%) contain `[n]`, 68 of them not held back for review; still present on the latest day recorded (3 of 100 on 2026-09-20). Saved evaluation answers in `eval/results/`: 255 of 2,716 (9.4%). Answers people wrote: 0 of 698 in the answer memory and 0 of 3 written by hand. Three answers recorded as edited by a person but not written by hand carry 2 to 10 markers each, the model's pattern; they were not read. Of 4,928 markers in all, 51 follow a noun, 44 of them "Policy [n]", itself a citation.
- **Resolved** 2026-10-05 (Claude, under the user's rule: 5.4% of stored answers, recurring, never written by people, is often enough): `strip_source_markers` removes `[n]`, `[n, m]` and `[n-m]` unless a document-structure word precedes it ("annex [1]", "section [2]") or it is a Markdown link. It runs where an answer is finalized, exported and written into a cell. Replayed over every stored answer: 615 of 5,886 model-written answers change and 2 keep a bracketed number (a real reference); the answer memory is unchanged. Answers already stored still carry their markers in the database and on the answer card, but not in a filled file or an export, which strip on the way out.

## TD-025: The README gives two sizes for the house set

- **What:** measured 2026-10-05 (Claude): `eval/house_set.json` holds 135 cases. The README's "Evaluation" introduction says it "holds 122 questions"; its "Splitting the team's answers" section says 135.
- **Impact:** a reader cannot tell which number a reported score is over.
- **Fix:** correct it when the README is reorganised (M4); numbers about a dataset should come from the dataset (a generated summary) rather than be typed.
- **Resolved** 2026-10-06 (Claude, plan 009): re-measured on the unlocked file, 135 cases from 5 questionnaires; `docs/measurements/evaluation.md` now says 135. A generated summary was not added: the file is sealed in git, so a generator would only work where it is unlocked.

## TD-026: A questionnaire that was not yours answered 400, everything else 404

- **What:** read 2026-10-05 (Claude, plan 004): `tools._require` raises `ToolError("No questionnaire ...")`, which the API turns into 400, for a questionnaire that does not exist or belongs to a colleague; a missing or colleague's run, conversation, memory entry, skill or document answers 404. `tests/test_private_work.py` pins the 400.
- **Impact:** a client cannot tell "not there" from "bad request" for questionnaires; the README's rule that another person's work "reads as absent" holds in wording but not in status.
- **Fix (needs a decision):** raise `NotFound` from `_require` and update the test, if nothing in the pages depends on the 400.
- **Decision** 2026-10-05, by the user: questionnaires answer 404 like everything else.
- **Resolved** 2026-10-05 (Claude): `tools._require` raises `QuestionnaireNotFound`, a `NotFound` (404, code `questionnaire_not_found`) that is also a `ToolError`, so the chat assistant still reports it to the model as a refusal instead of failing. No page depends on the 400 (checked: only the chat page reads a status, 401). Eight assertions in three test files changed from 400 to 404; the error snapshot changed in exactly that scenario. Missing questions *inside* a questionnaire still answer 400 ("No question 'x' in this questionnaire"); that was not part of the decision.

## TD-027: Docling's diagnostics reach the person who uploaded a file

- **What:** read 2026-10-05 (Claude, plan 004): `DoclingError` messages carry the converter's URL, HTTP status and raw response. With `DOCLING_FALLBACK_LOCAL=false`, `documents.load_text` wraps one into `UnsupportedDocumentError(f"Could not convert '<file>': {exc}")`, and ingestion reports `str(exc)` as the upload's error, which the page shows. `DoclingError` itself stays outside the AppError hierarchy as an internal diagnostic (allow-listed in ARCH-ERROR).
- **Impact:** with the fallback off, a person can see internal host names and the converter's raw output.
- **Fix:** keep the diagnostics in the log, show "Could not convert '<file>'." to the person, and make `DoclingError` an `Unavailable` with a safe message and its details in a separate attribute.

## TD-028: Most modules still log prose sentences

- **What:** measured 2026-10-05: 90 log calls in 24 modules of `src/`, each a %-formatted sentence with no event name. Plan 005 converted `api`, `storage`, `identity` and `config` (22 calls); 23 modules that make a standard-library logger (some never call it) are allow-listed in ARCH-LOG.
- **Impact:** their lines cannot be filtered by event or read as fields; they still carry the request ID, which the logging filter adds to every record.
- **Fix:** convert a module whenever it is next changed (`get_logger`, an event name, keyword fields), then delete its allow-list entry.

## TD-029: A generated team access code was written to the log

- **What:** read 2026-10-05 (Claude): on an upgrade where a team has no access code, `identity.bootstrap` generates one and logs it once at WARNING, in plaintext, so that someone can read it off the log ("Setting it up, and upgrading into it" in the README).
- **Impact:** a credential sits in `logs/server.log`, and in anything that collects logs, for as long as they are kept.
- **Fix (needs a decision):** show it once some other way (the admin page already issues codes; or print it to the console only, not the log file), or accept it as the documented break-glass path. Not changed: it is how an upgrade avoids locking everyone out.
- **Decision** 2026-10-06, by the user: show it on the admin page and on the console.
- **Resolved** 2026-10-06 (Claude): `src/access_codes.py` keeps the generated code in the server's memory only and lists it beside its team on the Access panel (administrators only) until a new code is issued; it writes it to the terminal device itself (`/dev/tty`, `CONOUT$` on Windows), which the `tee` in `serve.sh` does not capture; the log records `identity.access_code_generated` with where it was shown, never the code (`tests/test_access_codes.py`). The README's example of the old log line contained a code, `YEKS-...`; if that was a real one it has been in git since it was written and should be rotated on the Access panel.

## TD-030: Real customer names were in code, tests and the README

- **What:** found 2026-10-05 (Claude, plan 005), counted without reading the passages: one customer's name appears in `src/static/chat.html` (1), `tests/test_private_work.py` (9) and `tests/test_storage.py` (3); another's in `README.md`, `src/formatting.py`, `tests/test_formatting.py` and `tests/test_tools.py` (1 each). Both are customers in the sealed house set.
- **Impact:** the repository says who the customers are, which the sealing of the eval data (plan 002) was meant to keep out of git.
- **Fix (needs a decision):** replace them with invented names (behaviour-neutral in tests and comments), and decide whether a check should refuse them; such a check would need the names without committing them, for example by comparing hashes or by reading the sealed data when it is unlocked.
- **Decision** 2026-10-06, by the user: replace them.
- **Resolved** 2026-10-06 (Claude): replaced by invented names (Contoso, Fabrikam) in the seven places; only string contents and comments changed, and the affected tests pass. Earlier commits still contain the names, as they contain the plaintext eval data (TD-013). No check was added: the user did not ask for one, and it would need the names in some form.

## TD-031: uvicorn's access log writes every raw path and query string (kept, by decision)

- **What:** read 2026-10-05 (Claude): `serve.sh` and `run.sh` start uvicorn with its default access log, which writes `GET /api/documents/uploaded/uploaded/<file name>/file` and `GET /api/search?q=<search text>` lines to `logs/server.log` through uvicorn's own handler, so neither the redaction nor the route-template rule of `src/logs.py` applies. Since plan 005, `http.request` records every request without those details.
- **Impact:** customer file names and search text are kept in the server log.
- **Fix (needs a decision):** start uvicorn with `--no-access-log` in both scripts, relying on `http.request`.
- **Decision** 2026-10-06, by the user: no need to change it. Kept as it is; recorded here so the trade-off stays visible.

## TD-032: URL ingestion exists but nothing reaches it

- **What:** read 2026-10-06 (Claude, plan 008): `documents.load_url_text` asks Docling to fetch and convert a document by URL (`docling_client.convert_url`). No route, tool, script or test calls it; every document enters as an uploaded file.
- **Impact:** about 40 lines that read as a feature the product does not offer. If it were wired up without care, the server's Docling would fetch whatever URL a person gave it.
- **Fix (needs a decision):** delete both functions, or keep them for a planned "add a policy from a link" feature and say so in `documents.py`. Recommended: delete; the git history keeps them.
