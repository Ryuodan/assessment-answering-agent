"""ARCH-ERROR: every error the application raises belongs to src/errors.py's hierarchy.

    ARCH-ERROR  a class in src/ derives from a built-in exception without
                deriving from AppError; or src/ builds an HTTPException

Private classes (`_Unspliceable`) are internal control flow and exempt, as is
src/errors.py, where the hierarchy is rooted. The AppError family is found by
name across src/: a class is in it when one of its bases (by its last name,
so `forms.UnsupportedForm` counts) is AppError or already in it. Existing
exceptions to the rule are allow-listed against a TD item (plan 004).
"""

from __future__ import annotations

import ast
from pathlib import Path

from harness.report import Violation

ROOT_CLASS = "AppError"
ERRORS_MODULE = "src/errors.py"
BUILTIN_EXCEPTIONS = {
    "BaseException",
    "Exception",
    "ArithmeticError",
    "AttributeError",
    "IOError",
    "KeyError",
    "LookupError",
    "NotImplementedError",
    "OSError",
    "RuntimeError",
    "TypeError",
    "ValueError",
}


def _last_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def check(root: Path, allowed: dict[str, str]) -> tuple[list[Violation], set[str]]:
    """Violations, and which allow-list entries were matched."""
    trees: dict[str, ast.Module] = {}
    for path in sorted((root / "src").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        trees[rel] = ast.parse(path.read_text(encoding="utf-8"), filename=rel)

    bases_of: dict[str, set[str]] = {}
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases_of.setdefault(node.name, set()).update(_last_name(b) for b in node.bases)
    family = {ROOT_CLASS}
    grew = True
    while grew:
        grew = False
        for name, bases in bases_of.items():
            if name not in family and bases & family:
                family.add(name)
                grew = True

    violations: list[Violation] = []
    used: set[str] = set()
    for rel, tree in trees.items():
        module = rel.removesuffix(".py").removesuffix("/__init__").replace("/", ".")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _last_name(node.func).endswith("HTTPException"):
                violations.append(
                    Violation(
                        "ARCH-ERROR",
                        rel,
                        node.lineno,
                        "builds an HTTPException",
                        "raise an AppError subclass from src/errors.py with a code (e.g. "
                        '`NotFound("No run.", code="run_not_found")`); the handler in src/api.py answers for it',
                    )
                )
            if rel == ERRORS_MODULE or not isinstance(node, ast.ClassDef) or node.name.startswith("_"):
                continue
            bases = {_last_name(b) for b in node.bases}
            if bases & BUILTIN_EXCEPTIONS and not bases & family:
                qualified = f"{module}.{node.name}"
                if qualified in allowed:
                    used.add(qualified)
                    continue
                violations.append(
                    Violation(
                        "ARCH-ERROR",
                        rel,
                        node.lineno,
                        f"{node.name} is an exception outside the AppError hierarchy",
                        "derive it from the fitting class in src/errors.py (Invalid, NotFound, Unprocessable, ...) "
                        "and give it a `code`; keep the built-in base too if callers catch it by that",
                    )
                )
    return violations, used
