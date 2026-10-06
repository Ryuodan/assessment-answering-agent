# Plan 013: An evaluation whose numbers can be trusted

**Status:** completed

## Goal

The house set has five questionnaires, 135 questions, with the security
team's own answers. It is how the product is measured, and TD-014 lists why
its numbers cannot yet be taken at face value:

- Every change was kept or dropped on the same five questionnaires, so there
  is no split that was not tuned against.
- No check keeps benchmark items out of what the system is built from.
- An infrastructure failure scores as an answer:
  - a question that failed to answer is judged as "(no answer)";
  - a judge that failed is filed as `unanswerable`.
- Two runs are compared by their averages alone, with no measure of how far
  an unchanged system moves between runs.

This plan builds the method. Plan 014 spends on it: three identical runs of
the dev split to measure noise. This is milestone M6, with the user's
approval for up to three repeat runs over the dev split with real model
calls.

## Acceptance criteria

- [x] The house set is split by questionnaire into `dev` (3 questionnaires, 82 cases) and `final` (2, 53), recorded in `eval/splits.json` under hashes of the file names (no customer names). An unassigned questionnaire is an error with a FIX line.
- [x] Both runners take `--split` (default `dev`). `--split final` requires `--reason`, and every final run is appended to `eval/final_runs.jsonl` (when, why, the numbers; no content).
- [x] An answering or judging failure is marked on its case (`failure`), left out of every score, and counted on its own line. A run with more than 5% failures is reported NOT COMPARABLE.
- [x] Contamination check:
  - Before spending anything, both runners check that no run of 10 consecutive words from a benchmark question or reference answer appears in `src/`, and that no house-set question is, normalised, a question in the answer memory. A leak stops the run.
  - `poe eval-contamination` runs the same check by hand.
  - A test checks the golden set against `src/` on every run.
- [x] `scripts/compare_runs.py` compares two runs case by case: better, worse, same, failed in either. Given a noise file, a move on a case that varied between identical runs is "within noise".
- [x] `scripts/measure_noise.py` runs the dev split N times and writes each run's numbers, their spread, the smallest difference worth calling a change, and the unstable cases.
- [x] The duplicated answer-and-judge code of the two runners lives once, in `eval/house.py` (`run_cases`, `answer_cases`, `judge_cases`, `case_rows`).
- [x] Tests use synthetic cases only (the house set is sealed customer data).
- [x] `uv run poe check` passes.

## Plan

1. Add `eval/splits.py` and `eval/splits.json`, and choose the split from case counts per hashed file.
2. Add `eval/contamination.py`, the `poe eval-contamination` task, and the golden-set test.
3. In `eval/house.py`, add failure marking and the shared run, judge and row helpers. Point both runners at them, and add `--split`, `--reason`, the contamination gate and the final-run record.
4. Add `scripts/compare_runs.py` and `scripts/measure_noise.py`.
5. Write the tests and docs (the evaluation document and TD-014), run the gate, and close the plan.

## Progress log

- 2026-10-06: Split chosen from case counts per questionnaire, read by hashed file name only. The five questionnaires hold 30, 44, 17, 21 and 23 cases, all English. `dev` = 44 + 21 + 17 = 82; `final` = 30 + 23 = 53.
- 2026-10-06: `eval/splits.py`, `eval/contamination.py`, `scripts/compare_runs.py` and `scripts/measure_noise.py` added. `eval/house.py` gained `run_cases`, `answer_cases`, `judge_cases` and `case_rows`, and a `failure` on each result; a failed judge now returns None. The two runners are 68 lines shorter: their duplicated answer, judge and row code moved there. Both take `--split` and `--reason`, screen for contamination before spending, and record final runs.
- 2026-10-06: First contamination check on the unlocked house set (`poe eval-status`: both files in step with their seals): 135 cases, 1 leak. The leak is a 10-word run of HOUSE-096's reference answer (dev split; first written here as final, a misreading of the check's log corrected in plan 014), found at `src/prompts.py` line 91, in the drafting prompt's style example. Recorded as TD-033 and listed in `KNOWN`, so runners leave the case out. No house-set question matched a question in the answer memory. Only counts, ids and the run of words already in `src/prompts.py` were read into this session; no other customer text.
- 2026-10-06: `tests/test_evaluation_method.py` (10 tests, synthetic cases only) covers the split selection and its refusal, the committed split naming no questionnaire, the final-run record, both kinds of leak, a known leak versus a new one, failures left out of the score and the NOT COMPARABLE threshold, and the case-by-case comparison. One test also checks the 42 golden-set questions against `src/`, and none is there.
- 2026-10-06: `uv run poe check` passes (1,802 tests, 5 browser tests). Plan complete.

## Decision log
- 2026-10-06: The split is chosen by case count and recorded by hashes of the file names. The names would say who the customers are, and the data is sealed for that reason (plan 002). A hash prefix could confirm a guessed name, but not reveal one. (Claude)
- 2026-10-06: A contamination check that finds a leak stops the run. A leak that cannot be fixed at once is recorded in `KNOWN` against a tech-debt item and its case left out, the same only-shrinks rule the harness's allow-lists follow. Changing the prompt to remove the leak would change answers, so that is the user's call (TD-033). (Claude)
- 2026-10-06: No test reads the house set. It is customers' data, and tests never touch real data (non-negotiable 4). It is checked by the runners and by `poe eval-contamination`, which are run by hand. The golden set is tracked in plain text and is checked on every test run. (Claude)
