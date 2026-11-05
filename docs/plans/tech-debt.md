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
- **Update** 2026-10-06 (plan 019): `src/store.py` went from 475 to 132 lines, because the migrations moved to `src/migrations.py`, and has left the list: 17 remain. `src/api.py` went from 2036 to 1862, because the sign-in dependencies and the Access panel's routes moved to `src/routes/`. The OpenAPI contract is byte-identical.
- **Update** 2026-10-06 (plans 020 to 024, measured in plan 025): 16 remain. Each plan that needed room moved a cohesive part out first, behind the existing tests, with the contract compared before and after.
  - `models.py` went from 421 to 329 lines (the model-output schemas, to `src/schemas.py`) and has left the list.
  - `api.py` 1862 -> 1296: knowledge, memory and chat routes to `src/routes/`.
  - `agents/assistant.py` 1742 -> 1524: its prompt, to `agents/assistant_prompt.py`.
  - `tools.py` 1487 -> 1376: question selection, to `src/selection.py`.
  - `service.py` 711 -> 614: policy search, to `src/search.py`.
  - `answer_memory.py` 918 -> 836: the disagreement sweep, to `src/memory_sweep.py`.
  - `graph/nodes.py` 406 -> 402.

  The ceilings in `harness/arch-allowlist.toml` were lowered to match, each at the end of its plan.

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
- **Decision** 2026-10-20, by the user: push the repository, history included, to a private GitHub repository so that the server manager can pull it ("don't mind the evaluation, it would be a private repo"). Before the push, Claude scanned the whole history:
  - no API key, private key or password value;
  - no `.env`, database, index or data folder was ever committed;
  - the only key-shaped strings are short test values, far shorter than real keys.

  The plaintext eval data and the old customer names are now readable by whoever has access to the repository. The purge stays possible later, with a force-push.

## TD-014: The evaluation has no clean held-out split

- **What:** read from the README, not verified by running anything: decisions such as "What moved it" and prompt changes were made after runs on the house set, which the README calls held out; there is no separate tuning split; no test checks that benchmark items stay out of prompts; run-to-run noise is measured in places (paired judge passes) but not as a standing procedure.
- **Impact:** reported scores may overstate how the system does on an unseen questionnaire.
- **Fix:** an evaluation plan: dev and held-out splits, noise measured first, contamination test, item-by-item comparison against the last kept version.
- **Partly resolved** 2026-10-06 (Claude, plan 013), measured where noted:
  - The house set is split by questionnaire into `dev` (82 cases) and `final` (53). Every final run needs a reason and is recorded in `eval/final_runs.jsonl`.
  - Both runners check contamination before spending anything. This found one leak (TD-033).
  - Infrastructure failures are counted apart from scores.
  - `scripts/compare_runs.py` compares two runs case by case.
  - `scripts/measure_noise.py` measures noise (plan 014).

  - Noise measured on the dev split (plan 014): two identical runs, 4.0 points of agreement apart on the same 75 cases; the smallest difference worth calling a change is about 5 points.

  Not resolved: all five questionnaires were tuned against before the split existed, so `final` is held out from 2026-10-06 on, not unseen. A clean final split needs questionnaires nobody has scored against yet, which only the team can supply.

## TD-015: Organisation- and machine-specific defaults in the code

- **What:** read: `embedding_base_url` defaults to the organisation's internal host `https://ds.t2.sa/text_embed/v1`; `serve.sh` hard-codes `/home/m.sayed/miniconda3` and a conda env, while the README says the environment is a uv `.venv`.
- **Impact:** the code only runs as intended on one network and one server; two contradictory setup stories.
- **Fix:** move deployment-specific values to `.env` and `.env.example`; make `serve.sh` use the same environment as development.

## TD-016: The browser code has no behavioural tests

- **What:** read: `src/static/index.html` (3412 lines, inline script), `chat.html`, `memory.html`, `preferences.html` and `cards.js` are tested only as served files (`tests/test_pages.py` checks asset fingerprints); nothing exercises their behaviour.
- **Impact:** UI regressions are found by people.
- **Fix:** browser automation tests for the main flows (Phase 4 plan).
- **Partly resolved** 2026-10-06 (plan 011): `tests/browser/` drives the workbench in headless Chromium. It covers sign-in, a refused code, the Access panel, reading, answering and the answer cards, and a markup file name; the gate runs it. The assistant (`chat.html`), the memory and preferences pages are still exercised only as served files.
- **Update** 2026-10-06 (plans 016 to 024): 13 browser tests now.
  - The assistant page: its progress bubble (plan 016); its knowledge-base selector (plan 021); its product chip, history badges and product changes (plan 024).
  - The memory page: its selector and moving an answer (plan 022).
  - The Products page: adding, and deleting behind the typed confirmation (plan 020).
  - The workbench: its Product selector and the product badges (plan 024).

  Still exercised only as a served file: the preferences page.

