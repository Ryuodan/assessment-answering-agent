"""Adopt everything already indexed as answer memory, then sweep it for conflicts.

    python -m scripts.build_answer_memory --rescan --limit 40   # a sample, to see the rate
    python -m scripts.build_answer_memory --rescan              # the lot

The 698 imported answers were indexed before the memory kept rows of its own, so
the first half of this gives each of them one. The second half is the sweep that
runs by itself after an upload or an approval: every entry that has not been
compared against the rest is, at 0.80 similarity with a model confirming each
pair, and what it finds is marked or raised.

Imported answers carry no date -- the questionnaires record none -- so nothing
here can supersede anything. Every finding is therefore a contradiction, which
is exactly the queue this is meant to produce: pairs where we told two customers
opposite things and nothing says which is current.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src import answer_memory  # noqa: E402
from src.config import configure_logging  # noqa: E402
from src import llm  # noqa: E402


async def main_async(args) -> int:
    answer_memory.ensure_synced()
    stats = answer_memory.stats()
    print(f"  {stats['entries']} remembered answer(s): {stats['by_origin']}")
    print(f"  {stats['unscanned']} not yet compared, {stats['open_conflicts']} open conflict(s)\n")

    if args.sync_only:
        return 0

    if args.rescan:
        print(f"  putting {answer_memory.reopen_for_scan(origin=args.origin)} entries "
              "back in the queue")

    started = time.monotonic()
    done = 0
    while True:
        batch = min(args.batch, args.limit - done) if args.limit else args.batch
        if batch <= 0:
            break
        before = len(answer_memory.pending(limit=10_000))
        found = await answer_memory.scan_pending(limit=batch, concurrency=args.concurrency)
        waiting = len(answer_memory.pending(limit=10_000))
        # What actually moved, not what was asked for: the last batch is short,
        # and an entry the model could not be asked about stays in the queue.
        done += before - waiting
        for finding in found:
            print(f"  [{finding.kind:12s}] {finding.because}")
            print(f"      other: {finding.other_question[:90]}")
        print(f"  ... {done} compared, {waiting} left, "
              f"{len(answer_memory.conflicts())} conflict(s) so far "
              f"({time.monotonic() - started:.0f}s)")
        if not waiting:
            break
        if before == waiting:
            # A whole pass moved nothing, so the next one will not either:
            # whatever it needs -- the embedding host, the model -- is down.
            print("  nothing moved in that pass; stopping. Run it again later.")
            break

    print("\n" + "=" * 74)
    final = answer_memory.stats()
    print(f"  {final['entries']} entries, {final['superseded']} superseded, "
          f"{final['open_conflicts']} conflict(s) waiting for a person")
    for conflict in answer_memory.conflicts():
        first, second = answer_memory.get(conflict.entry_id), answer_memory.get(conflict.other_id)
        if first is None or second is None:
            continue
        print(f"\n  {first.question[:88]}")
        print(f"    {first.from_file}: {first.answer[:100]}")
        print(f"    {second.from_file}: {second.answer[:100]}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="stop after this many (0 = all)")
    parser.add_argument("--batch", type=int, default=25)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--sync-only", action="store_true")
    parser.add_argument("--rescan", action="store_true",
                        help="compare entries that have already been compared once")
    parser.add_argument("--origin", default="", help="with --rescan: only this origin")
    args = parser.parse_args()
    configure_logging()
    return llm.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
