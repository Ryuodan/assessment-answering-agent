"""The docs check: the documentation exists, links resolve, nothing is orphaned.

    uv run poe docs

Rules (each violation prints rule, file:line and a FIX line):

    DOCS-REQUIRED  a document the layout requires is missing
    DOCS-LINK      a relative link points at a file that does not exist,
                   or a `path:line` link at a line past the end of the file
    DOCS-ANCHOR    a `#anchor` names no heading in the target document
    DOCS-ORPHAN    a document cannot be reached by following links from CLAUDE.md
    DOCS-PLAN      a plan lacks a required section, or its status disagrees with
                   its folder, or a completed plan has unchecked criteria
    DOCS-ID        an ID (TD-, D-, GP-) is defined twice
    DOCS-MAP       CLAUDE.md has grown past its limit: it is a map, not a manual

Links inside code blocks and inline code are not links.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import deque
from pathlib import Path

from harness.report import ROOT, Violation, finish

ENTRY = "CLAUDE.md"
MAP_MAX_LINES = 120

REQUIRED = [
    "CLAUDE.md",
    "README.md",
    "ARCHITECTURE.md",
    "SECURITY.md",
    "docs/project/DESCRIPTION.md",
    "docs/project/overview.md",
    "docs/design/decisions.md",
    "docs/plans/README.md",
    "docs/plans/roadmap.md",
    "docs/plans/tech-debt.md",
    "docs/plans/active",
    "docs/plans/completed",
    "docs/harness/golden-principles.md",
    "docs/generated/openapi.json",
    "docs/generated/settings.md",
    "docs/generated/layers.md",
    "docs/generated/errors.md",
]

PLAN_SECTIONS = ["Goal", "Acceptance criteria", "Plan", "Progress log", "Decision log"]
PLAN_NAME = re.compile(r"^(\d{3})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
STATUS = re.compile(r"^\*\*Status:\*\*\s*(\w+)", re.MULTILINE)

# IDs are defined by a heading ("## TD-001: ...") or a table row ("| GP-01 | ...").
ID_DEFINITIONS = {
    "docs/plans/tech-debt.md": re.compile(r"^#{2,3} (TD-\d{3})\b", re.MULTILINE),
    "docs/design/decisions.md": re.compile(r"^#{2,3} (D-\d{3})\b", re.MULTILINE),
    "docs/harness/golden-principles.md": re.compile(r"^\| (GP-\d{2}) \|", re.MULTILINE),
}

_FENCE = re.compile(r"^\s*(```|~~~)")
_INLINE_CODE = re.compile(r"`[^`]*`")
_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_LINE_SUFFIX = re.compile(r"^(.*\.[A-Za-z0-9]+):(\d+)$")
_EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*://|mailto:)", re.IGNORECASE)


# --- reading markdown ------------------------------------------------------


def prose_lines(text: str) -> list[tuple[int, str]]:
    """(line number, text) for lines outside fenced code blocks, inline code removed."""
    lines: list[tuple[int, str]] = []
    fenced = False
    for number, line in enumerate(text.splitlines(), start=1):
        if _FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            lines.append((number, _INLINE_CODE.sub("", line)))
    return lines


def slug(heading: str) -> str:
    """GitHub's anchor for a heading: link text kept, punctuation dropped, spaces to hyphens."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)
    text = text.replace("`", "").lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(text: str) -> set[str]:
    found: set[str] = set()
    counts: dict[str, int] = {}
    fenced = False
    for line in text.splitlines():
        if _FENCE.match(line):
            fenced = not fenced
            continue
        match = None if fenced else _HEADING.match(line)
        if match:
            base = slug(match.group(2))
            seen = counts.get(base, 0)
            found.add(base if seen == 0 else f"{base}-{seen}")
            counts[base] = seen + 1
    return found


