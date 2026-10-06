"""Quality grades per layer: the same five measures every cleanup round.

    uv run poe cov       # writes .coverage.json (gitignored), takes the suite's time
    uv run poe grades    # prints the table for the round's record

For each layer of harness/layers.toml:

    coverage     statement coverage of its modules, from .coverage.json
                 A >= 90%, B >= 80%, C >= 70%, D below
    size         modules over 400 lines (counted as ARCH-SIZE counts them)
                 A none, B one, C two or three, D more
    suppressions `noqa` and `type: ignore` comments in its modules
                 A none, B up to 3, C up to 8, D more
    duplication  blocks of 8+ identical lines found twice (harness/gc.py), once per layer
                 A none, B one, C two or three, D more
    docstrings   public top-level functions and classes with a docstring
                 A >= 90%, B >= 75%, C >= 60%, D below

The thresholds are fixed so rounds can be compared; change them only with a
decision, and re-grade the previous round when you do. The round's record
(docs/quality/) adds each layer's gaps in words.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from harness.arch import MAX_LINES, counted_lines
from harness.gc import _sources, duplicates
from harness.layers import Layering, module_name
from harness.report import ROOT

COVERAGE_FILE = ROOT / ".coverage.json"

# (measured value, letter)
Grade = tuple[float, str]


@dataclass(frozen=True)
class Row:
    layer: str
    modules: int
    lines: int
    coverage: Grade
    oversized: Grade
    suppressions: Grade
    duplication: Grade
    docstrings: Grade


def _letter(value: float, bands: tuple[float, float, float], higher_is_better: bool) -> str:
    a, b, c = bands
    if higher_is_better:
        return "A" if value >= a else "B" if value >= b else "C" if value >= c else "D"
    return "A" if value <= a else "B" if value <= b else "C" if value <= c else "D"


def grade(root: Path = ROOT, coverage_file: Path = COVERAGE_FILE) -> list[Row]:
    layering = Layering.load(root / "harness" / "layers.toml")
    coverage: dict[str, tuple[int, int]] = {}
    if coverage_file.exists():
        for path, data in json.loads(coverage_file.read_text(encoding="utf-8"))["files"].items():
            summary = data["summary"]
            coverage[Path(path).as_posix()] = (summary["covered_lines"], summary["num_statements"])

    texts = _sources(root)
    by_layer: dict[str, list[Path]] = defaultdict(list)
    for path in sorted((root / "src").rglob("*.py")):
        layer = layering.layer_of(module_name(path, root))
        if layer:
            by_layer[layer].append(path)

    # A duplicated block counts once for each layer it appears in.
    shared: dict[str, int] = defaultdict(int)
    for line in duplicates(root, texts):
        places = re.findall(r"(src/[\w/]+\.py):\d+", line)
        for layer in {layering.layer_of(module_name(root / place, root)) for place in places}:
            if layer:
                shared[layer] += 1

    rows: list[Row] = []
    for layer in layering.order:
        paths = by_layer.get(layer, [])
        rels = [p.relative_to(root).as_posix() for p in paths]
        covered = sum(coverage.get(r, (0, 0))[0] for r in rels)
        statements = sum(coverage.get(r, (0, 0))[1] for r in rels)
        oversized = sum(1 for p, r in zip(paths, rels) if counted_lines(r, texts[p]) > MAX_LINES)
        suppressions = sum(len(re.findall(r"#\s*(?:noqa|type:\s*ignore)", texts[p])) for p in paths)
        duplicated = shared.get(layer, 0)
        public = documented = 0
        for p in paths:
            for node in ast.parse(texts[p]).body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith(
                    "_"
                ):
                    public += 1
                    documented += bool(ast.get_docstring(node))
        coverage_pct = 100 * covered / statements if statements else 0.0
        docstring_pct = 100 * documented / public if public else 100.0
        rows.append(
            Row(
                layer=layer,
                modules=len(paths),
                lines=sum(len(texts[p].splitlines()) for p in paths),
                coverage=(round(coverage_pct, 1), _letter(coverage_pct, (90, 80, 70), True) if statements else "?"),
                oversized=(oversized, _letter(oversized, (0, 1, 3), False)),
                suppressions=(suppressions, _letter(suppressions, (0, 3, 8), False)),
                duplication=(duplicated, _letter(duplicated, (0, 1, 3), False)),
                docstrings=(round(docstring_pct), _letter(docstring_pct, (90, 75, 60), True)),
            )
        )
    return rows


def _cell(grade: Grade, suffix: str = "") -> str:
    value, letter = grade
    return f"{letter} ({value:g}{suffix})"


def table(rows: list[Row]) -> str:
    out = [
        "| Layer | Modules | Lines | Coverage | Over 400 | Suppressions | Duplicated blocks | Docstrings |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        out.append(
            f"| {row.layer} | {row.modules} | {row.lines} | {_cell(row.coverage, '%')} | {_cell(row.oversized)} "
            f"| {_cell(row.suppressions)} | {_cell(row.duplication)} | {_cell(row.docstrings, '%')} |"
        )
    return "\n".join(out)


def main() -> int:
    if not COVERAGE_FILE.exists():
        print("no .coverage.json: run `uv run poe cov` first; coverage is graded '?' without it", file=sys.stderr)
    print(table(grade()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
