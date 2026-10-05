"""ARCH-LOG: application code logs events through src/logs.py.

    ARCH-LOG  a module in src/ makes a logger with `logging.getLogger` instead
              of `get_logger`; or an event logger is called with something
              other than a dotted lower-case event name written as a literal

`src/logs.py` itself is exempt: it is where the standard library is wrapped.
Modules that still log prose are allow-listed against TD-028 (plan 005) and
leave the list when converted.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from harness.report import Violation

OWNER = "src/logs.py"
LEVELS = {"debug", "info", "warning", "error", "exception"}
EVENT_NAME = r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+"


def _event_loggers(tree: ast.Module) -> set[str]:
    """Module-level names bound to `get_logger(...)` or `logs.get_logger(...)`."""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if called == "get_logger":
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def check(root: Path, allowed: dict[str, str]) -> tuple[list[Violation], set[str]]:
    event_name = re.compile(EVENT_NAME)
    violations: list[Violation] = []
    used: set[str] = set()
    for path in sorted((root / "src").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel == OWNER:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        stdlib = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "getLogger"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "logging"
        ]
        if stdlib and rel in allowed:
            used.add(rel)
        elif stdlib:
            violations += [
                Violation(
                    "ARCH-LOG",
                    rel,
                    line,
                    "makes a standard-library logger, which logs prose",
                    "use `logger = get_logger(__name__)` from src.logs and log events: "
                    '`logger.info("area.what_happened", field=value)`',
                )
                for line in stdlib
            ]
        loggers = _event_loggers(tree)
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in LEVELS
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in loggers
            ):
                continue
            first = node.args[0] if node.args else None
            if (
                len(node.args) == 1
                and isinstance(first, ast.Constant)
                and isinstance(first.value, str)
                and event_name.fullmatch(first.value)
            ):
                continue
            violations.append(
                Violation(
                    "ARCH-LOG",
                    rel,
                    node.lineno,
                    "an event logger called without a literal dotted event name (or with positional arguments)",
                    "name the event as a literal, `area.what_happened`, and pass the facts as keywords: "
                    '`logger.warning("storage.over_limit", person=email, used_mb=812)`',
                )
            )
    return violations, used
