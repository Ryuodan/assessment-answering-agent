"""mypy --strict, with a baseline of the errors that existed when it was adopted.

    uv run poe types              # fail on any error not in the baseline
    uv run poe types-baseline     # drop fixed errors from the baseline (never adds)

The code base predates type checking, so strict mode reports errors that
cannot all be fixed at once. They are recorded in `harness/mypy-baseline.txt`;
a new error anywhere fails, and an error that has been fixed must be removed
from the baseline, so the file only shrinks. Entries are matched without line
numbers (file, error code, message), because unrelated edits move lines.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass

from harness.report import ROOT, Violation, finish

BASELINE = ROOT / "harness" / "mypy-baseline.txt"
_ERROR = re.compile(r"^(?P<path>[^:]+):(?P<line>\d+): error: (?P<message>.*?)(?:\s+\[(?P<code>[\w-]+)\])?$")
_LINE_REFERENCE = re.compile(r"\bon line \d+\b")
# Usually the environment, not the code: a fresh clone once failed here because
# an optional extra was not installed (D-009).
_MISSING_MODULE_FIX = (
    "the module is not installed in this environment: run `uv sync --inexact` (the dev group carries every "
    "optional extra); if it is a new dependency, add it to pyproject.toml and run `uv lock`"
)


@dataclass(frozen=True)
class TypeError_:
    path: str
    line: int
    code: str
    message: str

    @property
    def key(self) -> str:
        message = _LINE_REFERENCE.sub("on line N", self.message)
        return f"{self.path}: [{self.code}] {message}"


def run_mypy() -> tuple[list[TypeError_], str]:
    completed = subprocess.run(
        [sys.executable, "-m", "mypy", "--no-error-summary", "--show-error-codes", "--no-pretty"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    errors: list[TypeError_] = []
    for raw in completed.stdout.splitlines():
        match = _ERROR.match(raw.strip())
        if match:
            errors.append(
                TypeError_(
                    path=match["path"].replace("\\", "/"),
                    line=int(match["line"]),
                    code=match["code"] or "misc",
                    message=match["message"],
                )
            )
    # mypy exits 1 for type errors and 2 for a crash or a configuration error.
    trouble = completed.stderr.strip() if completed.returncode not in (0, 1) else ""
    return errors, trouble


def load_baseline() -> Counter[str]:
    if not BASELINE.exists():
        return Counter()
    lines = BASELINE.read_text(encoding="utf-8").splitlines()
    return Counter(line for line in lines if line and not line.startswith("#"))


def write_baseline(entries: Counter[str]) -> None:
    header = [
        "# mypy --strict errors that existed when type checking was adopted (plan 001).",
        "# Only ever shrinks: `uv run poe types-baseline` removes fixed entries and never adds.",
        "# Format: path: [error-code] message   (no line numbers; duplicates repeat)",
    ]
    body = sorted(entries.elements())
    BASELINE.write_text("\n".join(header + body) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--shrink", action="store_true", help="remove fixed errors from the baseline")
    parser.add_argument("--init", action="store_true", help="create the baseline (refuses if one exists)")
    args = parser.parse_args(argv)

    errors, trouble = run_mypy()
    if trouble:
        print(trouble)
        print("types: mypy did not run cleanly", file=sys.stderr)
        print("  FIX: read mypy's message above; usually a [tool.mypy] setting in pyproject.toml or a syntax error")
        return 1

    current = Counter(error.key for error in errors)
    baseline = load_baseline()

    if args.init:
        if BASELINE.exists():
            print("types: a baseline already exists; it may only shrink (use --shrink)", file=sys.stderr)
            return 1
        write_baseline(current)
        print(f"types: baseline created with {sum(current.values())} error(s)")
        return 0
    if args.shrink:
        kept = baseline & current
        removed = sum(baseline.values()) - sum(kept.values())
        write_baseline(kept)
        print(f"types: removed {removed} fixed error(s); {sum(kept.values())} remain in the baseline")
        return 0

    print(f"mypy: {sum(current.values())} error(s), {sum(baseline.values())} in the baseline")
    return finish("types", judge(errors, baseline))


def judge(errors: list[TypeError_], baseline: Counter[str]) -> list[Violation]:
    """New errors (beyond the baseline's count for their key) and fixed ones."""
    violations: list[Violation] = []
    allowance = Counter(baseline)
    for error in errors:
        if allowance[error.key] > 0:
            allowance[error.key] -= 1
            continue
        violations.append(
            Violation(
                "TYPES-NEW",
                error.path,
                error.line,
                f"[{error.code}] {error.message}",
                _MISSING_MODULE_FIX
                if error.code == "import-not-found"
                else "fix the type error; the baseline is for errors that predate plan 001, never for new ones",
            )
        )
    fixed = +allowance
    if fixed:
        violations.append(
            Violation(
                "TYPES-FIXED",
                "harness/mypy-baseline.txt",
                1,
                f"{sum(fixed.values())} baseline error(s) no longer occur",
                "run `uv run poe types-baseline` to remove them, and commit the smaller baseline",
            )
        )
    return violations


if __name__ == "__main__":
    sys.exit(main())
