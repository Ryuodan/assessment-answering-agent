"""Two house-set runs, compared question by question rather than by their averages.

    python -m scripts.compare_runs eval/results/before.json eval/results/after.json
    python -m scripts.compare_runs before.json after.json --noise eval/results/noise_dev.json

An average can stay put while ten answers get better and ten get worse, and a
two-point rise can be three questions that would have moved anyway. This reads
the per-case rows both runners write (`agreement_score`, `verdict`, `form`,
`failure`) and says which cases moved and which way.

With `--noise` (written by `scripts.measure_noise`), a case whose score already
varied between identical runs is reported as within noise, whichever way it
moved: only a change on a case that was stable is evidence.

A case that failed in either run (`failure` set: the machinery, not the answer)
is left out and counted. Exit code 0 always: this reports, it does not judge.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _rows(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {row["test_id"]: row for row in data["cases"]}


def _scored(row: dict) -> bool:
    return (
        not row.get("failure")
        and row.get("verdict") not in ("", "unanswerable")
        and row.get("agreement_score") is not None
    )


def compare(before: dict[str, dict], after: dict[str, dict], unstable: set[str]) -> dict:
    shared = sorted(set(before) & set(after))
    failed = [t for t in shared if before[t].get("failure") or after[t].get("failure")]
    scored = [t for t in shared if t not in failed and _scored(before[t]) and _scored(after[t])]
    moved = {"better": [], "worse": [], "within_noise": []}
    same = 0
    for test_id in scored:
        delta = after[test_id]["agreement_score"] - before[test_id]["agreement_score"]
        if delta == 0:
            same += 1
        elif test_id in unstable:
            moved["within_noise"].append(test_id)
        else:
            moved["better" if delta > 0 else "worse"].append(test_id)
    return {
        "shared": len(shared),
        "only_before": len(set(before) - set(after)),
        "only_after": len(set(after) - set(before)),
        "failed_in_either": len(failed),
        "compared": len(scored),
        "same": same,
        **moved,
    }


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--noise", type=Path, default=None, help="a noise_*.json from scripts.measure_noise")
    parser.add_argument("--show", action="store_true", help="print each moved case's question and both verdicts")
    args = parser.parse_args(argv)

    before, after = _rows(args.before), _rows(args.after)
    unstable: set[str] = set()
    if args.noise:
        unstable = set(json.loads(args.noise.read_text(encoding="utf-8"))["unstable"])
    result = compare(before, after, unstable)

    print(f"{args.before.name} -> {args.after.name}")
    print(
        f"  {result['compared']} compared of {result['shared']} shared "
        f"({result['failed_in_either']} failed in either run, left out)"
    )
    print(f"  better {len(result['better'])}   worse {len(result['worse'])}   same {result['same']}", end="")
    print(
        f"   moved within noise {len(result['within_noise'])}"
        if args.noise
        else "   (no noise file: every move counted)"
    )
    for kind in ("worse", "better", "within_noise"):
        for test_id in result[kind]:
            b, a = before[test_id], after[test_id]
            print(
                f"  {kind:12} {test_id}  {b['verdict']} {b['agreement_score']} -> {a['verdict']} {a['agreement_score']}"
            )
            if args.show:
                print(f"               Q {b['question'][:110]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
