"""Command-line interface.

    python -m src.cli guidelines  policies/*.pdf
    python -m src.cli answers     completed/2025-vendor-assessment.docx
    python -m src.cli answer      new-assessment.docx --language ar --out filled.json
    python -m src.cli stats
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from src import service
from src.config import configure_logging
from src.models import SourceType


async def _ingest(paths: list[str], source_type: SourceType) -> int:
    failed = 0
    for path in paths:
        result = await service.ingest(path, source_type)
        if result.error:
            failed += 1
            print(f"✗ {result.source_name}: {result.error}")
        else:
            detail = f"{result.qa_pairs_found} Q/A pairs" if result.qa_pairs_found else f"{result.chunks_indexed} chunks"
            print(f"✓ {result.source_name}: {detail}")
    return 1 if failed else 0


async def _answer(path: str, language: str | None, out: str | None) -> int:
    result = await service.answer_assessment(path, language=language)

    print(f"\n{result.source_name} — {result.questions_found} questions, "
          f"{result.needs_review_count} need review ({result.language})\n")

    for answered in result.answers:
        flag = "⚠ " if answered.needs_review else "  "
        print(f"{flag}[{answered.question.id}] {answered.question.text}")
        print(f"   → {answered.answer or '(no answer)'}")
        print(f"   confidence {answered.confidence:.2f} · "
              f"sources: {', '.join(e.source_name for e in answered.evidence) or 'none'}\n")

    if out:
        Path(out).write_text(result.model_dump_json(indent=2), encoding="utf-8")
        print(f"Written to {out}")

    return 0


def _stats() -> int:
    stats = service.knowledge_stats()
    print(f"{stats['total_chunks']} chunks — "
          f"{stats['guideline_chunks']} guideline, {stats['prior_answer_chunks']} previous answers")
    for source in stats["sources"]:
        print(f"  {source['source_type']:<13} {source['name']} ({source['chunks']})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="assessment-answer", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    guidelines = subparsers.add_parser("guidelines", help="index guideline documents")
    guidelines.add_argument("paths", nargs="+")

    answers = subparsers.add_parser("answers", help="index previously answered assessments")
    answers.add_argument("paths", nargs="+")

    answer = subparsers.add_parser("answer", help="answer a new assessment")
    answer.add_argument("path")
    answer.add_argument("--language", choices=["ar", "en"], default=None,
                        help="force the output language (default: match each question)")
    answer.add_argument("--out", default=None, help="write the full result as JSON to this path")

    subparsers.add_parser("stats", help="show what is indexed")
    subparsers.add_parser("clear", help="empty the knowledge base")

    return parser


def main() -> int:
    configure_logging()
    args = build_parser().parse_args()

    if args.command == "guidelines":
        return asyncio.run(_ingest(args.paths, SourceType.GUIDELINE))
    if args.command == "answers":
        return asyncio.run(_ingest(args.paths, SourceType.PRIOR_ANSWER))
    if args.command == "answer":
        return asyncio.run(_answer(args.path, args.language, args.out))
    if args.command == "stats":
        return _stats()

    service.clear_knowledge()
    print("Knowledge base cleared.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
