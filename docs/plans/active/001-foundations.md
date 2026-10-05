# Plan 001: Foundations

**Status:** active

## Goal

One command, `uv run poe check`, decides whether a change is safe: it runs
formatting, lint, types, architecture rules, docs checks and tests, and every
failure says what is wrong, where (file:line), and how to fix it. Around it, a
short agent map (`CLAUDE.md`), a `docs/` layout that is checked mechanically,
generated docs that cannot go stale silently, and characterization tests that
pin what the important paths do today, so that the refactors of later plans
(layers, error hierarchy, module splits) cannot change behaviour unnoticed.

Out of scope: layer import rules and the error hierarchy (plan 003+), any
refactor or bug fix, the README reorganisation (a later plan), sealing the
eval data (plan 002).

## Acceptance criteria

- [ ] `uv run poe check` runs `fmt`, `lint`, `types`, `arch`, `docs`, `test` in that order, prints one pass/fail line per task, exits non-zero if any fails, and passes on a clean checkout. Each task also runs alone (`uv run poe lint`, ...).
- [ ] `uv.lock` is committed and `uv lock --check` passes.
- [ ] `fmt`: `ruff format --check` passes on the whole repo, after one mechanical format commit whose syntax trees are verified unchanged and which is listed in `.git-blame-ignore-revs`.
- [ ] `lint`: ruff passes with today's rule set (no rules widened in this plan).
- [ ] `types`: mypy in strict mode with the pydantic plugin over `src/` and `harness/`. Today's errors are in a baseline file; a new error fails the task, and a fixed error must be removed from the baseline (the update command only removes).
- [ ] `arch` (v0) prints rule ID, file:line and a `FIX:` line for each violation, each rule has a test with a failing example, and every allow-list entry names a TD item. Rules: ARCH-SIZE (at most 400 lines per module in `src/`; current offenders allow-listed at their current length), ARCH-PRINT (no `print` in `src/` except `src/cli.py`), ARCH-ENV (no environment reads outside `src/config.py`), ARCH-ENVEX (`Settings` fields and `.env.example` keys match exactly), ARCH-SECRET (no key-shaped strings in tracked files).
- [ ] `docs` checks: required docs exist; relative links, heading anchors and `path:line` links resolve; every doc is reachable from `CLAUDE.md`; every plan has the five required sections and a status matching its folder; errors in the same format as `arch`, with tests.
- [ ] The layout exists: `CLAUDE.md` (about 100 lines), `ARCHITECTURE.md`, `SECURITY.md`, `docs/project/DESCRIPTION.md`, `docs/project/overview.md`, `docs/design/decisions.md`, `docs/plans/` (README, active/, completed/, roadmap.md, tech-debt.md), `docs/harness/golden-principles.md`, `docs/generated/`.
- [ ] `uv run poe gen` writes `docs/generated/openapi.json` and `docs/generated/settings.md`; a test fails with a FIX line when either is stale.
- [ ] Characterization tests pin input to output where no existing test does, for: reading the fixture questionnaires, one full answer through the graph (fake corpus, scripted LLM), the cells `fill` writes, the CSV/DOCX/PDF export text, and chunking of the fixture documents. Snapshots change only through an explicit update command. Suspected bugs found while writing them go to tech-debt.md, unfixed.
- [ ] tech-debt.md holds the survey findings.
- [ ] Baselines recorded in this plan: test count and runtime, line coverage per package (measured, not gated), mypy error count, oversized modules.

## Plan

1. Commit the pre-existing work in progress as-is (decision 1a). Commit this plan, the plan template, the roadmap, and tech-debt.md seeded from the Phase 0 survey.
2. Toolchain: dev tools (poethepoet, mypy, pytest-cov) in a uv dependency group; commit `uv.lock`; verify the suite still passes on the locked versions.
3. Task runner with `fmt`, `lint`, `test`. Mechanical format commit, syntax trees verified unchanged, hash in `.git-blame-ignore-revs`.
4. `types` with its baseline tool.
5. Docs layout and `CLAUDE.md`.
6. `docs` check and its tests.
7. `arch` v0 and its tests.
8. Generated docs and the staleness test.
9. Audit which key paths are already pinned end to end; add characterization tests for the gaps.
10. Wire `check`, record baselines, move this plan to `completed/`, update the roadmap.

## Progress log

