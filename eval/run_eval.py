"""Run and score the golden question set.

    python -m eval.run_eval answer  --out eval/results/current.json
    python -m eval.run_eval score   eval/results/current.json
    python -m eval.run_eval score   eval/results/current.json --baseline ../../previous_results/old_system_cyber_real_testset.pdf.answers.json
    python -m eval.run_eval history

`answer` asks the live system every question in the golden set and writes the
result in the same shape the archived runs use. `score` grades any such file,
so the current system and both archived runs are measured on one rubric by one
judge.

Every scored run is appended to `eval/history.jsonl` with the settings that
produced it; `history` prints them. See eval/history.py.
"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from src import llm
from src.config import PROJECT_ROOT, configure_logging
from src.models import AssessmentResult

from eval.dataset import DEFAULT_GOLDEN_SET, align, load_answers, load_golden_set
from eval.history import HISTORY_PATH, format_history, load as load_history, record, save_configuration
from eval.judge import judge_all
from eval.report import build_report, format_comparison, format_report
from eval.retrieval import DEFAULT_TARGETS, as_dict, build_plans, load_targets, measure_all
from eval.retrieval import format_report as retrieval_report

RESULTS_DIR = PROJECT_ROOT / "eval" / "results"


async def answer_golden_set(golden_path: Path, out: Path) -> None:
    """Ask the live system every golden question and write the answers."""
    from src import service

    cases = load_golden_set(golden_path)
    questions = [case.as_question(index) for index, case in enumerate(cases)]
    print(f"Answering {len(questions)} golden questions...")

    answers = await service.answer_questions(questions)
    result = AssessmentResult(
        run_id=uuid.uuid4().hex[:12],
        source_name=Path(golden_path).name,
        language="en",
        questions_found=len(questions),
        answers=answers,
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    # Beside the answers, so a later scoring run records what produced them
    # rather than whatever happens to be set when it is graded.
    save_configuration(out)
    print(f"Run {result.run_id} written to {out}")


async def score(
    answers_path: Path, golden_path: Path, label: str, baseline_path: Path | None, notes: str = ""
) -> None:
    cases = load_golden_set(golden_path)

    async def report_for(path: Path, name: str) -> dict:
        pairs = align(cases, load_answers(path))
        missing = [case.test_id for case, answer in pairs if answer is None]
        if missing:
            print(f"warning: {name} has no answer for {', '.join(missing)}")
        return build_report(name, pairs, await judge_all(pairs))

    candidate = await report_for(answers_path, label)
    print(format_report(candidate))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = RESULTS_DIR / f"{label}.report.json"
    report_path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")

    # Recorded before anything else is printed or compared: a scoring run costs
    # real tokens, and losing the record to a broken pipe or a crash on the way
    # out means paying for it twice.
    record(candidate, golden_set=Path(golden_path).name, answers_file=str(answers_path), notes=notes)
    print(f"\nFull report written to {report_path}")
    print(f"Recorded in {HISTORY_PATH}")

    if baseline_path:
        baseline = await report_for(baseline_path, baseline_path.stem)
        print(format_report(baseline))
        print(format_comparison(baseline, candidate))


async def score_retrieval(
    targets_path: Path, golden_path: Path, label: str, out: Path | None,
    baseline: Path | None, plans_path: Path | None = None,
) -> None:
    """Measure retrieval on its own. No judge, no drafting, no tokens to speak of."""
    targets = load_targets(targets_path, golden=load_golden_set(golden_path))
    print(f"Measuring retrieval on {len(targets)} golden questions...")

    # Hold the expanded queries fixed across a sweep. The planner is an LLM and
    # rewrites them slightly every run, which moved recall by several points
    # between two passes of an identical system — more than most of the
    # settings worth testing.
    plans = None
    if plans_path:
        if plans_path.exists():
            plans = json.loads(plans_path.read_text(encoding="utf-8"))
            print(f"Reusing the query plans in {plans_path}")
        else:
            plans = await build_plans(targets)
            plans_path.parent.mkdir(parents=True, exist_ok=True)
            plans_path.write_text(json.dumps(plans, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Wrote query plans to {plans_path}")

    results = await measure_all(targets, plans=plans)
    payload = as_dict(label, results)
    print(retrieval_report(payload["summary"], payload["categories"], results))

    destination = out or (RESULTS_DIR / f"{label}.retrieval.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Written to {destination}")

    if baseline and baseline.exists():
        previous = json.loads(baseline.read_text(encoding="utf-8"))
        print(f"\nagainst {previous.get('label', baseline.stem)}")
        print("-" * 62)
        for key in ("document_recall_pct", "clause_recall_pct",
                    "selection_loss_documents", "never_retrieved_documents",
                    "cases_fully_covered", "mrr"):
            before = previous["summary"].get(key)
            after = payload["summary"].get(key)
            if isinstance(before, (int, float)) and isinstance(after, (int, float)):
                print(f"  {key:32s} {before:>8} -> {after:<8} {after - before:+.3g}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eval", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN_SET, help="golden set JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    answer = subparsers.add_parser("answer", help="answer the golden set with the live system")
    answer.add_argument("--out", type=Path, default=RESULTS_DIR / "current.json")

    scoring = subparsers.add_parser("score", help="judge an answers file against the golden set")
    scoring.add_argument("answers", type=Path)
    scoring.add_argument("--label", default=None, help="name for this run in the report")
    scoring.add_argument("--baseline", type=Path, default=None, help="a second answers file to compare against")
    scoring.add_argument("--notes", default="", help="a line recorded with this run in the history")

    subparsers.add_parser("history", help="show every recorded run")

    retrieval = subparsers.add_parser(
        "retrieval", help="score retrieval alone, without asking a model to write anything")
    retrieval.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
    retrieval.add_argument("--label", default="retrieval")
    retrieval.add_argument("--out", type=Path, default=None,
                           help="write the full per-case result here")
    retrieval.add_argument("--baseline", type=Path, default=None,
                           help="a previous retrieval result file to compare against")
    retrieval.add_argument("--plans", type=Path, default=None,
                           help="reuse (or create) a fixed set of expanded queries, so a sweep "
                                "measures the setting rather than the planner's variation")

    return parser


def main() -> int:
    configure_logging()
    args = build_parser().parse_args()

    if args.command == "answer":
        llm.run(answer_golden_set(args.golden, args.out))
    elif args.command == "history":
        print(format_history(load_history()))
    elif args.command == "retrieval":
        llm.run(score_retrieval(args.targets, args.golden, args.label, args.out,
                                    args.baseline, args.plans))
    else:
        label = args.label or args.answers.stem
        llm.run(score(args.answers, args.golden, label, args.baseline, args.notes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
