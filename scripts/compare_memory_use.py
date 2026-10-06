"""Which wiring of the answer memory actually answers better.

    python -m scripts.compare_memory_use --sample 45

Four ways of using the same 698 remembered answers, run over the *same*
questions so the comparison is paired -- question difficulty varies far more
than the wirings do, and comparing different samples would measure the sample.

  off        the memory is indexed but not retrieved. The control.
  evidence   retrieved and shown to the drafter as another source, with the
             prompt it already had.
  precedence a procedure: when a remembered answer covers the question, start
             from it, verify it against our policies, and say so if the two
             disagree. The policies remain the authority -- they are what the
             team wrote the remembered answer from in the first place, so an
             answer that contradicts them is drift rather than a new standard.
  reuse      the same procedure, plus: when a remembered answer is clearly the
             same question, keep its wording and change only what the new
             question requires.

Measured over 135 held-out questions the nearest remembered answer is reusable
as it stands 91% of the time above 0.90 similarity and 21% of the time below
0.75 -- so the interesting question is not whether the memory helps but whether
the drafter can tell those apart. `precedence` and `reuse` differ only in how
strongly they lean on it when it does match.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.config import PROJECT_ROOT, configure_logging, settings
from src import llm
from src import prompts
from eval.house import (
    form_score,
    judge_agreement,
    load_house_set,
    summarise,
    HouseResult,
)
from scripts.run_house_eval import stratified

RESULTS = PROJECT_ROOT / "eval" / "results"

# The rule as it stands: the memory shapes the wording, the policies decide the
# facts. Everything below replaces exactly this sentence.
CURRENT = (
    "- Previous answers are the strongest signal for wording and level of detail — reuse "
    "their phrasing and structure when the question matches. Guidelines take precedence "
    "when the two disagree, because a previous answer may be out of date."
)

PRECEDENCE = (
    "- A PREVIOUS ANSWER is what this organisation actually said to a real assessor, and it "
    "is the best evidence of how we answer. When one covers the question, work from it:\n"
    "  1. Read what we said before.\n"
    "  2. Check it against OUR POLICY above. The policies are what the team wrote that answer "
    "from, so they remain the authority -- a previous answer that conflicts with them is out "
    "of date rather than a new position.\n"
    "  3. If they agree, answer as we answered, adjusted to what this question actually asks.\n"
    "  4. If they conflict, follow the policy, and say plainly in `rationale` that a previous "
    "answer said otherwise. Somebody needs to reconcile the two, and that is not your job.\n"
    "  A previous answer to a *different* question is not evidence about this one. Questions "
    "about neighbouring controls -- an incident-response drill and a business-continuity "
    "drill, a DPA with a customer and a DPA with a sub-processor -- read alike and are not "
    "the same question."
)

REUSE = PRECEDENCE + (
    "\n  When the previous question is plainly the same question, keep the answer's own "
    "words and change only what this question needs changed. It was written by the people "
    "who own the subject and reviewed before it went to a customer; rewriting it in your own "
    "words adds risk and no value."
)

WIRINGS = {
    "off": (CURRENT, 0),
    "evidence": (CURRENT, None),
    "precedence": (PRECEDENCE, None),
    "reuse": (REUSE, None),
}


async def run_one(name: str, cases) -> dict:
    from src import service

    replacement, top_k = WIRINGS[name]
    original_prompt = prompts.ANSWER_SYSTEM
    original_k = settings.top_k_prior_answers
    try:
        prompts.ANSWER_SYSTEM = original_prompt.replace(CURRENT, replacement, 1)
        assert name == "off" or replacement == CURRENT or CURRENT not in prompts.ANSWER_SYSTEM, (
            "the rule being replaced was not found in the prompt"
        )
        # The graph reads the module attribute at call time, so the swap has to
        # reach `src.graph.nodes` too -- it imported the name directly.
        from src.graph import nodes

        nodes.ANSWER_SYSTEM = prompts.ANSWER_SYSTEM
        if top_k is not None:
            settings.top_k_prior_answers = top_k

        print(f"\n[{name}] answering {len(cases)}…")
        answers = await service.answer_questions([c.as_question(i) for i, c in enumerate(cases)])
    finally:
        prompts.ANSWER_SYSTEM = original_prompt
        from src.graph import nodes

        nodes.ANSWER_SYSTEM = original_prompt
        settings.top_k_prior_answers = original_k

    results = []
    for case, produced in zip(cases, answers):
        score, shape = form_score(case, produced.answer)
        results.append(
            HouseResult(
                case=case,
                answer=produced.answer,
                register=score,
                shape=shape,
                confidence=produced.confidence,
                needs_review=produced.needs_review,
            )
        )
    print(f"[{name}] judging…")
    for result, verdict in zip(results, await asyncio.gather(*(judge_agreement(r.case, r.answer) for r in results))):
        result.agreement = verdict

    used = sum(1 for produced in answers if any(e.source_type.value == "prior_answer" for e in produced.evidence))
    return {
        "name": name,
        "summary": summarise(results),
        "cited_memory": used,
        "results": results,
    }


async def main_async(args) -> int:
    cases = stratified(load_house_set(), args.sample, args.seed)
    print(f"{len(cases)} questions, each answered {len(args.wirings)} ways")

    runs = {}
    for name in args.wirings:
        runs[name] = await run_one(name, cases)
        # Written as each finishes: four answering passes is the expensive part
        # of this script and a crash in the fourth should not cost the first
        # three.
        (RESULTS / "memory_wirings.json").write_text(
            json.dumps(
                {
                    n: {
                        "summary": r["summary"],
                        "cited_memory": r["cited_memory"],
                        "cases": [
                            {
                                "test_id": x.case.test_id,
                                "question": x.case.question,
                                "team": x.case.answer,
                                "answer": x.answer,
                                "verdict": x.agreement.verdict if x.agreement else "",
                                "score": x.agreement.score if x.agreement else 0,
                                "words": x.shape.words,
                                "confidence": x.confidence,
                            }
                            for x in r["results"]
                        ],
                    }
                    for n, r in runs.items()
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )

    print("\n" + "=" * 78)
    print("  FOUR WAYS OF USING THE SAME REMEMBERED ANSWERS")
    print("=" * 78)
    print(
        f"  {'wiring':12s} {'agreement':>10s} {'form':>7s} {'contradicts':>12s} "
        f"{'cited memory':>13s} {'median words':>13s}"
    )
    for name, run in runs.items():
        s = run["summary"]
        print(
            f"  {name:12s} {s['agreement']:9.1f}% {s['form']:6.1f}% "
            f"{s['verdicts'].get('contradicts', 0):12d} "
            f"{run['cited_memory']:13d} {s['median_words_ours']:13.0f}"
        )

    # Paired: same question, did the wiring beat the control on it?
    if "off" in runs and len(runs) > 1:
        base = {r.case.test_id: (r.agreement.score if r.agreement else 0) for r in runs["off"]["results"]}
        print("\n  against `off`, question by question:")
        for name, run in runs.items():
            if name == "off":
                continue
            better = worse = same = 0
            for r in run["results"]:
                mine = r.agreement.score if r.agreement else 0
                theirs = base.get(r.case.test_id, 0)
                better += mine > theirs
                worse += mine < theirs
                same += mine == theirs
            print(f"    {name:12s} better on {better:3d}   worse on {worse:3d}   unchanged {same:3d}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=45)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--wirings", nargs="+", default=list(WIRINGS))
    args = parser.parse_args()
    configure_logging()
    return llm.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
