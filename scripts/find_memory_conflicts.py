"""Find remembered answers that disagree with each other.

    python -m scripts.find_memory_conflicts
    python -m scripts.find_memory_conflicts --threshold 0.85 --json out.json

Every pair of remembered answers whose questions embed close enough to be the
same question, where the two answers open with opposite verdicts. Embeddings
only -- no model calls -- so this is cheap enough to run over the whole memory
and cheap enough to run again after every import.

Lexical matching finds none of these. The pair that started this -- "yes, under
Data Privacy and Data Officer" against "we do not have a DPO, but it falls under
the Cybersecurity team" -- shares almost no wording with its twin, and the two
questions are phrased differently as well.

What comes out is a *shortlist for a person*, not a verdict. Similarity proposes
the pair; only somebody who knows the organisation can say whether two questions
really ask the same thing, and the measured evidence is that similarity alone
cannot: "business-continuity drills annually" and "incident-response drill at
least annually" embed at 0.793 and are different controls, while "signed a DPA
with sub-processors" and "DPAs with all your sub-processors" embed at 0.808 and
are one question.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.config import PROJECT_ROOT, configure_logging  # noqa: E402
from src.embeddings import get_embeddings  # noqa: E402
from src.memory import SAME_QUESTION, disagree, verdict_of  # noqa: E402

MEMORY = PROJECT_ROOT / "eval" / "answer_memory.json"


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=float, default=SAME_QUESTION)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()
    configure_logging()

    rows = json.loads(MEMORY.read_text(encoding="utf-8"))
    answered = [r for r in rows if verdict_of(r["answer"])]
    print(f"{len(rows)} remembered answers")
    print(f"  {len(answered)} open with a verdict, so can disagree with another")
    print(f"  {len(rows) - len(answered)} state something else -- a period, a name, a description")

    client = get_embeddings()
    print(f"\nembedding {len(answered)} questions…")
    vectors = client.embed_documents([r["question"][:900] for r in answered])

    print(f"comparing every pair at {args.threshold:.2f}…")
    conflicts = []
    for i in range(len(answered)):
        for j in range(i + 1, len(answered)):
            if not disagree(answered[i]["answer"], answered[j]["answer"]):
                continue
            score = cosine(vectors[i], vectors[j])
            if score >= args.threshold:
                conflicts.append((score, answered[i], answered[j]))

    conflicts.sort(key=lambda row: -row[0])
    print(f"\n{len(conflicts)} pair(s) that a person should look at\n")
    for score, a, b in conflicts[:20]:
        print(f"  [{score:.3f}]")
        print(f"    {a['test_id']}  {a['question'][:84]}")
        print(f"        -> {a['answer'][:96]}")
        print(f"        in {a['file'][:60]}")
        print(f"    {b['test_id']}  {b['question'][:84]}")
        print(f"        -> {b['answer'][:96]}")
        print(f"        in {b['file'][:60]}")
        print()

    if len(conflicts) > 20:
        print(f"  … and {len(conflicts) - 20} more")

    if args.json:
        args.json.write_text(json.dumps([
            {"similarity": round(s, 3), "a": a, "b": b} for s, a, b in conflicts
        ], ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nwritten to {args.json}")

    # How the count moves with the threshold, because the threshold is a
    # judgement and the person choosing it should see what it costs.
    print("\n  at other thresholds:")
    for cut in (0.95, 0.92, 0.90, 0.88, 0.85, 0.80):
        n = sum(1 for s, _, _ in conflicts if s >= cut)
        if cut < args.threshold:
            n = sum(
                1 for i in range(len(answered)) for j in range(i + 1, len(answered))
                if disagree(answered[i]["answer"], answered[j]["answer"])
                and cosine(vectors[i], vectors[j]) >= cut
            )
        print(f"    >= {cut:.2f}   {n:4d} pair(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
