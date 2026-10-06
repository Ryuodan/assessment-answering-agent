# Plan 014: Run-to-run noise on the house set, measured

**Status:** completed

## Goal

Before any change to the system is judged on the house set, measure how far
its score moves when nothing changes at all. Run the dev split three times,
with identical code, settings, corpus and memory. The spread of those runs
says how big a difference must be before it means anything, and which cases
move on their own. TD-014 asked for this.

Plan 013 built the tools for it; this plan spends real model calls. The user
approved up to three repeat runs over the whole dev split on 2026-10-06.

## Acceptance criteria

- [x] Identical runs of the dev split (81 cases, after the known leak is left out) with the deployment's own settings, within the approved budget, after the contamination check passed. Revised from "three runs over 82 cases" after run 2 hung; see the decision log.
- [x] Each run's agreement, form and infrastructure failures are recorded here and in `docs/measurements/evaluation.md`, along with:
  - the mean, standard deviation and range;
  - the smallest difference worth calling a change;
  - how many cases moved between identical runs.
- [x] TD-014 says what is now resolved and what is not (see the decision log).
- [x] `uv run poe check` passes.

## Plan

1. Check the sealed data is unlocked and in step (`poe eval-status`), and run the contamination check (`poe eval-contamination`).
2. Run `uv run python -m scripts.measure_noise --repeats 3 --label baseline`.
3. Record the numbers and what they mean for reading a change. Update the evaluation document and TD-014. Close the plan, and milestone M6.

## Progress log

- 2026-10-06: Started `scripts.measure_noise --repeats 3 --label baseline` at 06:59 (local time). Before it ran, `poe eval-status` reported both sealed files unlocked and in step. The contamination screen left one case out: HOUSE-096 (TD-033). That made a correction necessary: plan 013 and TD-033 had recorded HOUSE-096 as being in the final split, but it is in dev. The lookup behind that record had read the wrong token from the check's log. Each run therefore scores 81 cases, not 82.
- 2026-10-06: Run 1 finished at 07:15: 81 cases, 79 scored, 2 answering failures (Groq's tokens-per-minute limit, after the client's retries). Agreement 83.5%, form 96.2%. Comparable (2.5% failures, under the 5% limit).
- 2026-10-06: Run 2 hung. From 07:38 nothing was logged; the process used no CPU and held one open connection to the embedding host (`ds.t2.sa`, 8.213.24.143). The embedding client has no timeout of its own (TD-034). I expected the OpenAI client's defaults (600 s, 2 retries) to give up by 08:08; at 08:31 it had not, so the run was stopped and its partial results lost. In total, 780 Groq retries were logged across runs 1 and 2.
- 2026-10-06: `scripts/measure_noise.py --summarise` added, to build the noise summary from run files written by separate invocations. Then one more full run (label `baseline_b`) was started at 08:31 and watched for a 15-minute stall.
- 2026-10-06: The `baseline_b` run finished at 08:50 with no stall: 81 cases, 77 scored, 4 answering failures (4.9%, under the 5% limit). Agreement 87.0%, form 97.8%. `--summarise` over the two complete runs: mean 85.2, standard deviation 2.47, range 3.5; smallest difference worth calling a change 4.9 points; 12 cases unstable. On the 75 cases both runs scored: 82.7% and 86.7%. Seven of the 12 moves were the full 5 points, and in 7 cases "contradicts" appeared in one run only. Recorded in `docs/measurements/evaluation.md` ("Run-to-run noise on the house set") and TD-014.
- 2026-10-06: The run files (`eval/results/noise_baseline_1.json`, `noise_baseline_b_1.json`) and the summary (`noise_baseline.json`) are in the gitignored `eval/results/`, because they hold the customers' questions and the team's answers. Only the numbers above are committed.
- 2026-10-06: `uv run poe check` passes (1,803 tests, 5 browser tests). Plan complete; milestone M6 done, with TD-014's clean final split still open.

## Decision log
- 2026-10-06: After the hang, the measurement stays within the user's limit of three full runs' worth of spend: run 1, most of run 2 (lost), and one more full run. That gives two complete runs, not three. Two runs give a range and the cases that moved, but only a rough standard deviation; this is said wherever the numbers are quoted. A third run is better made after TD-034 is fixed, so it cannot hang the same way. (Claude)
- 2026-10-06: TD-034 (no embedding timeout) is recorded, not fixed. A timeout changes behaviour for a slow but working host, so it is the user's decision (non-negotiable 3). (Claude)
- 2026-10-06: The first acceptance criterion was revised after the hang, from three runs over 82 cases to the identical runs the budget allowed (two) over the 81 cases that may be scored. The alternative was a fourth run's worth of spend that the user had not approved. (Claude)
