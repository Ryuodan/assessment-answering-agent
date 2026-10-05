"""One format for every violation a harness check reports.

    ARCH-SIZE src/api.py:1: module has 2001 lines; the limit is 400
      FIX: split it, or ...

Rule ID first so a failure can be searched for; `file:line` so an editor can
jump to it; the FIX line so the reader knows what to do without asking.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Violation:
    rule: str
    path: str
    line: int
    message: str
    fix: str

    def render(self) -> str:
        return f"{self.rule} {self.path}:{self.line}: {self.message}\n  FIX: {self.fix}"


def rel(path: Path) -> str:
    """A path as the repository names it: relative to the root, forward slashes."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def finish(name: str, violations: list[Violation]) -> int:
    """Print the violations and a one-line verdict; return the exit code."""
    for violation in sorted(violations, key=lambda v: (v.path, v.line, v.rule)):
        print(violation.render())
    if violations:
        print(f"{name}: {len(violations)} violation(s)", file=sys.stderr)
        return 1
    print(f"{name}: ok")
    return 0
