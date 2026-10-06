"""Both suites, one command, with the house set as the target and the facts set as a floor.

    python -m scripts.run_both_evals --label "org profile added"
    python -m scripts.run_both_evals --label "..." --sample 40
    python -m scripts.run_both_evals --compare eval/results/house_baseline.json

The two suites disagree by design and that is the whole point of running them
together. The house set asks whether we write what the security team would have
written; the facts set asks whether the answer is right and complete. Optimising
either alone produces a system that fails the other -- measuring only fact
coverage is what produced 152-word answers against a team median of 11, and
optimising the house set alone would produce answers that are short and wrong,
which is worse than what we started with.

So one is the target and the other is a floor:

  HOUSE SET   the number to move. Agreement with the team's own answers on
              what this organisation actually claims, plus a narrow form score
              -- verdict first, no telling the assessor our documentation is
              silent. Length is reported and never scored: the team's answers
              are short because they had hundreds to write, not because short
              is what they want.
  FACTS SET   the number that must not fall. A change that improves the house
              score while dropping this one has traded correctness for brevity,
              and that trade is refused here rather than discovered later.

`--floor` sets how far the facts score may drift before the run is called a
regression. The default of 2 points is roughly the run-to-run noise measured
across four repeats of an unchanged system (79.0, 75.2, 77.6, 77.1).
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.config import PROJECT_ROOT, configure_logging
from src import llm
from src.models import AssessmentResult

from eval.dataset import align, load_golden_set
from eval import contamination
from eval.house import case_rows, format_summary, load_house_set, load_memory_set, run_cases, summarise
from eval.splits import final_runs, record_final_run, select
from eval.judge import judge_all
from eval.report import build_report

RESULTS = PROJECT_ROOT / "eval" / "results"
NOISE = 2.0
"""Points the facts score may move without meaning anything.

Four repeats of an unchanged system scored 79.0, 75.2, 77.6 and 77.1 -- a
spread of 3.8. Half of that is the smallest drop worth calling a regression.
"""


async def run_house(cases, label: str) -> dict:
    print(f"\n[house] answering and judging {len(cases)} question(s) the team has already answered…")
    results = await run_cases(cases)
    return {"summary": summarise(results), "results": results}


async def run_facts(label: str) -> dict:
    from src import service

    cases = load_golden_set()
    print(f"\n[facts] answering {len(cases)} golden question(s)…")
    answers = await service.answer_questions([c.as_question(i) for i, c in enumerate(cases)])
    result = AssessmentResult(
        run_id=uuid.uuid4().hex[:12],
        source_name="golden_set.json",
        language="en",
        questions_found=len(cases),
        answers=answers,
    )
    path = RESULTS / "facts_latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    from eval.dataset import load_answers

    pairs = align(cases, load_answers(path))
    print("[facts] judging fact coverage…")
    judgements = await judge_all(pairs)
    return build_report(label, pairs, judgements)


def format_verdict(house: dict, facts: dict, previous: dict | None, floor: float) -> str:
    lines = ["", "=" * 74, "  THE TWO NUMBERS", "=" * 74]
    h = house["summary"]
    # `accuracy_pct` is the facts report's headline: points scored over points
    # available, which is the number the evaluation history has always tracked.
    facts_score = facts.get("summary", {}).get("accuracy_pct")
    contradictions = facts.get("summary", {}).get("contradiction_cases")

    lines.append(f"  house  agreement {h['agreement']:5.1f}%   form {h['form']:5.1f}%   <- the target")
    lines.append(
        f"         median words: ours {h['median_words_ours']}, "
        f"theirs {h['median_words_theirs']} (reported, not scored)"
    )
    if facts_score is None:
        lines.append("  facts  not run")
    else:
        lines.append(
            f"  facts  {facts_score:5.1f}%"
            + (f"   ({contradictions} contradicted)" if contradictions is not None else "")
            + "                <- the floor"
        )

    if previous:
        p = previous.get("summary", previous)
        moved = []
        for key, name in (("agreement", "agreement"), ("form", "form")):
            if key in p:
                delta = h[key] - p[key]
                moved.append(f"{name} {delta:+.1f}")
        if moved:
            lines.append("")
            lines.append("  against " + previous.get("label", "the previous run") + ": " + ", ".join(moved))
        # From the payload, not from the house summary nested inside it. Read
        # from the wrong level this silently skipped the regression check --
        # the one line in this report that exists to stop something.
        before = previous.get("facts_score")
        if before is not None and facts_score is not None:
            delta = facts_score - before
            lines.append(f"  facts {delta:+.1f}")
            if delta < -floor:
                lines.append("")
                lines.append(
                    f"  ** REGRESSION ** the facts score fell {abs(delta):.1f} points, "
                    f"past the {floor:.1f}-point noise floor."
                )
                lines.append("  Correctness was traded for brevity. That is not the trade.")
    return "\n".join(lines)


async def main_async(args) -> int:
    cases = select(load_house_set(), args.split)
    cases = contamination.screen(cases, [m.question for m in load_memory_set()])
    if cases is None:
        return 1
    if not args.all:
        from scripts.run_house_eval import stratified

        cases = stratified(cases, args.sample, args.seed)

    house = await run_house(cases, args.label)

    # Written before anything is printed. Formatting a summary is not supposed
    # to be able to fail, and it has now cost two completed runs of thirty
    # answers -- once on a judge that refused a schema, once on a constant this
    # module deleted. Everything below here may fail freely.
    out = args.out or (RESULTS / f"both_{args.label.replace(' ', '_')[:40]}.json")
    _write(out, args.label, house, {})
    print(f"\n  answers saved to {out}")

    print()
    print(format_summary(args.label, house["summary"]))

    facts = {}
    if not args.house_only:
        facts = await run_facts(args.label)

    previous = None
    if args.compare and Path(args.compare).exists():
        previous = json.loads(Path(args.compare).read_text(encoding="utf-8"))

    print(format_verdict(house, facts, previous, args.floor))
    _write(out, args.label, house, facts)
    print(f"\n  written to {out}")
    if args.split == "final":
        record_final_run(args.label, args.reason, house["summary"])
        print(f"  the final split has now been looked at {final_runs()} time(s) (eval/final_runs.jsonl)")
    return 0


def _write(out: Path, label: str, house: dict, facts: dict) -> None:
    """Everything this run produced, as far as it has got."""
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "label": label,
        "summary": house["summary"],
        "facts_score": facts.get("summary", {}).get("accuracy_pct"),
        "facts_summary": facts.get("summary"),
        "cases": case_rows(house["results"]),
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="current", help="what changed, for the record")
    parser.add_argument("--sample", type=int, default=30)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--house-only", action="store_true", help="skip the facts floor")
    parser.add_argument("--compare", type=Path, default=None, help="a previous both_*.json")
    parser.add_argument("--floor", type=float, default=NOISE)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--split", choices=["dev", "final", "all"], default="dev", help="of the house set (eval/splits.py)"
    )
    parser.add_argument("--reason", default="", help="why the final split is being looked at (required for it)")
    args = parser.parse_args()
    if args.split == "final" and not args.reason.strip():
        parser.error("--split final needs --reason: every look at it is recorded (eval/final_runs.jsonl)")
    configure_logging()
    return llm.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