## TD-017: The test suite takes 3.5 to 4 minutes, and nobody knows why

- **What:** measured: 242 s and 214 s for 1570 tests. The slowest test takes 7.4 s and the slowest fifteen about 22 s together, so the time is spread across all tests (about 0.13 s each). Not profiled.
- **Impact:** `check` is slow, so it is run less often.
- **Fix:** profile setup and import time (the autouse fixtures rebuild the database per test); consider `pytest-xdist`.
- **Measured** 2026-10-06 (Claude, plan 015), with `--durations=25`: 1,803 tests in 319 s, on a machine that was also running another project's evaluation, so treat it as an upper bound. The 25 slowest phases add up to about 50 s:
  - a hostile-workbook test, 9.4 s;
  - the five generated-document staleness tests, about 3.5 s each, because each one rebuilt all five documents;
  - the characterization error snapshots, 3.5 s.

  The other ~270 s is spread across the remaining ~1,780 tests at about 0.15 s each, which points to per-test setup (the autouse fixtures) rather than to slow tests. Fixed in this round: the staleness tests build the documents once per module, and their file now takes 9.1 s instead of about 19 s. Not done: profiling the autouse fixtures, and `pytest-xdist`. That fixture shares process-wide settings, so running in parallel needs care.
- **Measured** 2026-10-06 (plan 025), from the gate runs of plans 023 to 025: 1,861 tests in 355 to 415 s, about 0.2 s each. M7 added 58 tests, and the time per test rose too. The cause is still unprofiled.

## TD-018: Undefined name in a type annotation

- **What:** measured with ruff F821: `src/prompts.py:184` annotates `list["Evidence"]` without importing `Evidence`. Harmless at runtime (`from __future__ import annotations`), but the annotation refers to nothing.
- **Impact:** wrong for type checkers and readers.
- **Fix:** import `Evidence` under `TYPE_CHECKING`. Part of the mypy baseline until fixed.
- **Resolved** 2026-10-06 (Claude, plan 015): imported under `TYPE_CHECKING`; mypy baseline 284 -> 283.

## TD-019: Third-party libraries used from several modules

- **What:** read: `python-docx` is imported by `documents`, `export_docx`, `forms.docx` and `service`; `langchain_core` by seven modules.
- **Impact:** a library upgrade or replacement touches many modules; no single owner.
- **Fix:** assign each IO or framework library to one layer and enforce it in `arch` (plan 003).
- **Partly resolved** 2026-10-05 (plan 003): ownership is enforced (ARCH-OWNER); the one remaining exception, `service` importing `docx` for the Word preview, is allow-listed. `langchain_core` is deliberately not owned (D-012).

## TD-020: Commented-out implementation in `src/embeddings.py`

- **What:** read: the second half of the file is a commented-out `HuggingFaceEmbeddings` variant.
- **Impact:** it reads as if local embeddings were supported (see TD-001).
- **Fix:** delete it or turn it into a real, configured option; a product decision for the user.
- **Decision** 2026-10-06, by the user: remove it, no need for it now.
- **Resolved** 2026-10-06 (Claude, plan 017): the commented-out block is deleted from `src/embeddings.py`, with the README sentence that pointed to it and the `langchain_huggingface` ownership entry in `harness/layers.toml`, which nothing imports any more. `sentence-transformers` stays: the reranker uses it.

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
- **Update** 2026-10-06 (plans 019 to 024): 21 modules are allow-listed. The modules M7 created log events: `products`, the routers, `memory_sweep` and `search`. The three prose lines that moved into the last two with the sweep and the search were converted on the way, as ARCH-LOG requires of a new module.

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
- **Decision** 2026-10-06, by the user: remove it. File uploads to the knowledge base were never affected; they read the saved file (`service.ingest` -> `documents.load_text`).
- **Resolved** 2026-10-06 (Claude): `documents.load_url_text`, `docling_client.convert_url`, its endpoint constant and `_conversion_options`, which only it used (found by `poe gc` after the first deletion), are deleted (40 lines); `documents.py`'s size ceiling was lowered from 424 to 404.

## TD-033: A team reference answer is the drafting prompt's style example

