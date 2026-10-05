"""The gate: run every check task in order and say which failed.

    uv run poe check               # all of them; exit 1 if any failed
    uv run poe check --fail-fast   # stop at the first failure

"Done" means this passes. Each task's own output is streamed as it runs; the
summary at the end names each failed task with the command that fixes it or
the place to look.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time

# Order matters only for speed of feedback: cheap checks first, tests last.
GATE: list[tuple[str, str]] = [
    ("fmt", "run `uv run poe format`, then review the diff"),
    ("lint", "fix each file:line above; `uv run python -m ruff check --fix .` repairs the auto-fixable ones"),
    ("types", "each TYPES-* line above has its own FIX"),
    ("arch", "each ARCH-* line above has its own FIX"),
    ("docs", "each DOCS-* line above has its own FIX"),
    ("rules", "a check's own test failed: read it before trusting that check's verdict"),
    ("test", "read the first failure above; rerun one with `uv run python -m pytest path::name -x`"),
]


def run_task(name: str) -> tuple[bool, float]:
    print(f"\n=== {name} ===", flush=True)
    started = time.perf_counter()
    completed = subprocess.run([sys.executable, "-m", "poethepoet", name], check=False)
    return completed.returncode == 0, time.perf_counter() - started


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fail-fast", action="store_true", help="stop at the first failing task")
    args = parser.parse_args(argv)

    results: list[tuple[str, bool, float, str]] = []
    for name, fix in GATE:
        passed, seconds = run_task(name)
        results.append((name, passed, seconds, fix))
        if not passed and args.fail_fast:
            break

    print("\n=== check summary ===")
    for name, passed, seconds, fix in results:
        print(f"  {'PASS' if passed else 'FAIL'}  {name:<6} {seconds:6.1f} s")
        if not passed:
            print(f"        FIX: {fix}")
    not_run = [name for name, _ in GATE[len(results) :]]
    if not_run:
        print(f"  not run (--fail-fast): {', '.join(not_run)}")

    failed = [name for name, passed, *_ in results if not passed]
    if failed or not_run:
        print(f"check: FAILED ({', '.join(failed)})", file=sys.stderr)
        return 1
    print("check: all tasks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
