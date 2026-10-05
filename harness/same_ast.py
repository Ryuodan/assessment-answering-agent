"""Prove a mechanical change left every Python file's syntax tree unchanged.

    python -m harness.same_ast                 # working tree against HEAD
    python -m harness.same_ast --commit abc123 # one commit against its parent

For changes that must not change behaviour: reformatting, auto-fixes that only
touch layout. Compares `ast.dump` of each changed `.py` file before and after.
Docstrings are compared after `inspect.cleandoc` and per-line right-stripping,
because a formatter re-indents them and trims trailing spaces, which changes
the string's value but not what any code does with it.
"""

from __future__ import annotations

import argparse
import ast
import inspect
import subprocess
import sys

from harness.report import ROOT, Violation, finish

_DOCSTRING_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _normalised(source: str) -> str:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, _DOCSTRING_OWNERS) and node.body:
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                cleaned = inspect.cleandoc(first.value.value)
                first.value.value = "\n".join(line.rstrip() for line in cleaned.splitlines())
    return ast.dump(tree, include_attributes=False)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout


def _show(rev: str, path: str) -> str | None:
    completed = subprocess.run(
        ["git", "show", f"{rev}:{path}"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False
    )
    return completed.stdout if completed.returncode == 0 else None


def compare(before_rev: str, after_rev: str | None) -> tuple[int, list[Violation]]:
    """Compare changed .py files; `after_rev=None` means the working tree."""
    diff_args = ["diff", "--name-only", "--diff-filter=M", before_rev]
    if after_rev:
        diff_args.append(after_rev)
    paths = [p for p in _git(*diff_args).splitlines() if p.endswith(".py")]
    violations: list[Violation] = []
    for path in paths:
        before = _show(before_rev, path)
        after = _show(after_rev, path) if after_rev else (ROOT / path).read_text(encoding="utf-8")
        if before is None or after is None:
            continue
        if _normalised(before) != _normalised(after):
            violations.append(
                Violation(
                    "SAME-AST",
                    path,
                    1,
                    "the syntax tree changed, so this is not a purely mechanical change",
                    f"inspect `git diff {before_rev} {after_rev or ''} -- {path}` and move the behavioural "
                    "part into its own commit",
                )
            )
    return len(paths), violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--commit", help="check this commit against its parent instead of the working tree")
    args = parser.parse_args(argv)
    if args.commit:
        compared, violations = compare(f"{args.commit}^", args.commit)
    else:
        compared, violations = compare("HEAD", None)
    print(f"compared {compared} changed Python file(s)")
    return finish("same-ast", violations)


if __name__ == "__main__":
    sys.exit(main())
