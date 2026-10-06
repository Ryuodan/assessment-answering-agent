# Plan 015: Cleanup round 3

**Status:** completed

## Goal

The third garbage-collection round, after milestone M6. It reuses the same
tools (`poe gc`, `poe grades`) and adds two things:

- a pass over tech-debt items whose recorded state the milestones had made
  stale;
- a first measurement of where the suite's time goes (TD-017).

It also fixes whatever is small and behaviour-neutral, and records the rest.

## Acceptance criteria

- [x] `poe gc` has been run, and every candidate is acted on or already decided.
- [x] Round 3 grades are recorded in [grades.md](../../quality/grades.md).
- [x] Every tech-debt item that the plans since round 2 changed says so (TD-016, TD-017, TD-018).
- [x] `uv run poe check` passes.

## Plan

1. Run `poe gc`, and act on what is new.
2. Refresh the stale tech-debt states. Fix TD-018. Measure TD-017 and take its cheap win.
3. Record the grades, run the gate, and close the plan.

## Progress log

- 2026-10-06: `poe gc` showed round 1's candidates plus two new STALE-PATH hits. Both named `eval/final_runs.jsonl`, which plan 013 creates on the first final-split run. It is now committed empty, so "the final split has been looked at 0 times" is on record, and both hits are gone.
- 2026-10-06: TD-016 marked partly resolved: plan 011 tests the workbench in a browser; the chat, memory and preferences pages are still untested. TD-018 fixed: `Evidence` imported under `TYPE_CHECKING` in `src/prompts.py`, which took the mypy baseline from 284 to 283.
- 2026-10-06: TD-017 measured with `--durations=25`: 1,803 tests in 319 s. The 25 slowest phases add up to about 50 s; the rest is about 0.15 s per test, which points to setup. The five staleness tests in `tests/harness/test_generated.py` each rebuilt all five generated documents. A module-scoped fixture now builds them once, and the file takes 9.1 s instead of about 19 s.
- 2026-10-06: Grades round 3 recorded. `src/` is unchanged since round 2 apart from TD-018, so the coverage column is round 2's run, and the grades record says so. No grade moved.
- 2026-10-06: `uv run poe check` passes (1,803 tests in 249 s, 5 browser tests). Plan complete.

## Decision log

- 2026-10-06: Coverage was not re-run for round 3. `git diff` from round 2 to M6's last commit shows no change under `src/`, so a 6-minute run would have measured the same thing. The grades record says which run the column comes from. (Claude)
