# Plan 025: Cleanup round 4

**Status:** completed

## Goal

The fourth garbage-collection round, after milestone M7 (products), with the
same tools as rounds 1 to 3: `poe gc`, `poe cov` and `poe grades`.

M7 changed `src/` a great deal, so coverage is measured again. The round also
brings the tech-debt items that M7's plans changed up to date, and closes
plan 018 and the milestone.

## Acceptance criteria

- [x] `poe gc` has been run, and every candidate is acted on or already decided.
- [x] Round 4 grades are recorded in [grades.md](../../quality/grades.md), with coverage measured on this tree.
- [x] Every tech-debt item that plans 019 to 024 changed says so.
- [x] Plan 018 is complete and moved to `completed/`; the roadmap shows M7 done.
- [x] `uv run poe check` passes.

## Plan

1. Run `poe gc` and `poe cov`, and act on what is new.
2. Record the grades.
3. Refresh the stale tech-debt states.
4. Close plan 018 and M7. Run the gate, and close this plan.

## Progress log

- 2026-10-06: `poe gc` found the candidates decided in round 1 and nothing new: 4 TEST-ONLY and 2 DUPLICATE (plan 008). OVERSIZE went from 18 to 16, because `store.py` (plan 019) and `models.py` (plan 023) are under the limit.
- 2026-10-06: `poe cov`: 1,861 tests passed in 414 s, and statement coverage is 92%. The modules M7 added are between 95% and 100%.
- 2026-10-06: `poe grades` put the interfaces layer's docstrings at D (59%). 27 of the public names without one were in modules that plans 019 to 024 created or filled: the routers, `cli.py` and `web.py`. Seven were new in M7, and the rest had moved out of `api.py`, where the size ceiling had kept them undocumented since round 1.
  - All 27 now have a docstring: D (59%) -> B (80%).
  - Against the contract from before: identical once descriptions are set aside. Seven paths gained one.
  - `api.py` stays as it was. A docstring on its one new request model took it a line over its ceiling, because the formatter adds a blank line after a class docstring, so that change was reverted.
- 2026-10-06: Tech debt brought up to date:
  - TD-006: 16 modules, each figure from M7's moves;
  - TD-016: only the preferences page is untested in a browser;
  - TD-017: 1,861 tests in 355 to 415 s;
  - TD-028: 21 modules allow-listed, and M7's new modules log events.
- 2026-10-06: Grades round 4 recorded. Plan 018 is complete and moved to `completed/`. The roadmap shows M7 and cleanup round 4 done.
- 2026-10-06: `uv run poe check` passes: 1,861 tests in 408 s, and 13 browser tests. Plan complete, and with it M7.

## Decision log
