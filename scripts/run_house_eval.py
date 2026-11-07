"""Score the system against what the security team actually wrote.

    python -m scripts.run_house_eval --all
    python -m scripts.run_house_eval --set in-memory --sample 300
    python -m scripts.run_house_eval --sample 30 --out eval/results/house_baseline.json
    python -m scripts.run_house_eval --all --split final --reason "confirming plan NNN"

The house set (`--set held-out`) is split by questionnaire into `dev`, to tune
against, and `final`, to confirm a change (eval/splits.py, plan 013). `--split`
defaults to dev; every final run needs a reason and is recorded. Before
anything is spent, the cases are checked for contamination
(eval/contamination.py), and a case whose answering or judging failed is
counted apart from the scores.

`eval/run_eval.py` grades the facts set: is the answer right and complete.
This grades the team's own answers: would they have written it. Two numbers
come out, and they are meant to be read as a pair -- see eval/house.py for why
optimising either one alone is what produced the gap this set exists to close.

**Two sets, and the difference between them is the whole point.**

`--set held-out` (the default) runs the five questionnaires that are *not* in
the answer memory, with the memory switched on. The corpus is split by file, so
these are five customers whose forms the memory has never seen: this is the
estimate of what happens when the next questionnaire arrives.

`--set in-memory` runs the memory's own questions, with the memory switched on.
The exact pair is in the corpus, so this measures reproduction rather than
generalisation -- a ceiling. It is worth having for two reasons: a low score
here means the pipeline cannot even reuse what it holds, and the distance
between the two numbers is what generalisation costs.

Both runs report the same things, plus two diagnostics that stop either number
being read for more than it says: how close the nearest remembered question was
(`twin`), and -- for the memory set -- whether the answer actually cited the
entry for the question being asked.

The sample is stratified by source file so a thirty-case run still covers every
questionnaire rather than the first two.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.config import PROJECT_ROOT, configure_logging
from src import llm
from eval import contamination
from eval.house import (
    answer_cases,
    case_rows,
    format_summary,
    judge_cases,
    load_house_set,
    load_memory_set,
    nearest_in_memory,
    summarise,
)
from eval.splits import final_runs, record_final_run, select

RESULTS = PROJECT_ROOT / "eval" / "results"

SETS = {
    "held-out": (load_house_set, "the five questionnaires the memory has never seen"),
    "in-memory": (load_memory_set, "the memory's own questions, answered again"),
}


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
    out.write_text(
        json.dumps(
            {
                "label": label,
                "graded": False,
                "cases": case_rows(results),
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )


async def answer_and_score(cases, label: str, out: Path | None, memory_cases=None) -> dict:
    from src import answer_memory

    # Computed before the answering, so a long run cannot lose it, and cheap:
    # one embedding pass over the questions on each side.
    print("Measuring how close the memory already is to each question…")
    twins = await nearest_in_memory(cases, memory_cases or [])

    # Matched on the question text rather than on an id: the entry ids were
    # assigned by the import, and the evaluation rows carry the questionnaire's own numbering.
    by_question = {entry.question.strip(): entry.entry_id for entry in answer_memory.entries(limit=100_000)}

    print(f"Answering {len(cases)} question(s) the team has already answered…")
    results = await answer_cases(cases, twins, by_question)

    # Written before the judging, not after. Answering is the minutes and the
    # money; judging is neither. The first run of this harness lost thirty
    # answers because the judge refused one schema, and the raw answers had
    # never been put anywhere.
    if out:
        _write_raw(out, label, results)
        print(f"  answers saved to {out} (before judging, so a judge failure costs nothing)")

    print("Judging agreement against the team's own answers…")
    await judge_cases(results)

    summary = summarise(results)
    print()
    print(format_summary(label, summary))

    worst = sorted(
        (r for r in results if r.agreement and r.agreement.verdict != "unanswerable"),
        key=lambda r: (r.agreement.score, r.register),
    )[:5]
    print("\n  The five furthest from what the team wrote:\n")
    for r in worst:
        print(
            f"    [{r.case.test_id}] {r.agreement.verdict}  "
            f"form {r.register:.0%}  {r.shape.words}w vs {len(r.case.answer.split())}w  "
            f"nearest remembered question {r.twin:.2f}" + ("  (cited its own entry)" if r.found_own_answer else "")
        )
        print(f"      Q      {r.case.question[:96]}")
        print(f"      team   {r.case.answer[:120]}")
        print(f"      ours   {' '.join(r.answer.split())[:170]}")
        print(f"      judge  {r.agreement.note[:120]}\n")

    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "label": label,
                    "summary": summary,
                    "cases": case_rows(results),
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        print(f"\n  written to {out}")
    return summary


def main() -> int:
    import eval as evaluation

    evaluation.plan_afresh()  # no kept search plans (plan 034's review)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--set",
        dest="which",
        choices=sorted(SETS),
        default="held-out",
        help="held-out (real-world) or in-memory (reproduction ceiling)",
    )
    parser.add_argument("--sample", type=int, default=30, help="how many cases (default 30)")
    parser.add_argument("--all", action="store_true", help="every case in the set")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--label", default="current")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--split",
        choices=["dev", "final", "all"],
        default="dev",
        help="of the house set: dev to tune against (default), final to confirm a change (eval/splits.py)",
    )
    parser.add_argument("--reason", default="", help="why the final split is being looked at (required for it)")
    args = parser.parse_args()
    if args.split == "final" and not args.reason.strip():
        parser.error("--split final needs --reason: every look at it is recorded (eval/final_runs.jsonl)")

    configure_logging()
    load, description = SETS[args.which]
    cases = load()
    if args.which == "held-out":
        cases = select(cases, args.split)
        description += f"; the {args.split} split"
    chosen = cases if args.all else stratified(cases, args.sample, args.seed)
    # The memory's questions are the comparison set either way: for the
    # held-out run they say how much the memory already knows about each
    # question, and for the memory run the nearest is the question itself.
    memory_cases = load_memory_set()
    print(f"{args.which}: {description}")
    print(
        f"  {len(cases)} cases from {len({c.file for c in cases})} questionnaires; "
        f"running {len(chosen)}. Answer memory holds {len(memory_cases)}."
    )
    if args.which == "in-memory":
        print("  Reproduction, not generalisation: every answer is already in the corpus.")
    # The memory set is the memory, so only the house set is checked against it.
    remembered = [m.question for m in memory_cases] if args.which == "held-out" else None
    chosen = contamination.screen(chosen, remembered)
    if chosen is None:
        return 1
    summary = llm.run(answer_and_score(chosen, args.label, args.out, memory_cases))
    if args.which == "held-out" and args.split == "final":
        record_final_run(args.label, args.reason, summary)
        print(f"\n  the final split has now been looked at {final_runs()} time(s) (eval/final_runs.jsonl)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
