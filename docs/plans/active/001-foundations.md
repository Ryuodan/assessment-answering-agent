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

## Decision log

- 2026-10-05: Decisions made by the user in chat after the survey: commit the work in progress as-is first (1a); poethepoet as the task runner (2a); one mechanical `ruff format` commit, verified, then enforced (3a); mypy strict with the pydantic plugin plus a baseline (4a); seal `eval/house_set.json` and `eval/answer_memory.json` with a key held in `.env`, encrypting forward only, with no history rewrite (plan 002); keep the README and reorganise its content into `docs/` in a later plan; I (Claude) write `docs/project/DESCRIPTION.md`; the OpenAI article PDF stays local and is gitignored. The user confirmed `tests/fixtures/MDS-CS-STD-003-...pdf` is not a real internal standard.
- 2026-10-05: Harness code lives in a top-level `harness/` package with tests in `tests/harness/`, so it is never mistaken for application code (my choice; `scripts/` holds operational scripts for the app).
- 2026-10-05: `types` covers `src/` and `harness/` only; `eval/`, `scripts/` and `tests/` are left for later (my choice: strict mode over ~33k lines of tests and scripts would bury the baseline in noise).
