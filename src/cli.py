"""Command-line interface.

python -m src.cli guidelines  policies/*.pdf
python -m src.cli answers     completed/2025-vendor-assessment.docx
python -m src.cli answer      new-assessment.docx --language ar --out filled.json
python -m src.cli stats
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src import answer_memory, llm, service
from src.config import configure_logging, settings
from src.models import SourceType


async def _ingest(paths: list[str], source_type: SourceType, team: str) -> int:
    failed = 0
    for path in paths:
        result = await service.ingest(path, source_type, team_id=team)
        if result.error:
            failed += 1
            print(f"✗ {result.source_name}: {result.error}")
        elif result.duplicate_of:
            print(f"– {result.source_name}: skipped, identical to '{result.duplicate_of}'")
        else:
            detail = (
                f"{result.qa_pairs_found} Q/A pairs" if result.qa_pairs_found else f"{result.chunks_indexed} chunks"
            )
            print(f"✓ {result.source_name}: {detail}")

    # Every imported pair is now an answer-memory entry, and what each one
    # supersedes or contradicts is a sweep of model calls. It runs here rather
    # than being left for whoever next opens the memory page, because importing
    # from the command line is exactly when nobody is looking at that page.
    if source_type is SourceType.PRIOR_ANSWER:
        found = await answer_memory.scan_pending(limit=500, team_id=team)
        conflicts = [f for f in found if f.needs_a_person]
        if found:
            print()
            print(
                f"Answer memory: {len(found) - len(conflicts)} answer(s) superseded, "
                f"{len(conflicts)} disagreement(s) raised for a person."
            )

    return 1 if failed else 0


async def _answer(path: str, language: str | None, out: str | None, team: str) -> int:
    result = await service.answer_assessment(path, language=language, team_id=team)

    print(
        f"\n{result.source_name} — {result.questions_found} questions, "
        f"{result.needs_review_count} need review ({result.language})\n"
    )

    for answered in result.answers:
        flag = "⚠ " if answered.needs_review else "  "
        print(f"{flag}[{answered.question.id}] {answered.question.text}")
        print(f"   → {answered.answer or '(no answer)'}")
        print(
            f"   confidence {answered.confidence:.2f} · "
            f"sources: {', '.join(e.source_name for e in answered.evidence) or 'none'}\n"
        )

    if out:
        Path(out).write_text(result.model_dump_json(indent=2), encoding="utf-8")
        print(f"Written to {out}")

    return 0


def _stats(team: str) -> int:
    stats = service.knowledge_stats(team)
    print(
        f"{stats['total_chunks']} chunks — "
        f"{stats['guideline_chunks']} guideline, {stats['prior_answer_chunks']} previous answers"
    )
    for source in stats["sources"]:
        print(f"  {source['source_type']:<13} {source['name']} ({source['chunks']})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="assessment-answer", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    guidelines = subparsers.add_parser("guidelines", help="index guideline documents")
    guidelines.add_argument("paths", nargs="+")

    answers = subparsers.add_parser("answers", help="index previously answered assessments")
    answers.add_argument("paths", nargs="+")

    answer = subparsers.add_parser("answer", help="answer a new assessment")
    answer.add_argument("path")
    answer.add_argument(
        "--language",
        choices=["ar", "en"],
        default=None,
        help="force the output language (default: match each question)",
    )
    answer.add_argument("--out", default=None, help="write the full result as JSON to this path")

    subparsers.add_parser("stats", help="show what is indexed")
    subparsers.add_parser("clear", help="empty the knowledge base")

    # Every team has its own knowledge base and answer memory. Left out, the
    # command acts for the team the system was set up for.
    for sub in subparsers.choices.values():
        sub.add_argument(
            "--team", default=settings.default_team, help="the team whose knowledge base this is (default: %(default)s)"
        )

    return parser


def _use_utf8_console() -> None:
    """Stop a Windows console codepage from killing a run mid-batch.

    The default Windows console encoding cannot represent Arabic file names or
    the tick this CLI prints, and `print` raises rather than degrading — so
    indexing forty-nine policies died on the first Arabic one, after the work
    was already done. Replacement characters in the terminal are the right
    trade here; the data itself is written as UTF-8 regardless.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    _use_utf8_console()
    configure_logging()
    args = build_parser().parse_args()

    if args.command == "guidelines":
        return llm.run(_ingest(args.paths, SourceType.GUIDELINE, args.team))
    if args.command == "answers":
        return llm.run(_ingest(args.paths, SourceType.PRIOR_ANSWER, args.team))
    if args.command == "answer":
        return llm.run(_answer(args.path, args.language, args.out, args.team))
    if args.command == "stats":
        return _stats(args.team)

    service.clear_knowledge(args.team)
    print(f"Knowledge base cleared for {args.team}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
