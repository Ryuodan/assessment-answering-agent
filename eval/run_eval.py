"""Run the gold question set and emit a scoreable JSON report."""
import asyncio, json
from src.service import answer_assessment

async def main(assessment_path: str, out: str, runs: int = 2) -> None:
    reports = []
    for run in range(runs):
        result = await answer_assessment(assessment_path)
        reports.append({
            "run": run,
            "answers": [
                {
                    "id": a.question.id,
                    "answer": a.answer,
                    "confidence": a.confidence,
                    "needs_review": a.needs_review,
                    "citations": a.citations,
                    "evidence": [
                        {"locator": e.locator, "score": e.score,
                         "part": e.part, "parts": e.parts}
                        for e in a.evidence
                    ],
                }
                for a in result.answers
            ],
        })
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(reports, handle, ensure_ascii=False, indent=2)