- **What:** found 2026-10-06 (Claude, plan 013) by the contamination check. `src/prompts.py`, in the drafting rules ("Write the position as a fact about us: ..."), gives as its example a sentence that is, for 10 of its 11 words, the security team's own answer to house-set question HOUSE-096, which is in the dev split (first recorded as final; corrected in plan 014). The line was added in commit f76ceab (2026-09-10), and the same rule cites a measurement "on the held-out questionnaires".
- **Impact:** for that one question, the drafter is shown the expected answer, so its score measures copying. Answers to other questions are unaffected, except for whatever the example teaches about style.
- **For now:** HOUSE-096 is in `KNOWN` in `eval/contamination.py`, so every runner leaves it out of the score and says so. Any other leak stops a run.
- **Fix (needs a decision):** replace the example with a sentence that is in no benchmark. This is a prompt change, so it changes answers in principle; the effect should be checked with `scripts/compare_runs.py` against a dev run. Recommended: replace it, then remove the `KNOWN` entry.
- **Decision** 2026-10-06, by the user: replace it.
- **Resolved** 2026-10-06 (Claude, plan 017): the example is now an invented sentence, "Removable media is blocked on company laptops". It was checked first, on normalised text, against every house-set question and answer, every answer-memory pair and the golden set: none contains it. The `KNOWN` entry is gone, so HOUSE-096 is scored again, and `poe eval-contamination` reports 0 leaks. Its effect on answers has not been measured: that needs a paid dev run, compared with `scripts/compare_runs.py --noise` against the plan 014 runs.

## TD-034: An embedding request that stalls is never given up

- **What:** measured 2026-10-06 (Claude, plan 014). During the second noise run, the measurement went silent at 07:38 local time with one connection open to the embedding host (`ds.t2.sa`) and no CPU in use. `src/embeddings.py` builds `OpenAIEmbeddings` with no `timeout`. This entry first said the OpenAI client's defaults would then apply (600 s, 2 retries). That was wrong: langchain passes `timeout=None` through, and the built client's timeout is `None`, so it waits for ever (checked 2026-10-06, plan 017). Only the interactive search (`service.search_knowledge`) bounds its embedding call (10 s).
- **Impact:** if the embedding host stops answering mid-request, the question or the upload waiting on it never finishes, and neither does the person watching it.
- **Fix (needs a decision):** an `EMBEDDING_TIMEOUT` setting (for example 30 s) passed to the client, so a stalled host fails the question fast, as the Docling client already does with `DOCLING_TIMEOUT`. This changes behaviour: a slow but working host would also be cut off.
- **Decision** 2026-10-06, by the user: set a large timeout, because a large file being added to the knowledge base may take a long time; test it and choose a good limit.
- **Resolved** 2026-10-06 (Claude, plan 017): `EMBEDDING_TIMEOUT`, default 300 s, applies to each request; the client's 2 retries stay. Ingestion sends 64 chunks per request, so the limit is per batch, and a large file is many batches, each with its own limit. Measured against the host that day, one request at a time, with synthetic text:
  - a 64-chunk batch of 1,200-character chunks took 37 to 70 s;
  - a one-line query took 0.26 to 34 s.

  300 s is about four times the slowest batch. A stalled host now fails a request after about 15 minutes (three attempts) instead of never. `tests/test_embeddings_client.py` holds a local server that never replies: with the timeout the request fails in about 3 s; without it, the same test was still waiting when a 40 s limit killed it.


## TD-035: Importing a completed questionnaire for a product would file its answers as shared

- **What:** read 2026-10-18 (Claude, plan 026). `service.ingest(path, PRIOR_ANSWER, product_id=...)` indexes the pairs into the product's collection (`own_store`). `answer_memory.adopt_file` then writes their rows with `product_id = ''`, because it takes no product. The rows would be listed under Shared on the memory page while their vectors sit in the product's collection, and forgetting one would unindex it from the shared collection and leave the vector behind.
- **Impact:** none today. No route offers this combination; the command line's `answers` command and the scripts pass no product. The import of the products' data (plan 026, a later step) would reach it.
- **Fix (needs approval, with that import):** give `adopt_file` the product, or have the import record its entries with `answer_memory.record(..., product_id=...)`. Either way, add a test that an imported product answer is listed, indexed and forgotten in its own memory.

## TD-036: Three entries in the live shared answer memory need the team's decision

