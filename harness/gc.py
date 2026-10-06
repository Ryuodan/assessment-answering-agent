"""Garbage-collection candidates: what a cleanup round should look at.

    uv run poe gc

Not a gate: it lists candidates for a person or an agent to judge, one per
line, `KIND path:line: what`. Kinds:

    UNUSED      a top-level function or class in src/ that nothing references
    TEST-ONLY   one only tests reference
    DUPLICATE   a block of 8+ lines that appears more than once in src/
    SUPPRESS    a `noqa` or `type: ignore` with no reason written beside it
    OVERSIZE    a module over the size limit (its ceiling is in the allow-list)
    STALE-PATH  a doc names a repository path, in backticks, that does not exist
                (plans are records, so they are not read)
    TODO        a TODO, FIXME or XXX in src/

References are found by name across src/, tests/, scripts/, eval/ and the pages
in src/static/, so a name used only dynamically can show as unused: read it
before deleting it. The round's plan records what was done with each.
"""

from __future__ import annotations

import ast
import re
import sys
from collections import defaultdict
from pathlib import Path

from harness.arch import MAX_LINES, counted_lines
from harness.report import ROOT

WINDOW = 8
_PATH_IN_BACKTICKS = re.compile(r"`((?:src|tests|harness|scripts|eval|docs)/[A-Za-z0-9_./-]+)`")
_SUPPRESSION = re.compile(r"#\s*(noqa(?::\s*[A-Z0-9, ]+)?|type:\s*ignore(?:\[[^\]]*\])?)(.*)$")


def _sources(root: Path) -> dict[Path, str]:
    files = [p for d in ("src", "tests", "scripts", "eval", "harness") for p in (root / d).rglob("*.py")]
    files += list((root / "src" / "static").glob("*.*"))
    return {path: path.read_text(encoding="utf-8", errors="replace") for path in files}


def unused(root: Path, texts: dict[Path, str]) -> list[str]:
    out: list[str] = []
    for path in sorted((root / "src").rglob("*.py")):
        tree = ast.parse(texts[path])
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if node.name.startswith("__") or any(
                isinstance(d, ast.Call) and getattr(d.func, "attr", "") in ("get", "post", "put", "patch", "delete")
                for d in node.decorator_list
            ):
                continue
            word = re.compile(rf"\b{re.escape(node.name)}\b")
            elsewhere = [p for p, text in texts.items() if p != path and word.search(text)]
            here = len(word.findall(texts[path])) - 1
            rel = path.relative_to(root).as_posix()
            if not here and not elsewhere:
                out.append(f"UNUSED {rel}:{node.lineno}: {node.name}")
            elif not here and all(p.relative_to(root).parts[0] == "tests" for p in elsewhere):
                out.append(f"TEST-ONLY {rel}:{node.lineno}: {node.name}")
    return out


def duplicates(root: Path, texts: dict[Path, str]) -> list[str]:
    seen: dict[tuple[str, ...], list[tuple[str, int]]] = defaultdict(list)
    for path in sorted((root / "src").rglob("*.py")):
        lines = [line.strip() for line in texts[path].splitlines()]
        rel = path.relative_to(root).as_posix()
        for start in range(len(lines) - WINDOW + 1):
            window = tuple(lines[start : start + WINDOW])
            meaningful = [line for line in window if line and not line.startswith(("#", '"""', "'''"))]
            if len(meaningful) >= WINDOW - 1 and len(set(meaningful)) > 3:
                seen[window].append((rel, start + 1))
    out: list[str] = []
    reported: set[tuple[str, int]] = set()
    for places in seen.values():
        if len(places) > 1 and not any(place in reported for place in places):
            first, *rest = places
            out.append(
                f"DUPLICATE {first[0]}:{first[1]}: same {WINDOW} lines at " + ", ".join(f"{p}:{n}" for p, n in rest)
            )
            # Overlapping windows of one duplicated block would repeat it line by line.
            reported.update((p, n + k) for p, n in places for k in range(WINDOW))
    return out


def suppressions(root: Path, texts: dict[Path, str]) -> list[str]:
    out: list[str] = []
    for path, text in texts.items():
        if path.suffix != ".py":
            continue
        rel = path.relative_to(root).as_posix()
        for number, line in enumerate(text.splitlines(), start=1):
            match = _SUPPRESSION.search(line)
            if match and not re.search(r"[A-Za-z]{3,}", match.group(2).lstrip(" -:#")):
                out.append(f"SUPPRESS {rel}:{number}: {match.group(1).strip()} without a reason")
    return out


def oversized(root: Path) -> list[str]:
    out: list[str] = []
    for path in sorted((root / "src").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        lines = counted_lines(rel, path.read_text(encoding="utf-8"))
        if lines > MAX_LINES:
            out.append(f"OVERSIZE {rel}:1: {lines} lines")
    return out


def stale_paths(root: Path) -> list[str]:
    out: list[str] = []
    docs = [p for p in root.glob("*.md")] + list((root / "docs").rglob("*.md"))
    for doc in sorted(docs):
        rel = doc.relative_to(root).as_posix()
        # Plans are records: a path in one names the tree as it was, or an alternative not taken.
        if rel.startswith(("docs/generated/", "docs/plans/active/", "docs/plans/completed/")):
            continue
        for number, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), start=1):
            for mentioned in _PATH_IN_BACKTICKS.findall(line):
                target = mentioned.rstrip(".,:;")
                if "*" in target or "<" in target or "..." in target:
                    continue
                if not (root / target).exists() and not (root / target.split("::")[0]).exists():
                    out.append(f"STALE-PATH {rel}:{number}: `{target}` does not exist")
    return out


def todos(root: Path, texts: dict[Path, str]) -> list[str]:
    out: list[str] = []
    for path in sorted((root / "src").rglob("*.py")):
        for number, line in enumerate(texts[path].splitlines(), start=1):
            if re.search(r"\b(TODO|FIXME|XXX)\b", line):
                out.append(f"TODO {path.relative_to(root).as_posix()}:{number}: {line.strip()[:80]}")
    return out


def candidates(root: Path = ROOT) -> list[str]:
    texts = _sources(root)
    return (
        unused(root, texts)
        + duplicates(root, texts)
        + suppressions(root, texts)
        + oversized(root)
        + stale_paths(root)
        + todos(root, texts)
    )


def main() -> int:
    found = candidates()
    print("\n".join(found))
    kinds: dict[str, int] = defaultdict(int)
    for line in found:
        kinds[line.split(" ", 1)[0]] += 1
    print(
        "gc: " + (", ".join(f"{count} {kind}" for kind, count in sorted(kinds.items())) or "nothing"), file=sys.stderr
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
