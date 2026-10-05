"""Rolling judgements up into the numbers the evaluation report cares about."""

from __future__ import annotations

from statistics import mean, pstdev

from eval.dataset import GoldenCase, ScoredAnswer
from eval.judge import Judgement

MAX_SCORE = 5


def _percentage(scores: list[int]) -> float:
    return 100.0 * sum(scores) / (MAX_SCORE * len(scores)) if scores else 0.0


def _correlation(xs: list[float], ys: list[float]) -> float:
    """Pearson r, or 0.0 when either series is constant.

    Confidence that does not move with correctness is the failure the report
    called a dead signal: mean confidence fell while accuracy fell too, so the
    number carried no information. This is the metric that catches it.
    """
    if len(xs) < 2:
        return 0.0
    sx, sy = pstdev(xs), pstdev(ys)
    if sx == 0 or sy == 0:
        return 0.0
    mx, my = mean(xs), mean(ys)
    covariance = mean([(x - mx) * (y - my) for x, y in zip(xs, ys)])
    return covariance / (sx * sy)


def build_report(
    label: str,
    pairs: list[tuple[GoldenCase, ScoredAnswer | None]],
    judgements: list[Judgement],
) -> dict:
    """Per-case detail plus the category and calibration roll-ups."""
    cases: list[dict] = []
    for (case, answer), judgement in zip(pairs, judgements):
        expected = len(case.expected_core_facts)
        covered = len({n for n in judgement.covered_fact_numbers if 1 <= n <= expected})
        cases.append(
            {
                "test_id": case.test_id,
                "category": case.category,
                "score": judgement.score,
                "facts_expected": expected,
                "facts_covered": covered,
                "contradicted_facts": [n for n in judgement.contradicted_fact_numbers if 1 <= n <= expected],
                "unverified_claims": judgement.unverified_claims,
                "confidence": answer.confidence if answer else 0.0,
                "needs_review": answer.needs_review if answer else True,
                "citations": answer.citations if answer else [],
                "sources": answer.sources if answer else [],
                "justification": judgement.justification,
                "answer": answer.answer if answer else "",
            }
        )

    by_category: dict[str, dict] = {}
    for entry in cases:
        bucket = by_category.setdefault(entry["category"], {"n": 0, "scores": []})
        bucket["n"] += 1
        bucket["scores"].append(entry["score"])

    scores = [entry["score"] for entry in cases]
    confidences = [entry["confidence"] for entry in cases]
    expected_total = sum(entry["facts_expected"] for entry in cases)
    covered_total = sum(entry["facts_covered"] for entry in cases)

    return {
        "label": label,
        "cases": cases,
        "summary": {
            "n": len(cases),
            "points": sum(scores),
            "points_available": MAX_SCORE * len(cases),
            "accuracy_pct": round(_percentage(scores), 1),
            "fact_recall_pct": round(100.0 * covered_total / expected_total, 1) if expected_total else 0.0,
            "contradiction_cases": sum(1 for entry in cases if entry["contradicted_facts"]),
            "unverified_claim_cases": sum(1 for entry in cases if entry["unverified_claims"]),
            "needs_review": sum(1 for entry in cases if entry["needs_review"]),
            "mean_confidence": round(mean(confidences), 3) if confidences else 0.0,
            "confidence_spread": round(pstdev(confidences), 3) if len(confidences) > 1 else 0.0,
            "distinct_confidences": len(set(confidences)),
            "confidence_score_correlation": round(_correlation(confidences, [float(s) for s in scores]), 3),
        },
        "categories": {
            name: {
                "n": bucket["n"],
                "accuracy_pct": round(_percentage(bucket["scores"]), 1),
                "points": sum(bucket["scores"]),
            }
            for name, bucket in sorted(by_category.items())
        },
    }


def format_report(report: dict) -> str:
    """The report as a terminal table."""
    summary = report["summary"]
    lines = [
        f"\n=== {report['label']} ===",
        f"{summary['points']}/{summary['points_available']} points   "
        f"accuracy {summary['accuracy_pct']}%   fact recall {summary['fact_recall_pct']}%",
        f"needs review {summary['needs_review']}/{summary['n']}   "
        f"contradicts a golden fact in {summary['contradiction_cases']} answers   "
        f"unverified specifics in {summary['unverified_claim_cases']}",
        f"confidence mean {summary['mean_confidence']}  spread {summary['confidence_spread']}  "
        f"distinct {summary['distinct_confidences']}  r(confidence, score) {summary['confidence_score_correlation']}",
        "",
        f"{'category':<26}{'n':>4}{'accuracy':>11}",
    ]
    for name, bucket in report["categories"].items():
        lines.append(f"{name:<26}{bucket['n']:>4}{bucket['accuracy_pct']:>10.1f}%")

    lines.append("")
    lines.append(f"{'case':<10}{'score':>6}{'facts':>9}{'conf':>7}  category")
    for entry in report["cases"]:
        facts = f"{entry['facts_covered']}/{entry['facts_expected']}"
        lines.append(
            f"{entry['test_id']:<10}{entry['score']:>6}{facts:>9}{entry['confidence']:>7.2f}  {entry['category']}"
        )
    return "\n".join(lines)


def format_comparison(baseline: dict, candidate: dict) -> str:
    """Per-case deltas between two reports, in the shape the human review used."""
    baseline_scores = {entry["test_id"]: entry["score"] for entry in baseline["cases"]}
    lines = [
        f"\n=== {candidate['label']} vs {baseline['label']} ===",
        f"{baseline['summary']['accuracy_pct']}%  ->  {candidate['summary']['accuracy_pct']}%   "
        f"({candidate['summary']['accuracy_pct'] - baseline['summary']['accuracy_pct']:+.1f})",
        "",
        f"{'case':<10}{'base':>6}{'new':>6}{'delta':>7}  category",
    ]
    regressions = wins = 0
    for entry in candidate["cases"]:
        before = baseline_scores.get(entry["test_id"])
        if before is None:
            continue
        delta = entry["score"] - before
        regressions += delta < 0
        wins += delta > 0
        marker = "" if delta == 0 else ("  <-- regression" if delta < 0 else "  <-- win")
        lines.append(f"{entry['test_id']:<10}{before:>6}{entry['score']:>6}{delta:>+7}  {entry['category']}{marker}")
    lines.append(f"\n{wins} wins, {regressions} regressions")
    return "\n".join(lines)
