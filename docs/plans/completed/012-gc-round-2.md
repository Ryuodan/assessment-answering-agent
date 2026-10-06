# Plan 012: Cleanup round 2

**Status:** completed

## Goal

The second garbage-collection round, after milestones M4 (README
reorganised) and M5 (diagnostics, browser tests). It reuses round 1's tools
and thresholds: `poe gc`, `poe cov` then `poe grades`, and a reading of the
documents the milestones touched. That keeps its grades comparable with round
1's. Whatever the round finds is acted on or recorded.

## Acceptance criteria

- [x] `poe gc` has been run. Every candidate is either acted on or covered by round 1's recorded decisions.
- [x] Round 2's grades are recorded in [grades.md](../../quality/grades.md) next to round 1's, with what moved and why.
- [x] Documents and comments that still point to the README for text plan 009 moved now point to where the text is.
- [x] `uv run poe check` passes.

## Plan

1. Run `poe gc`, and compare it with the end of round 1.
2. Run `poe cov` and `poe grades`, and record round 2.
3. Search the documents and code for stale README references, and fix them.
4. Run the gate and close the plan.

## Progress log

- 2026-10-06: `poe gc` found the same candidates as the end of round 1, and nothing new: 4 TEST-ONLY, 1 UNUSED (`documents.load_url_text`, TD-032, waiting on the user), 2 DUPLICATE (both recorded in plan 008), and 18 OVERSIZE.
- 2026-10-06: `poe cov`: 1,792 passed, total coverage 91% (round 1: 89%). `poe grades`: interfaces coverage went from B to A (`cli.py` from 0% to 66%). Integrations docstrings fell from 96% to 91% because the new `src/diagnostics.py` had five public functions without one. They were added in this round; the layer is now at 97%.
- 2026-10-06: Three stale references fixed:
  - `SECURITY.md` called the design notes "README sections".
  - `docs/project/overview.md` said the README "is being reorganised".
  - `scripts/dev_server.py` cited "the open mode the README calls". It now points to `docs/design/access.md`, and the comment is the only change to that file.
- 2026-10-06: `uv run poe check` passes (1,792 tests, 5 browser tests). Plan complete.

## Decision log

- 2026-10-06: One round for two milestones. M4 changed documents only and M5 added two small modules and tests, so a round after each would have measured nearly the same tree twice. The roadmap's rule is "after each milestone or about 40 commits". This round covers both and says so. (Claude)
