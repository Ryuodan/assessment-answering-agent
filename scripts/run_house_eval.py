"""Score the system against what the security team actually wrote.

    python -m scripts.run_house_eval --sample 30
    python -m scripts.run_house_eval --all --out eval/results/house_baseline.json
    python -m scripts.run_house_eval --score eval/results/house_baseline.json

`eval/run_eval.py` grades the facts set: is the answer right and complete.
This grades the house set: would the team have written it. Two numbers come
out, and they are meant to be read as a pair -- see eval/house.py for why
optimising either one alone is what produced the gap this set exists to close.

The sample is stratified by source file so a thirty-case run still covers all
five questionnaires rather than the first two.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.config import PROJECT_ROOT, configure_logging  # noqa: E402
from eval.house import (  # noqa: E402
    HouseResult, format_summary, judge_agreement, load_house_set, register_score, summarise,
)

RESULTS = PROJECT_ROOT / "eval" / "results"


def stratified(cases, n: int, seed: int):
    """`n` cases spread across the source files, not the first `n` alphabetically."""
    if n >= len(cases):
        return list(cases)
    by_file = defaultdict(list)
    for case in cases:
        by_file[case.file].append(case)
    rng = random.Random(seed)
    for group in by_file.values():
        rng.shuffle(group)

    chosen, files = [], sorted(by_file)
    while len(chosen) < n:
        took = False
        for name in files:
            if by_file[name] and len(chosen) < n:
                chosen.append(by_file[name].pop())
                took = True
        if not took:
            break
    return sorted(chosen, key=lambda c: c.test_id)


def _write_raw(out: Path, label: str, results) -> None:
    """Just the answers, for when the grading half has not run or has failed."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "label": label,
        "graded": False,
        "cases": [
            {
                "test_id": r.case.test_id, "file": r.case.file, "question": r.case.question,
                "reference": r.case.answer, "answer": r.answer,
                "form": round(r.register, 3), "words": r.shape.words,
                "confidence": r.confidence, "needs_review": r.needs_review,
            }
            for r in results
        ],
    }, ensure_ascii=False, indent=1), encoding="utf-8")


async def answer_and_score(cases, label: str, out: Path | None) -> None:
    from src import service

    print(f"Answering {len(cases)} question(s) the team has already answered…")
    answers = await service.answer_questions([c.as_question(i) for i, c in enumerate(cases)])

    results = []
    for case, produced in zip(cases, answers):
        score, shape = register_score(case, produced.answer)
        results.append(HouseResult(
            case=case, answer=produced.answer, register=score, shape=shape,
            confidence=produced.confidence, needs_review=produced.needs_review,
        ))

    # Written before the judging, not after. Answering is the minutes and the
    # money; judging is neither. The first run of this harness lost thirty
    # answers because the judge refused one schema, and the raw answers had
    # never been put anywhere.
    if out:
        _write_raw(out, label, results)
        print(f"  answers saved to {out} (before judging, so a judge failure costs nothing)")

    print("Judging agreement against the team's own answers…")
    verdicts = await asyncio.gather(*(judge_agreement(r.case, r.answer) for r in results))
    for result, verdict in zip(results, verdicts):
        result.agreement = verdict

    summary = summarise(results)
    print()
    print(format_summary(label, summary))

    worst = sorted(
        (r for r in results if r.agreement and r.agreement.verdict != "unanswerable"),
        key=lambda r: (r.agreement.score, r.register),
    )[:5]
    print("\n  The five furthest from what the team wrote:\n")
    for r in worst:
        print(f"    [{r.case.test_id}] {r.agreement.verdict}  "
              f"form {r.register:.0%}  {r.shape.words}w vs {len(r.case.answer.split())}w")
        print(f"      Q      {r.case.question[:96]}")
        print(f"      team   {r.case.answer[:120]}")
        print(f"      ours   {' '.join(r.answer.split())[:170]}")
        print(f"      judge  {r.agreement.note[:120]}\n")

    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "label": label,
            "summary": summary,
            "cases": [
                {
                    "test_id": r.case.test_id, "file": r.case.file,
                    "question": r.case.question, "reference": r.case.answer, "answer": r.answer,
                    "form": round(r.register, 3), "words": r.shape.words,
                    "opens_with_verdict": r.shape.opens_with_verdict,
                    "cites_a_clause": r.shape.cites_a_clause, "hedges": r.shape.hedges,
                    "verdict": r.agreement.verdict if r.agreement else "",
                    "agreement_score": r.agreement.score if r.agreement else 0,
                    "note": r.agreement.note if r.agreement else "",
                    "confidence": r.confidence, "needs_review": r.needs_review,
                }
                for r in results
            ],
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n  written to {out}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=30, help="how many cases (default 30)")
    parser.add_argument("--all", action="store_true", help="every case in the set")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--label", default="current")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    configure_logging()
    cases = load_house_set()
    chosen = cases if args.all else stratified(cases, args.sample, args.seed)
    print(f"House set: {len(cases)} cases from "
          f"{len({c.file for c in cases})} questionnaires; running {len(chosen)}.")
    asyncio.run(answer_and_score(chosen, args.label, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