- 2026-10-05: Phase 0 survey done (reported in chat, findings now TD-001 to TD-020 in [tech-debt.md](../tech-debt.md)). Measured baseline before any change: 1580 tests collected, 1570 passed, 1 skipped (needs openpyxl), 9 deselected (`live_ai`); two runs took 242 s and 214 s; the slowest test 7.4 s and the slowest 15 together about 22 s. `ruff check` with the configured rules passes; `ruff format --check` would reformat 116 of 141 files. 18 modules in `src/` exceed 400 lines. OpenAPI has 70 operations. `.env.example` matches all 77 `Settings` fields. No type checker, coverage tool, lock file or task runner existed.
- 2026-10-05: Step 1. Committed the pre-existing reasoning-model work as `0307833` (decision 1a).
- 2026-10-05: Step 2 (`4b031f9`). An unconstrained `uv lock` would have upgraded about 60 installed packages (sentence-transformers 5.7 to 6.1, websockets 15 to 16, torch 2.13 to 2.14, ...). `UV_CONSTRAINT` is ignored by `uv lock`, so the lock was made with temporary `tool.uv.constraint-dependencies` pins to the installed versions, which were then removed; uv keeps locked versions on re-lock. Result: 187 packages locked, the venv differs from before only by the 9 new tool packages, `uv lock --check` passes.
- 2026-10-05: Step 3. Found while running the suite through poe: this `.venv` was copied from another checkout, and 46 of its `.exe` launchers (pytest, uvicorn, ...) still started that checkout's interpreter (`...\Git_repos\cyber_agent_QA\assessment-answer\.venv`), so `pytest` failed to import `rank_bm25`. The Phase 0 numbers are unaffected (they were run as `.venv/Scripts/python.exe -m pytest`). Fixed twice: tasks call `python -m <tool>` inside `.venv` (D-008, held by `tests/harness/test_tasks.py`), and the launchers were regenerated by reinstalling the same 175 versions (freeze identical before and after). Also: ruff 0.16 formats Python blocks in Markdown and stripped the README's aligned comments, so Markdown is excluded from `fmt`. The first formatted run failed one test, `test_the_shipped_parameters_are_the_interactive_ones`, which grepped the source text for `2 ** 14`; it now reads the syntax tree (`bb525b8`), verified to still fail when `SCRYPT_N` changes. Format commit `4a7c3c6`: 117 files, `harness.same_ast` identical, suite 1575 passed, 1 skipped.
- 2026-10-05: Step 4 (`b74fb3a`). mypy strict: 336 errors, of which 12 were untyped libraries (now an override), leaving 324 in `harness/mypy-baseline.txt` (111 in `src/api.py`). `harness/` has none.
- 2026-10-05: Steps 5 to 8. Docs layout and `CLAUDE.md` (96 lines). `docs` check (DOCS-REQUIRED, -LINK, -ANCHOR, -ORPHAN, -PLAN, -ID, -MAP) and `arch` v0 (ARCH-SIZE, -PRINT, -ENV, -ENVEX, -SECRET, -ALLOW), 39 rule tests. After formatting, 19 modules exceed 400 lines (`src/graph/nodes.py` went from 399 to 406 through formatting alone); all are allow-listed at their current length under TD-006. ARCH-SECRET found two false positives on first run (a `lsv2_...` placeholder in the README, a test `ADMIN_PASSWORD` constant); the env-line pattern now skips placeholders and Python files, while key-shaped values are still caught everywhere. Found while writing SECURITY.md: the README's claim of a test for markup in status lines has no matching test (TD-021). `uv run poe gen` writes `openapi.json` (verified identical under different settings) and `settings.md` (77 settings, from the syntax tree, without importing config); a test fails when either is stale, verified by a hand edit. Moved a misplaced comment in `src/config.py` (TD-005), syntax tree unchanged. Next: step 9, characterization tests.

## Decision log

- 2026-10-05: Decisions made by the user in chat after the survey: commit the work in progress as-is first (1a); poethepoet as the task runner (2a); one mechanical `ruff format` commit, verified, then enforced (3a); mypy strict with the pydantic plugin plus a baseline (4a); seal `eval/house_set.json` and `eval/answer_memory.json` with a key held in `.env`, encrypting forward only, with no history rewrite (plan 002); keep the README and reorganise its content into `docs/` in a later plan; I (Claude) write `docs/project/DESCRIPTION.md`; the OpenAI article PDF stays local and is gitignored. The user confirmed `tests/fixtures/MDS-CS-STD-003-...pdf` is not a real internal standard.
- 2026-10-05: Harness code lives in a top-level `harness/` package with tests in `tests/harness/`, so it is never mistaken for application code (my choice; `scripts/` holds operational scripts for the app).
- 2026-10-05: `types` covers `src/` and `harness/` only; `eval/`, `scripts/` and `tests/` are left for later (my choice: strict mode over ~33k lines of tests and scripts would bury the baseline in noise).
- 2026-10-05: Dev tools moved from the `dev` extra to a uv dependency group so `uv run` installs them without a flag; the README's setup line changed from `uv sync --extra dev` to `uv sync --inexact` (`--inexact` keeps optional extras such as `phoenix` that are installed in the venv). My choice.
- 2026-10-05: The lock pins the installed, tested versions rather than the newest (D-004). Alternative rejected: lock the newest and rerun the suite; that would have mixed an upgrade into a tooling change. My choice.
- 2026-10-05: Untyped third-party libraries are ignored by a mypy override instead of being baselined: they are not our errors and cannot be fixed here. My choice.
- 2026-10-05: The `docs` and `arch` checks read the Settings class from the syntax tree of `src/config.py` instead of importing it: importing reads the real `.env` and starts tracing, which checks must not do. My choice.
- 2026-10-05: ARCH-SIZE is a ratchet: when an allow-listed module shrinks, its ceiling must be lowered to match (the FIX line gives the number). Alternative: a tolerance band; rejected because "only shrinks" would then be enforced by review. My choice.
- 2026-10-05: A plan is reached from the roadmap, not from a directory link: DOCS-ORPHAN treats a link to a folder as reaching only its README, so every plan must be listed in `roadmap.md`. My choice.
