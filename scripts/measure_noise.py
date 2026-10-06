"""How much a house-set score moves when nothing has changed.

    python -m scripts.measure_noise --repeats 3            # the dev split (never the final one), three identical runs
    python -m scripts.measure_noise --repeats 3 --label baseline

Run the same split with the same settings several times and see how far the
numbers wander. That spread is the noise. A difference between two versions
that is smaller than it is not evidence of anything, however it is reported.

Writes each run (`eval/results/noise_<label>_<n>.json`, the same rows the other
runners write) and a summary (`eval/results/noise_<label>.json`):

- every run's agreement and form, with their mean, standard deviation and range;
- `smallest_real_difference`: twice the standard deviation of a run's agreement,
  the smallest change between two single runs worth calling a change;
- `unstable`: the cases whose agreement score was not the same in every run.
  `scripts.compare_runs --noise` reports a move on one of them as within noise.

Costs `repeats` full answering-and-judging passes over the split: real model
calls. The facts set's noise was measured the same way once (four repeats,
79.0 to 75.2: `scripts.run_both_evals`, NOISE).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import PROJECT_ROOT, configure_logging
from src import llm
from eval import contamination
from eval.house import case_rows, load_house_set, load_memory_set, run_cases, summarise
from eval.splits import select

RESULTS = PROJECT_ROOT / "eval" / "results"


def noise(runs: list[dict]) -> dict:
    """The spread of a list of summaries, and the cases that did not repeat themselves."""
    agreement = [run["summary"]["agreement"] for run in runs]
    form = [run["summary"]["form"] for run in runs]
    scores: dict[str, set] = {}
    for run in runs:
        for row in run["cases"]:
            if not row["failure"] and row["agreement_score"] is not None:
                scores.setdefault(row["test_id"], set()).add(row["agreement_score"])
    spread = statistics.stdev(agreement) if len(agreement) > 1 else 0.0
    return {
        "runs": len(runs),
        "agreement": agreement,
        "form": form,
        "agreement_mean": round(statistics.mean(agreement), 1),
        "agreement_stdev": round(spread, 2),
        "agreement_range": round(max(agreement) - min(agreement), 1),
        "form_stdev": round(statistics.stdev(form), 2) if len(form) > 1 else 0.0,
        "smallest_real_difference": round(2 * spread, 1),
        "unstable": sorted(test_id for test_id, seen in scores.items() if len(seen) > 1),
        "stable": sum(1 for seen in scores.values() if len(seen) == 1),
        "failures": [run["summary"]["failures"] for run in runs],
    }


async def main_async(args: argparse.Namespace) -> int:
    cases = contamination.screen(select(load_house_set(), "dev"), [m.question for m in load_memory_set()])
    if cases is None:
        return 1
    print(f"{len(cases)} cases in the dev split; {args.repeats} identical runs")
    runs = []
    for n in range(1, args.repeats + 1):
        print(f"\nrun {n} of {args.repeats}: answering and judging…")
        results = await run_cases(cases)
        run = {"label": f"{args.label} {n}", "summary": summarise(results), "cases": case_rows(results)}
        out = RESULTS / f"noise_{args.label}_{n}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8")
        s = run["summary"]
        print(f"  agreement {s['agreement']:.1f}%  form {s['form']:.1f}%  failures {s['failures']}  -> {out.name}")
        runs.append(run)

    summary = noise(runs)
    path = RESULTS / f"noise_{args.label}.json"
    path.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(
        f"\nagreement over {summary['runs']} runs: {summary['agreement']} "
        f"mean {summary['agreement_mean']}, stdev {summary['agreement_stdev']}, range {summary['agreement_range']}"
    )
    print(f"smallest difference worth calling a change: {summary['smallest_real_difference']} points")
    print(
        f"cases whose score changed between identical runs: {len(summary['unstable'])} of "
        f"{len(summary['unstable']) + summary['stable']}"
    )
    print(f"written to {path}")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--label", default="dev")
    args = parser.parse_args()
    configure_logging()
    return llm.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
