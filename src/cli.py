"""Command-line interface.

python -m src.cli guidelines  policies/*.pdf
python -m src.cli answers     completed/2025-vendor-assessment.docx
python -m src.cli answer      new-assessment.docx --language ar --out filled.json
python -m src.cli stats
python -m src.cli doctor [--network] [--json]
python -m src.cli inspect request <request-id>
python -m src.cli inspect fills [--team T] [--json]
python -m src.cli inspect retention [--days N] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src import answer_memory, diagnostics, fill_audit, llm, retention, service, store
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


def _doctor(network: bool, as_json: bool) -> int:
    checks = diagnostics.doctor(with_network=network)
    for check in checks:
        if as_json:
            print(json.dumps(check.as_dict(), ensure_ascii=False))
            continue
        print(f"{check.status.upper():5} {check.name:30} {check.detail}")
        if check.fix and check.status != diagnostics.OK:
            print(f"      FIX: {check.fix}")
    failed = sum(check.status == diagnostics.FAIL for check in checks)
    if not as_json:
        warned = sum(check.status == diagnostics.WARN for check in checks)
        print(f"\ndoctor: {len(checks)} checks, {failed} failed, {warned} to look at")
    return 1 if failed else 0


def _inspect_request(request_id: str, log: str | None) -> int:
    path = Path(log) if log else None
    try:
        lines = list(diagnostics.request_lines(request_id, path))
    except FileNotFoundError as error:
        print(f"no log at {error.filename}", file=sys.stderr)
        print("  FIX: pass --log <file>, or set SERVER_LOG_PATH to where the server's output goes", file=sys.stderr)
        return 1
    if not lines:
        print(f"no line carries request_id={request_id}", file=sys.stderr)
        print("  FIX: check the ID (it is in the error response and its X-Request-ID header)", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


def _schema_behind() -> int:
    """1, said, when the database is older than this code; 0 when the read-only commands can open it.

    They read through the app's own connection, which upgrades an older database
    first: an `inspect` against an installation not yet started on new code
    changed its schema (plan 035, found on the user's own data). Asked on a
    read-only connection, as `doctor` asks.
    """
    have, want = diagnostics.schema_version(), len(store.MIGRATIONS)
    if have is None or have >= want:
        return 0
    print(f"the database is at schema version {have}, and this code reads version {want}", file=sys.stderr)
    print("  FIX: start the app once, which upgrades it; then run this again. Nothing was changed.", file=sys.stderr)
    return 1


def _inspect_fills(team: str, as_json: bool) -> int:
    """Fills that wrote answers the review gate holds back, and withdrawn approvals left released (plan 029)."""
    if _schema_behind():
        return 1
    fills, released = fill_audit.held_fills(team), fill_audit.released_by_withdrawal(team)
    if as_json:
        print(json.dumps({"fills": [vars(f) for f in fills], "released": [vars(r) for r in released]}, indent=2))
    else:
        print("\n".join(fill_audit.report(fills, released)))
    return 0


def _inspect_retention(days: int, as_json: bool) -> int:
    """What retention deletes in the next `days` days, by kind and owner, without content (plan 033). Read-only."""
    if _schema_behind():
        return 1
    items = retention.due(within_days=days)
    if as_json:
        print(json.dumps({"retention_days": settings.retention_days, "due": [vars(item) for item in items]}, indent=2))
    else:
        print("\n".join(retention.report(items, days)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """The command line's arguments: one subcommand per job."""
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

    # Read-only, and about the installation rather than a team's work, so without --team.
    doctor = subparsers.add_parser("doctor", help="check that this installation can run (read-only)")
    doctor.add_argument("--network", action="store_true", help="also make one GET to each configured service")
    doctor.add_argument("--json", action="store_true", help="one JSON object per check")
    inspect = subparsers.add_parser("inspect", help="look at what happened (read-only)")
    what = inspect.add_subparsers(dest="what", required=True)
    request = what.add_parser("request", help="the server log's lines for one request ID")
    request.add_argument("request_id")
    request.add_argument("--log", default=None, help="the log file (default: SERVER_LOG_PATH)")
    # A team's work, so --team here: the loop above ran before `inspect` was added.
    fills = what.add_parser("fills", help="fills that wrote answers the review gate holds back (plan 029)")
    fills.add_argument("--team", default=settings.default_team, help="whose fills (default: %(default)s)")
    fills.add_argument("--json", action="store_true", help="the two lists as one JSON object")
    kept = what.add_parser("retention", help="what RETENTION_DAYS deletes in the next N days (plan 033)")
    kept.add_argument("--days", type=int, default=30, help="how far ahead to look (default: %(default)s)")
    kept.add_argument("--json", action="store_true", help="one JSON object")

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


def main(argv: list[str] | None = None) -> int:
    """Run one command; returns the exit status."""
    _use_utf8_console()
    configure_logging()
    args = build_parser().parse_args(argv)

    if args.command == "guidelines":
        return llm.run(_ingest(args.paths, SourceType.GUIDELINE, args.team))
    if args.command == "answers":
        return llm.run(_ingest(args.paths, SourceType.PRIOR_ANSWER, args.team))
    if args.command == "answer":
        return llm.run(_answer(args.path, args.language, args.out, args.team))
    if args.command == "stats":
        return _stats(args.team)
    if args.command == "doctor":
        return _doctor(args.network, args.json)
    if args.command == "inspect" and args.what == "fills":
        return _inspect_fills(args.team, args.json)
    if args.command == "inspect" and args.what == "retention":
        return _inspect_retention(args.days, args.json)
    if args.command == "inspect":
        return _inspect_request(args.request_id, args.log)

    service.clear_knowledge(args.team)
    print(f"Knowledge base cleared for {args.team}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