- **What:** seen 2026-10-18 (Claude, plan 026's survey), read-only.
  - `MEM-0035`: its answer is the name, job title and email address of the person who filled in the questionnaire. That is personal data, and nothing should reuse it as an answer.
  - `MEM-0519`: its answer is a routing note that sends the question to the product and legal teams, not an answer.
  - `MEM-0400`: it says a Data Protection Officer is in place. The team's own 2026 correspondence says, twice, that none is appointed.
- **Impact:** the drafter can quote the first two as if they were T2's answers, and the third may no longer be true.
- **Fix:** the user's call, on the Answer memory page: forget `MEM-0035` and `MEM-0519`, and confirm the DPO status before correcting or forgetting `MEM-0400`. Not done by Claude, because the live memory is the team's data.
- **Resolved** 2026-10-19. The user forgot `MEM-0035` on the memory page. On the user's instruction, Claude forgot `MEM-0519` and `MEM-0400` with `scripts/memory_changes.py`, with the app stopped and a backup of the database and the vector store taken first. The events are recorded under the user's account. Afterwards the rows and their vectors were checked to be gone.

## TD-037: A product chat's direct answers ignore the chat's product

- **What:** found 2026-10-19 by the pre-deploy tests (tracks A-api, B-browser, D1 and D3, each confirmed by a second opinion, two of them offline repros). `answer_directly` in `src/agents/assistant.py` calls `service.answer_questions(..., team_id=user.team_id)` without `product_id`. The same chat's `search_policies` and `open_questionnaire` do pass it (plan 023 wired those two and missed this one).
- **Impact:** in a chat set to a product, a typed "do we do X" question is drafted from the shared knowledge base and memory only. An Ole5 chat answered that there was no documented single sign-on, against Ole5's own facts. In another case it said no policy covered patching, while the product's knowledge base held the Patch Management Policy.
- **Fix (needs approval):** pass `product_id=state.get("product_id", "")`, and add a test that a product chat's direct answer reaches the product's store.
- **Resolved** 2026-10-19 (plan 027): `answer_directly` passes the chat's product. `tests/test_assistant.py::test_a_product_chats_direct_answer_is_drafted_for_its_product` follows it through `service.answer_questions` to the pipeline.

## TD-038: An empty SEED_PRODUCTS uses up the product seeding

- **What:** found 2026-10-19 (tracks C, D2, D3 and E, confirmed). `products.seed()` records the `products` seed on the first start even when `SEED_PRODUCTS` is empty. `identity.bootstrap` seeds `ALLOWED_EMAILS` only when the list is non-empty, which is the behaviour plan 018's decision 6 compared it to.
- **Impact:** an upgraded server whose `.env` has no `SEED_PRODUCTS`, which is every older production `.env`, marks the seed done on its first start. Setting the names afterwards adds nothing, and nothing is logged. The workaround is to add the products on the Products page.
- **Fix (needs approval):** record the seed only when `SEED_PRODUCTS` names something. For a deploy before the fix, set `SEED_PRODUCTS` before the first start.
- **Decision** 2026-10-19, by the user: not changed in code. The server manager starts the new version with a copy of the user's current `.env`, which sets `SEED_PRODUCTS` to the five products (checked, keys only).

## TD-039: Deleting a product leaves its uploaded files on disk and in the document library

- **What:** found 2026-10-19 (tracks A-api, C and D1). A product's knowledge-base files are saved in the team's upload folder with no product marker. After the product is deleted, its vectors are gone, but the files are still listed, opened and downloaded in the document library. The delete dialog says the product's documents are deleted.
- **Impact:** a person who deleted a product to get rid of its material still has the files on the server, listed for the whole team.
- **Fix (a product decision):** keep product uploads in a per-product folder and remove it with the product, or say plainly in the dialog that the files stay.
- **Resolved** 2026-10-19 (plan 027, D-019):
  - Product files live in the product's own folder and are deleted with it. That includes files uploaded before the folder existed, when nothing else uses them.
  - Removing or clearing a product document deletes its file.
  - The library shows the product's badge.
  - The delete dialog is a counted warning.

## TD-040: Product-related behaviour that needs a decision

Found 2026-10-19 by the pre-deploy tests. Each item works as specified, but a user may not expect it:

- **Precedence by label only.** A product's hits come first from the store, but the pipeline re-sorts all evidence by score (`graph/state.py`), so product and shared chunks interleave. The drafter still sees FOR THIS PRODUCT, and every tested answer followed the product, but precedence rests on the label alone.
- **Switching to General before approving.** Approving a product questionnaire's hand-written answer after switching it to General moves product wording into the shared memory. In the test, the sweep then marked a shared answer superseded by it, without asking anyone.
- **Silent forgetting on delete.** Deleting a product forgets its remembered answers, including shared answers that had been moved into it. The dialog does not count them.
- **Member rights.** Any member can upload to or clear a product's knowledge base and move memory entries; only managing products themselves needs a lead.
- **Decisions** 2026-10-19, by the user:
  - Product evidence is marked FOR THIS PRODUCT in the drafter's prompt and shared evidence carries no mark; that label is the precedence.
  - A questionnaire's or chat's product is chosen once and cannot be changed afterwards, which removes the switch-before-approving path.
  - Deleting a product deletes its remembered answers, including those moved in from Shared, and the warning says so.
  - Member rights stay as they are.
- **Resolved** 2026-10-19 (plan 027, D-018, D-019):
  - The product is fixed at creation (409 `product_locked`).
  - The chat's search results are marked FOR THIS PRODUCT as the drafter's are, and tests pin the marking.
  - The delete dialog counts the remembered answers, including those moved in from Shared.
  - A deleted product's work is kept read-only.

## TD-041: Chat page issues found in the browser tests

Found 2026-10-19 (track B, confirmed):

- **Clipped header.** The chat page's top bar does not wrap. Below about 1,018 px wide, the signed-in address and "Dark mode" are clipped.
- **Wide history column.** The history column doubles in width when a conversation has a long title. This predates products.
- **Chip not restored on refusal.** When changing a chat's product is refused (a stale tab offering a deleted product), the chip keeps showing the refused product, and the error is drawn as an assistant turn.
- **Polish.** Product badges are missing on chat source chips, the memory page's "Move to…" menu is full width, and some header links are inconsistent.
- **Resolved** 2026-10-19 (plan 027):
  - Every page's header wraps and has the same links. The chat page gained Sign out.
  - The history column is fixed at 250 px.
  - A deleted product chosen before the first message is refused beside the box, and the chip goes back to General.
  - Chat sources carry the product badge, and the Move menu sits with Edit and Forget.
  - `tests/browser/test_layout.py` checks the header at 1280 and 900 px, and the history width.

## TD-042: Upgrade and operations visibility

Found 2026-10-19 by the upgrade rehearsals:

- **Migrations are invisible.** Schema migrations are not logged. `doctor` does not warn that a migration is pending. A step is not atomic: a crash part-way through would need the backup.
- **Renamed setting.** The renamed `STORAGE_LIMIT_PER_TEAM_MB` (now per person, `STORAGE_LIMIT_PER_USER_MB`) is silently ignored when an old `.env` still has it.
- **Misleading warning.** `doctor`'s warning that `organisation.json` "is created at startup" never clears, because nothing creates it.
- **Log time zone.** Log timestamps moved from local time to UTC without a zone mark.

## TD-043: Assistant and reader behaviour seen once each in testing

Found 2026-10-19; none was repeated or confirmed by a second run:

- **Search loop.** A search-only request in a product chat looped to the recursion limit, using about 250k tokens. It then said answers were "beside this" when none had been written.
- **Invented quotation.** Asked what a product document says, the assistant quoted a paraphrase that stated the opposite of the source.
- **Document opened as a questionnaire.** The assistant once tried to open a knowledge-base document as a questionnaire.
- **Excel agent.** It returned no questions for a small, clean sheet twice in three opens.
- **Resolved** 2026-10-19 (plan 027):
  - **Search loop.** The cause was that the model saw only the first 400 characters of each clause, so the sentence that answered it was cut off. Searches now show whole clauses, up to 1,500 characters, with the product's own marked. A message searches at most three times, and a repeated search is not run again. A model that asks again after a refusal ends the turn, with a reply that says what it searched. A turn's sources are listed once.
  - **Stopped turns.** A turn that stops early says what it did, and never claims answers that were not written. It no longer repeats the previous reply: `_reply_from` scanned the whole history.
  - **Invented quotation.** Words set out as a quotation, in quotation marks or a blockquote, are checked against every source and tool result in the conversation (`src/agents/assistant_quotes.py`). Unfound words make the model write the reply again, once. Words still unfound are shown as a paraphrase, with a note.
  - **Opening a document.** `open_questionnaire` with nothing attached says that it cannot open knowledge-base documents, and names the document when it is one.
  - **Excel reader.**
    - The causes: the rules needed three question rows, so a one- or two-question sheet had no floor under `guarded`; and the agent's round could end on a prose reply.
    - Now the rules read a short numbered form under Question and Answer headings. A guard inside the model call keeps the agent calling tools until every sheet is recorded: one reminder, then an ordinary end, so the second round still runs. Near-empty sheets are not shown to the agent.
    - The workbench says why a file yields no questions.
    - Not changed, as behaviour the user has not asked to change: which reading wins when the agent and the rules find the same number of questions, and short unnumbered sheets (pinned as a reference table).
    - Not yet seen on a live open: how gpt-oss behaves under `tool_choice=required`. Look for `excel_agent.reminded` in the server log.

## TD-044: Nobody can reach a former member's questionnaires and chats

- **What:** found 2026-10-19 by the upgrade rehearsal from the production commit (track D3, check D3-07). Since the 20 September release, questionnaires and chats are private to their owner, by design. Before it, every member and the administrator could list and open all of them. After an upgrade from an earlier version, each is visible only to its owner; anyone else gets 404, and the administrator has no team-wide view.
- **Impact:** nothing is lost, and owners keep their own work. But colleagues who used to share questionnaires lose sight of each other's, and a former member's questionnaires and chats cannot be reached or handed over.
- **Fix (a product decision):** at least a release note for the upgrade. Possibly a read-only or reassign view for administrators.
- **Decision** 2026-10-19, by the user: intended; each person has their own history. Nothing to change beyond the release note.

## TD-045: Work already running when its product is deleted is not stopped

- **What:** read 2026-10-19 (Claude, plan 027's design for read-only work).
  - An answer run, a reword or a chat turn that started before a product was deleted can still save what it finished into the now read-only questionnaire or conversation. Most of that work will have failed, because the product's knowledge base is gone.
  - An approval caught between its check and `answer_memory.record` can leave a memory row for the deleted product.
- **Impact:** small. Nothing reaches the shared memory, because approving is refused. A stray row is never listed or retrieved, but the conflict sweep logs `memory.scan_failed` for it on every pass.
- **Fix:** check the product again before `batches.save_answers` and before `answer_memory.record`.

## TD-046: `src/migrations.py` is at its 400-line limit

- **What:** migration 14 (plan 027) brought the module to exactly 400 lines, the default ARCH-SIZE limit.
- **Impact:** the next migration fails `poe arch`.
- **Fix:** before adding one, move `_team_the_answer_memory` (migration 12's data step) into a module of its own, with no change in behaviour.

## TD-047: With hybrid search on, a superseded remembered answer can come back

- **What:** found 2026-10-19 by plan 027's review. `knowledge._fuse_with_lexical` builds evidence for keyword-only hits from the keyword index and never applies `_still_standing`. The same was already true for imported answers. Since each remembered answer is now its own evidence, the keyword index holds every one, not only the last one indexed.
- **Impact:** none with the default `HYBRID_SEARCH=false`, which is also the local setting. With it on, an answer the sweep marked superseded can reach the drafter.
- **Fix (needs approval):** filter keyword-only prior-answer hits through `_still_standing` before fusion, with a hybrid test. `knowledge.py` is at its size ceiling, so make room first.

## TD-048: Text extracted under older settings stays after its file is deleted

- **What:** read 2026-10-19 (plan 027's review). Extracted text is cached under a key that includes `EXTRACTION_VERSION` and the Docling settings. Deleting a file removes only the cache under today's key.
- **Impact:** text from a deleted product's documents can remain in `data/extracted` when the conversion settings changed while the files existed. The storage sweep has the same limitation.
- **Fix:** key the cache by the file's path and content hash only, or sweep cache entries whose file no longer exists.

## TD-049: The quotation check judges an attribution from word lists

- **What:** plan 027's quotation check (`src/agents/assistant_quotes.py`) has to tell an attribution beside a genuine quotation ("As stated in the Ole5 fact sheet, section 5.3:") from a claim made beside it ("Ole5 follows the Encryption Standard, as stated in ..."). It does this from closed lists, in English and Arabic: attribution words, attribution phrases, place words, and the words of the found documents' names. Three review rounds added forms both ways.
- **Impact:**
  - An attribution worded outside the lists costs one extra model call. If the second reply still uses it, the quotation is marked a paraphrase although it is genuine.
  - A claim made only of listed words still passes. Words outside quotation marks shorter than six words are not checked at all.
- **Fix (needs a decision):** accept the lists, which tests pin both ways (`tests/test_assistant_quotes.py`), and extend them when a form is seen. Or judge an attribution with a model call, at the cost of one call per quoted reply.
- **Seen 2026-10-20 in plan 028's rehearsal.**
  - A reply quoting three policy clauses word for word got the paraphrase note, although its quotation marks stayed. That means the words flagged were not in the reply shown.
  - It was not reproduced offline from the stored reply and the real chunks.
  - Since then, `as_paraphrase` adds the note only when it un-quoted something. Otherwise it logs `assistant.quote_unlocated`, which is the event to look for if this recurs.

## TD-050: More customer and organisation names in code, tests and docs

- **What:** found 2026-10-20 (Claude) by scanning the code archive prepared for the server manager. The scan compared the archive's text with the words of the delivered files' names and of the evaluation files' names. Counts only:
  - one bank's name in 7 files, mostly a questionnaire fixture and its two characterization snapshots;
  - one organisation's name in 8 files, 52 times, used as the example of a person's own answer format, including in the assistant's prompt;
  - three customer questionnaires' names, in 7, 7 and 1 files: comments, docs and test names.

  TD-030 replaced the names found then. These were not on its list.
- **Impact:** the code says who some customers are. That matters for any copy given to someone, and the git history keeps them whatever is done now (as TD-013).
- **Fix:** by the user's TD-030 decision, replace them with invented names. Only string contents, comments and test names change; snapshots are re-recorded and reviewed.
- **Resolved** 2026-10-20 (Claude, plan 027):
  - replaced in 27 files by invented names (Northwind, Tailspin, Woodgrove, Litware, Proseware), and a generic sheet name in one example;
  - the two characterization snapshots changed by the same strings only, and their tests pass;
  - the archive was scanned again and none of the names remain. They are still in the git history (TD-013).

## TD-051: A deleted knowledge base leaves its vector-index folder on disk

- **What:** seen 2026-10-20 in plan 028's rehearsal. Deleting a product dropped its Chroma collection, its embeddings and its rows in `chroma.sqlite3`. Chroma left the collection's HNSW segment folder in `chroma_db/`: 4 files, about 424 KB, vectors and labels only, no text. The local data also holds 14 older unreferenced segment folders, dated 2026-10-05.
- **Impact:** disk space, and vectors of deleted documents remain until removed. The text of those documents is gone.
- **Fix:** after `delete_collection`, remove segment folders that `chroma.sqlite3` no longer references, with the app stopped or inside the delete. Or sweep them in the storage task.

## TD-052: The Workbench's Fill writes held-back answers into the customer's file

- **What:** found 2026-11-05 by the review of the team's feedback, and confirmed in the code. `index.html` sets `$("fillFormBtn").onclick = fillTheForm`. The click event therefore arrives as `includeUnreviewed`, and the request sends `include_unreviewed: true` on every click. The handler dates from 2026-09-07 (`cef554a`), before the gate existed, so every Workbench fill has bypassed the gate since the gate came in on 2026-09-09 (`fd1c01f`). The chat's Fill sends `false`.
- **Impact:**
  - Every file filled from the Workbench also holds the answers the review gate holds back. Those are flagged or low-confidence answers: on the held-out set, 76.2% agreement and 11 of 12 contradictions, against 95.8% and 1 for the answers the gate lets through.
  - The FILE_FILLED event then records `held_back=0`, so the logs do not show it.
- **Fix:** plan 029, approved by the user.
- **Resolved** 2026-11-05 (Claude, plan 029, item 0.1):
  - The button calls `fillTheForm(false)`, and the request opens the gate only for an exact `true`, so a handler that passes an event fails closed.
  - A fill that holds answers back says how many, lists each under "Which, and why" with its reason, and offers "Write them in anyway" behind a confirm that counts them. After that, the first line says how many unconfirmed answers were written.
  - `FILE_FILLED` records the gate's count (`held_back`) in both modes, and `include_unreviewed`. Events from before have no `include_unreviewed` key.
  - `python -m src.cli inspect fills` lists the fills that wrote held answers before the fix (`src/fill_audit.py`). It is certain only for answers unchanged since the fill. What to tell the team, and which sent files to re-check, is the user's decision.
  - Tests: 2 browser tests in `tests/browser/test_workbench.py` (failing on the old page), 3 unit tests in `tests/test_tools.py`, 11 in `tests/test_fill_audit.py`.
  - After the review of Stage 0: "Write them in anyway" counted the last Fill's list, but the server wrote whatever was held at the click, so an approval withdrawn in between went in under "Write 2" and "including 2" (3 were written). The request now names the answers it counted (`unreviewed_ids`), the server writes only those, and the first line says how many went in as the server counted them (`written_anyway`). The audit also lists answers cleared after a fill, and fills of questionnaires no longer on the server, as unknown. Tests: 3 unit and 1 API test, 1 browser test (failing on the old page), 5 in `tests/test_fill_audit.py`.

## TD-053: Withdrawing an approval leaves the answer released

- **What:** found 2026-11-05 by the feedback review. Approving clears `needs_review`, and withdrawing the approval does not put it back. A held answer that was approved and then withdrawn is written to the file as if confident.
  - The "why the score is low" sentence (`confidence_reason`) was lost too.
  - Found by plan 029's design, and reproduced: rewording an approved answer (`revise`) cleared the approval the same way, so the reworded model text was released unreviewed.
- **Fix:** plan 029.
- **Resolved** 2026-11-05 (Claude, plan 029, item 0.2):
  - An approval keeps the flag and reason it replaced, in the answer's stored JSON (`AnsweredQuestion.before_approval`; no column, no migration). Withdrawing restores them; rewording an approved answer withdraws the approval by the same rule (`selection.approve`, `selection.withdraw_approval`).
  - An approval made before the fix kept nothing: withdrawing it applies the review's rule again (any reason, or a score at or under the threshold, unless a person wrote the words).
  - Answers already released by a withdrawal before the fix stay released until somebody edits or approves them. `python -m src.cli inspect fills` lists them (0.1b); they are not repaired.
  - Tests: 7 in `tests/test_tools.py` (5 failing on the old code, 2 pinning what stays), 1 in `tests/test_api_forms.py`, 1 browser test in `tests/browser/test_answer_card.py`.

## TD-054: A fill that held every answer said none of them had a cell to go into

- **What:** found 2026-11-05 by plan 029's design, and reproduced. When every answer that could be written was held back by the review gate, `fill` returned "The answers exist but none of them has a cell to go into -- check the answer column for each sheet in the reading report." `_nothing_written` had no case for held answers. The chat showed it above its own "N held back" line.
- **Impact:** it sent the person to the column mapping when what they had to do was review the answers. After TD-052's fix the Workbench reaches this case often.
- **Resolved** 2026-11-05 (Claude, plan 029, item 0.1): the message is "Nothing was written: N answer(s) are held back until somebody edits or approves them." when answers were kept out. `tests/test_tools.py::test_a_fill_that_held_everything_says_so`.

## TD-055: Saving an empty brief released the model's answer as a person's

- **What:** found 2026-11-05 by plan 029's design, and reproduced. `set_answer(which="brief", text="")` left the model's full answer in place and marked the answer `by_hand`, confidence 1.0. The empty check covered the full answer only.
- **Impact:** emptying the brief editor on a held answer released it unreviewed, as a person's words, at 100%.
- **Resolved** 2026-11-05 (Claude, plan 029, item 0.5): an empty brief is refused (400 `operation_refused`, "A brief answer cannot be empty. To write nothing for this question, use Leave blank."); the stored answer is unchanged. `tests/test_tools.py::test_an_empty_brief_is_refused`, `tests/test_api_forms.py::test_an_empty_brief_is_a_400`.
  - The card does not send an emptied brief: it puts the brief back and says to use Leave blank (`tests/browser/test_answer_card.py::test_emptying_a_brief_is_refused_on_the_card`). The editor of a Brief card now holds the brief, not the full answer.

## TD-056: Rewording an answer a person wrote releases the model's new words unreviewed

- **What:** found 2026-11-05 by plan 029's design, and reproduced. `revise(include_written=True)`, which the chat assistant can ask for, rewords a hand-written answer. The result has `by_hand` false and `confidence_reason` cleared, but keeps the `needs_review=False` and confidence 1.0 that writing by hand set, so the gate lets the model's new words through.
- **Impact:** model text reaches the customer's file as if a person had confirmed it.
- **Fix (needs a decision):** a reworded hand-written answer comes back held, as a reworded approved answer does since plan 029 (0.2).

## TD-057: A brief-only edit marks the whole answer as a person's

- **What:** read 2026-11-05 (plan 029's design). `set_answer(which="brief")` sets `by_hand`, confidence 1.0 and `HAND` on the answer, though the full answer is still the model's.
- **Impact:** switched to Full, the model's full text is written as the person's. Approved in a Full questionnaire, it enters the answer memory under their name.
- **Fix (needs a decision):** record which length a person wrote, or drop the brief's mark when the full answer is written.

## TD-058: A set-aside question's held answer is counted as held back by fill

- **What:** found 2026-11-05 while building plan 029's 0.1, and reproduced. `fill` checks the gate before it checks whether a question is set aside, so a set-aside question whose answer is held appears in `Filled.held_back` and in the `FILE_FILLED` event's `held_back` count. `inspect`'s `held_back` count leaves set-aside questions out, and `docs/design/questionnaires.md` says the fill report does too. Nothing is written for them either way.
- **Impact:** the fill's "N held back" and its reasons can include questions that will never be written, and "Write them in anyway" counts them.
- **Fix (needs approval):** skip set-aside questions before the gate in `fill`, with a test.

## TD-059: Putting back the draft of an approved answer releases it unreviewed

- **What:** found 2026-11-05 while building plan 029's 0.2, and reproduced. `restore_draft` clears `APPROVED` from `confidence_reason` but leaves `needs_review` false, as withdrawing did before TD-053's fix. A flagged answer that was reworded, then approved, then put back to its draft is written as if confident (seen at 0.85 with a reviewer's reason).
- **Impact:** the model's draft reaches the customer's file without a person having confirmed it. Only answers that scored at or above the threshold: a low score is still held.
- **Fix (needs approval):** `restore_draft` withdraws the approval with `selection.withdraw_approval(restored, reworded=True)`, as `revise` does since plan 029. One line, with a test.

## TD-060: A late knowledge-base answer replaced the list for another scope

- **What:** found 2026-11-05 by `poe check` during plan 029, when the existing browser test of removing a product's documents timed out under load. The Workbench loads the shared knowledge base when the page opens and the chosen one when the selector changes, and drew whichever answer came back last. A slow shared answer replaced a product's list while the selector still named the product.
- **Impact:** the list, and since plan 029 the count in "Remove every policy document", could belong to another knowledge base than the one chosen. A "remove" clicked there was sent for the chosen one, and refused. The test failed intermittently.
- **Resolved** 2026-11-05 (Claude, plan 029, with 0.3, whose count depends on it): `loadKnowledge` drops an answer for a scope the selector has left. `tests/browser/test_knowledge_scope.py::test_a_late_answer_for_the_shared_list_does_not_replace_a_products` delays the shared answer and fails on the old page.
- **Still open:** the chat drawer's `loadSources` has the same race. Fix (needs approval): the same check.
