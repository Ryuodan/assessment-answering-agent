"""Can the system answer a certification question now that the profile says so?

    python -m scripts.probe_certifications

Fourteen answers in the team's own questionnaires mention a certification, and
they were the sharpest thing this system got wrong: told nothing about which
certifications were held, it answered "No. T2 does not hold any
information-security certifications" at 0.85 confidence, on its way into a
customer's file.

They were set aside deliberately as a probe -- the class of question that no
prompt could fix because the fact was not in the corpus. This runs them and
grades the answers against what the team actually wrote, so "does the profile
fix it" has a number rather than an opinion.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.config import PROJECT_ROOT, configure_logging  # noqa: E402
from src import llm  # noqa: E402
from eval.house import HouseCase, judge_agreement  # noqa: E402

MENTIONS = re.compile(r"iso\s*/?\s*(iec)?\s*27001|soc\s*2|pci\s*dss|certif", re.I)


def certification_questions() -> list[HouseCase]:
    """Every remembered answer that turns on a certification."""
    rows = []
    for name in ("answer_memory.json", "house_set.json"):
        rows.extend(json.loads((PROJECT_ROOT / "eval" / name).read_text(encoding="utf-8")))
    return [
        HouseCase(
            test_id=row["test_id"], question=row["question"], answer=row["answer"],
            file=row.get("file", ""), section=row.get("section", ""),
        )
        for row in rows
        if MENTIONS.search(row["question"]) or MENTIONS.search(row["answer"])
    ]


async def main_async(args) -> int:
    from src import service

    cases = certification_questions()
    if args.limit:
        cases = cases[: args.limit]
    print(f"{len(cases)} question(s) turning on a certification\n")

    answers = await service.answer_questions(
        [c.as_question(i) for i, c in enumerate(cases)]
    )
    verdicts = await asyncio.gather(*(
        judge_agreement(c, a.answer) for c, a in zip(cases, answers)
    ))

    denials = 0
    for case, produced, verdict in zip(cases, answers, verdicts):
        denied = bool(re.search(
            r"\b(do(es)? not (hold|have)|no .{0,20}certificat|not certified|"
            r"holds no|without any certificat)\b", produced.answer, re.I))
        denials += denied
        mark = "DENIES" if denied else verdict.verdict
        print(f"  [{mark:12s}] conf {produced.confidence:.2f}  {case.question[:70]}")
        print(f"      team  {case.answer[:96]}")
        print(f"      ours  {' '.join(produced.answer.split())[:130]}")
        print()

    from collections import Counter
    counts = Counter(v.verdict for v in verdicts)
    agreed = sum(1 for v in verdicts if v.verdict in ("same", "broader"))
    print("=" * 74)
    print(f"  agreed with the team on {agreed}/{len(cases)} ({agreed/len(cases):.0%})")
    print(f"  wrongly denied a certification: {denials}")
    print(f"  verdicts: " + ", ".join(f"{k} {v}" for k, v in counts.most_common()))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    configure_logging()
    return llm.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