def links(text: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for number, line in prose_lines(text):
        for match in _LINK.finditer(line):
            target = match.group(1)
            if not _EXTERNAL.match(target):
                found.append((number, target))
    return found


# --- the checks ------------------------------------------------------------


def candidate_documents(root: Path) -> list[str]:
    """Every document that must be reachable: root Markdown plus everything in docs/.

    Uses git so that ignored files (a local reference PDF) are not demanded;
    falls back to the file system outside a repository (the tests).
    """
    try:
        listed = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", "*.md", "docs"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout.splitlines()
        paths = sorted({p for p in listed if (root / p).is_file()})
    except (subprocess.CalledProcessError, FileNotFoundError):
        paths = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    return [
        p
        for p in paths
        if (p.startswith("docs/") or ("/" not in p and p.endswith(".md"))) and not p.endswith(".gitkeep")
    ]


def check_required(root: Path) -> list[Violation]:
    return [
        Violation(
            "DOCS-REQUIRED",
            path,
            1,
            "required by the documentation layout but missing",
            "create it (see docs/plans/completed/001-foundations.md for the layout); "
            "generated files come from `uv run poe gen`",
        )
        for path in REQUIRED
        if not (root / path).exists()
    ]


def resolve(source: str, target: str) -> tuple[str, str, int | None]:
    """(repository path, anchor, line) for a link target written in `source`."""
    path_part, _, anchor = target.partition("#")
    line: int | None = None
    suffix = _LINE_SUFFIX.match(path_part)
    if suffix:
        path_part, line = suffix.group(1), int(suffix.group(2))
    if not path_part:
        return source, anchor, line
    joined = (Path(source).parent / path_part).as_posix()
    parts: list[str] = []
    for piece in joined.split("/"):
        if piece in ("", "."):
            continue
        if piece == ".." and parts:
            parts.pop()
        else:
            parts.append(piece)
    return "/".join(parts), anchor, line


def check_links(root: Path, documents: list[str]) -> tuple[list[Violation], dict[str, set[str]]]:
    """Link violations, and the graph of which document links to which."""
    violations: list[Violation] = []
    graph: dict[str, set[str]] = {}
    anchor_cache: dict[str, set[str]] = {}
    for source in documents:
        if not source.endswith(".md"):
            continue
        text = (root / source).read_text(encoding="utf-8")
        graph[source] = set()
        for number, target in links(text):
            path, anchor, line = resolve(source, target)
            full = root / path
            if not full.exists():
                violations.append(
                    Violation(
                        "DOCS-LINK",
                        source,
                        number,
                        f"link target '{target}' does not exist",
                        f"point the link at an existing file (resolved to '{path}'), or remove it",
                    )
                )
                continue
            graph[source].add(path if full.is_file() else f"{path.rstrip('/')}/README.md")
            if line is not None and full.is_file():
                length = len(full.read_text(encoding="utf-8", errors="replace").splitlines())
                if line > length:
                    violations.append(
                        Violation(
                            "DOCS-LINK",
                            source,
                            number,
                            f"'{target}' points at line {line}, but the file has {length}",
                            "update the line number (the code moved), or link to the file without one",
                        )
                    )
            if anchor and full.is_file() and path.endswith(".md"):
                if path not in anchor_cache:
                    anchor_cache[path] = anchors(full.read_text(encoding="utf-8"))
                if anchor not in anchor_cache[path]:
                    violations.append(
                        Violation(
                            "DOCS-ANCHOR",
                            source,
                            number,
                            f"'{target}': no heading in {path} has the anchor '#{anchor}'",
                            "use the heading's anchor: lower-case, punctuation removed, spaces as hyphens",
                        )
                    )
    return violations, graph


def check_orphans(documents: list[str], graph: dict[str, set[str]]) -> list[Violation]:
    reached = {ENTRY}
    queue = deque([ENTRY])
    while queue:
        for target in graph.get(queue.popleft(), set()):
            if target not in reached:
                reached.add(target)
                queue.append(target)
    return [
        Violation(
            "DOCS-ORPHAN",
            path,
            1,
            "cannot be reached by following links from CLAUDE.md",
            "link it from the document that should lead to it (a plan from docs/plans/roadmap.md; "
            "anything else from CLAUDE.md or a page it links to), or delete it if it is obsolete",
        )
        for path in documents
        if path not in reached
    ]


def check_plans(root: Path) -> list[Violation]:
    violations: list[Violation] = []
    for folder in ("active", "completed"):
        directory = root / "docs" / "plans" / folder
        if not directory.is_dir():
            continue
        for plan in sorted(directory.glob("*.md")):
            path = plan.relative_to(root).as_posix()
            text = plan.read_text(encoding="utf-8")

            def fail(line: int, message: str, fix: str, _path: str = path) -> None:
                violations.append(Violation("DOCS-PLAN", _path, line, message, fix))

            name = PLAN_NAME.match(plan.name)
            if not name:
                fail(1, f"'{plan.name}' is not named NNN-slug.md", "rename it, e.g. 007-short-name.md")
            elif not re.search(rf"^# Plan {name.group(1)}: ", text, re.MULTILINE):
                fail(1, f"the title must start '# Plan {name.group(1)}: '", "match the title to the file number")
            status = STATUS.search(text)
            if not status:
                fail(1, "no '**Status:**' line", f"add '**Status:** {folder}' under the title")
            elif status.group(1) != folder:
                line = text[: status.start()].count("\n") + 1
                fail(
                    line,
                    f"status is '{status.group(1)}' but the plan is in {folder}/",
                    "move the file to the folder its status names, or correct the status",
                )
            headings = [m.group(1) for m in re.finditer(r"^## (.+?)\s*$", text, re.MULTILINE)]
            missing = [s for s in PLAN_SECTIONS if s not in headings]
            if missing:
                fail(
                    1,
                    f"missing section(s): {', '.join(missing)}",
                    "add them as '## <name>' headings; see the template in docs/plans/README.md",
                )
            if folder == "completed":
                for number, line_text in enumerate(text.splitlines(), start=1):
                    if line_text.lstrip().startswith("- [ ]"):
                        fail(
                            number,
                            "a completed plan has an unchecked acceptance criterion",
                            "meet and check it, or move the plan back to active/",
                        )
    return violations


def check_ids(root: Path) -> list[Violation]:
    violations: list[Violation] = []
    for path, pattern in ID_DEFINITIONS.items():
        file = root / path
        if not file.exists():
            continue
        text = file.read_text(encoding="utf-8")
        seen: dict[str, int] = {}
        for match in pattern.finditer(text):
            line = text[: match.start()].count("\n") + 1
            identifier = match.group(1)
            if identifier in seen:
                violations.append(
                    Violation(
                        "DOCS-ID",
                        path,
                        line,
                        f"{identifier} is already defined on line {seen[identifier]}",
                        "give this entry the next unused number; never reuse an ID",
                    )
                )
            else:
                seen[identifier] = line
    return violations


def check_map(root: Path) -> list[Violation]:
    entry = root / ENTRY
    if not entry.exists():
        return []
    length = len(entry.read_text(encoding="utf-8").splitlines())
    if length <= MAP_MAX_LINES:
        return []
    return [
        Violation(
            "DOCS-MAP",
            ENTRY,
            MAP_MAX_LINES + 1,
            f"CLAUDE.md has {length} lines; the limit is {MAP_MAX_LINES}",
            "move the detail into a document under docs/ and link to it from CLAUDE.md",
        )
    ]


def check(root: Path = ROOT) -> list[Violation]:
    documents = candidate_documents(root)
    link_violations, graph = check_links(root, documents)
    return (
        check_required(root)
        + link_violations
        + check_orphans(documents, graph)
        + check_plans(root)
        + check_ids(root)
        + check_map(root)
    )


def main() -> int:
    return finish("docs", check())


if __name__ == "__main__":
    sys.exit(main())
