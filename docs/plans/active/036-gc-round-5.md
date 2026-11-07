# Plan 036: Cleanup round 5

**Status:** active

## Goal

The fifth garbage-collection round, asked for by the user after plans 031 to 035, with the same tools as rounds 1 to 4: `poe gc`, `poe cov`, `poe grades` and `poe arch-lower`. It also brings the tech-debt items the plans changed up to date, and closes plans 031 to 035 once the A-to-Z run is clean on the final tree.

## Acceptance criteria

- [ ] `poe gc` has been run, and every candidate is acted on or already decided.
- [ ] Round 5 grades are recorded in [grades.md](../../quality/grades.md), with coverage measured on this tree.
- [ ] The size ceilings are lowered to what the modules are now.
- [ ] Every tech-debt item that plans 031 to 035 changed says so. Routes no page uses are recorded for the user.
- [ ] The A-to-Z run is clean on the final tree. Plans 031 to 035 are completed and moved; the roadmap is updated.
- [ ] `uv run poe check` passes.

## Plan

1. `poe gc`: act on what is new.
2. `poe cov` and `poe grades`: record round 5.
3. Tech-debt states; the unused routes.
4. The final A-to-Z run; close plans 031 to 035; gate; close this plan.

## Progress log

- 2026-11-07: `poe gc`: 4 TEST-ONLY, 3 DUPLICATE, 1 SUPPRESS, 15 OVERSIZE.
  - **TEST-ONLY:** `forget_sync`, `is_allowed`, `reset_connection` and `database_size` are the four decided in plan 008.
  - **DUPLICATE:**
    - `forms/xlsx.py` / `forms/xlsx_package.py` was decided in plan 008.
    - `migration_steps.py` / `migrations.py` is the `memory_entries` table in two migrations. A migration is history and is not edited, so it stays.
    - `lists.py` / `tools.py` was new: both openers set the person's preferred length in the same eight lines. They now share `questionnaire.at_their_length`. Behaviour-neutral, behind the existing tests; `tools.py` went from 1150 to 1144.
  - **SUPPRESS:** the one `type: ignore` without a reason (`tests/test_assistant.py`) now has its reason.
  - **OVERSIZE:** 15 (round 4: 16). They are the allow-listed modules, none over its ceiling.
- 2026-11-07: TD-016's last gap closed: the preferences page has a browser test of its own (`tests/browser/test_preferences_page.py`, 2 tests).
- 2026-11-07: `poe cov`: 2,401 tests passed in 510 s; statement coverage 93% (round 4: 92%). `poe grades` recorded as round 5 in [grades.md](../../quality/grades.md): every layer A on coverage; answering B to A (87.7% to 90.7%); suppressions up in records (7 to 10) and integrations (9 to 10), each a broad `except` with its reason.
- 2026-11-07: `poe arch-lower`: `tools.py` 1150 to 1144.
- 2026-11-07: tech debt brought up to date:
  - TD-006: 15 modules, with each plan's moves;
  - TD-016 resolved: every page has browser tests, 197 in all;
  - TD-017: about 0.17 s a test, unprofiled;
  - TD-028: 21 modules, and every new one logs events.
  - Recorded for the user: TD-079, four API routes no page, script or evaluation uses.

## Decision log

- 2026-11-07, by the user: "Then do a cleaning round."
