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
- **Fix:** correct the README when it is reorganised into `docs/`; decide whether the commented-out variant (TD-020) stays.

## TD-002: README "Limits" section is out of date

- **What:** it says filled forms are not written back into the original file (`POST /api/forms/{id}/fill` does exactly that); it says scanned PDFs need OCR turned on (`DOCLING_OCR_AUTO` defaults to true); one bullet ends mid-sentence ("Except when "). Read.
- **Impact:** wrong statements about the product's limits, in the document readers trust most.
- **Fix:** rewrite the section during the README reorganisation.

## TD-003: README API table lists 46 of 70 operations

- **What:** measured: `/openapi.json` has 70 operations; the README table has 46 rows. Missing among others: the memory, preferences and skills routes.
- **Impact:** the API cannot be learned from the docs.
- **Fix:** plan 001 generates `docs/generated/openapi.json`; the README table should link to it instead of listing routes by hand.
- **Partly resolved** 2026-10-05 (plan 001): the generated contract exists and is kept current by a test; the README table is still hand-written.

## TD-004: References to the deleted `demo_data` package

- **What:** the demo files were deleted in commit 5da221d, but the README still mentions "bundled English, Arabic and bilingual trial documents", `pyproject.toml` describes a `demo` extra for `python -m demo_data.generate`, and `.claude/settings.json` allows `demo_data.smoke` and macOS-only paths. Read.
- **Impact:** instructions that cannot work; an empty `demo` extra.
- **Fix:** remove the references (small change, no plan needed) once the README is reorganised.

## TD-005: Small configuration doc errors

- **What:** the README configuration table lists `DOCLING_DO_OCR` twice. In `src/config.py` the comment "ME-Central-1 regional endpoint ..." sits above `groq_reasoning_format`, not above `groq_base_url` which it describes. Read.
- **Impact:** minor confusion.
- **Fix:** the generated `docs/generated/settings.md` replaces the hand-written table; move the comment.
- **Partly resolved** 2026-10-05 (plan 001): the comment is above `groq_base_url` again and `docs/generated/settings.md` exists; the README table still lists `DOCLING_DO_OCR` twice.

## TD-006: Eighteen modules in `src/` exceed 400 lines

- **What:** measured 2026-10-05: `api.py` 1987, `agents/assistant.py` 1653, `tools.py` 1403, `chunking.py` 1103, `forms/xlsx.py` 886, `answer_memory.py` 864, `knowledge.py` 836, `service.py` 740, `forms/xlsx_package.py` 705, `identity.py` 644, `export_pdf.py` 643, `config.py` 544, `agents/excel_agent.py` 513, `forms/docx.py` 486, `preferences.py` 479, `store.py` 475, `models.py` 430, `documents.py` 427. The static pages are larger still (`index.html` 3412).
- **Impact:** a module that does many things is hard to change safely and hard to read into an agent's context.
- **Fix:** allow-listed in ARCH-SIZE at their current length so they cannot grow; split them one at a time, behind characterization tests, in later plans.
- **Update** 2026-10-05: after the format commit `4a7c3c6` the count is 19 (`src/graph/nodes.py` went from 399 to 406 lines through formatting alone); the current ceilings are in `harness/arch-allowlist.toml`. Since D-010 (plan 002) `src/config.py` is measured without its Settings class (142 lines) and has left the list: 18 remain.

## TD-007: Import cycles and upward imports

- **What:** read (AST scan of imports, most of them inside functions): `knowledge` and `answer_memory` import each other; `forms.xlsx` and `forms.llm_layout` import each other; `forms.reading` imports `agents.excel_agent`, which imports `forms`; `storage` imports `service`; `rewrite` imports `graph.state` for `order_evidence`; `export_docx` imports `forms.xlsx_package`; `agents.assistant` imports `store`, `service` and `tools` directly.
- **Impact:** no layer can be changed or tested without pulling in the others; function-level imports hide the cycles from readers.
- **Fix:** plan 003 defines layers and an `arch` import rule; existing violations go on its allow-list and are removed one by one.

## TD-008: No error hierarchy

- **What:** read: eleven unrelated exception classes (`DoclingError`, `UnsupportedDocumentError`, `ExportError`, `FormatError`, `UnsupportedForm`, `AccessDenied`, `NotAllowed`, `PreferenceError`, `NotADocument`, `ToolError`, ...); four separate exception-to-HTTP wrappers in `api.py` (`_guard`, `_tool`, `_atool`, `_preference`) plus 45 direct `HTTPException` uses; 37 `except Exception` blocks in `src/`.
- **Impact:** error codes and user-facing messages are decided case by case; no stable codes for a client or a test to rely on.
- **Fix:** one hierarchy with stable codes and user-safe messages (Phase 2 plan).

## TD-009: Logging is unstructured, and `config.py` has import-time side effects

- **What:** read: stdlib logging with %-formatted sentences, no event names, no request IDs. `src/config.py` configures tracing (LangSmith, Phoenix) when it is imported and owns `logging.basicConfig`.
- **Impact:** logs cannot be filtered by event or followed through a request; importing settings patches LangChain, which is why `tests/conftest.py` must set `PHOENIX_TRACING` before importing anything.
- **Fix:** structured logs with event names and request IDs, and tracing started from the entry points rather than from config (Phase 2 and 4 plans).

## TD-010: Possibly unused definitions

- **What:** found by name search, so approximate: never referenced: `batches.detail_of`, `documents.load_url_text`, `forms/docx._blocks`, `forms/reading.by_sheet`, `forms/xlsx._has_arabic`, `identity.team_members`, `models.QueryPlan`; referenced only by tests: `identity.is_allowed`.
- **Impact:** dead code misleads readers about what the system does.
- **Fix:** confirm each in the first garbage-collection round, then delete.

## TD-011: Tests load the developer's real `.env`

- **What:** read: `src.config.settings` is built from `.env` at import. The autouse fixtures in `tests/conftest.py` pin storage paths, the allow-list, admin credentials, the reading strategy, tracing and hybrid search, but the other settings (model names, evidence budgets, thresholds, ...) come from whatever `.env` the developer has.
- **Impact:** a test can pass on one machine and fail on another; tests read real configuration, which the harness forbids.
- **Fix:** build test settings from defaults only (no `.env`), then let tests override explicitly.

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

## TD-020: Commented-out implementation in `src/embeddings.py`

- **What:** read: the second half of the file is a commented-out `HuggingFaceEmbeddings` variant.
- **Impact:** it reads as if local embeddings were supported (see TD-001).
- **Fix:** delete it or turn it into a real, configured option; a product decision for the user.

## TD-021: No test holds "server text is never markup on the page"

- **What:** the README ("Facing a network") says status lines are written as text and that "a test uploads exactly such a name". Searching `tests/` (2026-10-05, Claude) found markup payloads only in `tests/test_document_library.py` (the Word preview) and `tests/test_hostile_input.py` (a search query that must not cause a 500); nothing checks how the pages render a file name or an error.
- **Impact:** a regression to `innerHTML` in a page would pass the suite.
- **Fix:** a browser test (M5) that uploads a file named as markup and asserts it is shown as text; until then, a review rule.

## TD-022: The PDF export reads `WINDIR` directly

- **What:** read: `src/export_pdf.py` builds its font candidate list with `os.environ.get("WINDIR", "C:/Windows")`, outside `src/config.py`. The candidates are hard-coded per operating system; no setting can point the export at a font.
- **Impact:** small: the one environment read outside the settings module (allow-listed in ARCH-ENV), and a deployment without one of the three fonts cannot configure another.
- **Fix:** a `pdf_font_path` setting with the OS candidates as the fallback.

## TD-023: The organisation profile is read from a hard-coded path, in tests too

- **What:** read: `src/organisation.py` loads `PROJECT_ROOT / "data" / "organisation.json"` (`PROFILE_PATH`, bound as a default argument), not a setting. `graph.nodes.draft` and `GET /api/preferences` call `organisation.load()`, and `tests/conftest.py` does not redirect it, so tests that reach either read the developer's real profile (found 2026-10-05 while writing characterization tests, Claude).
- **Impact:** test results can depend on a file in `data/`; the profile cannot be relocated with the rest of the data.
- **Fix:** an `organisation_path` setting under the data directory, redirected by the `isolated_storage` fixture.

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
