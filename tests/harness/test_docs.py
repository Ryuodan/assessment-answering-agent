"""The docs check, rule by rule, on small documentation trees built in tmp_path."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness import docs

PLAN = """# Plan 001: Example

**Status:** {status}

## Goal

x

## Acceptance criteria

- [{box}] done

## Plan

1. x

## Progress log

- x

## Decision log

- x
"""


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A minimal documentation tree that passes every rule."""
    files = {
        "CLAUDE.md": "[a](README.md) [b](ARCHITECTURE.md) [c](SECURITY.md) [d](docs/index.md)\n",
        "README.md": "# Readme\n\n## Getting started\n",
        "ARCHITECTURE.md": "# Architecture\n",
        "SECURITY.md": "# Security\n",
        "docs/index.md": (
            "[](project/DESCRIPTION.md) [](project/overview.md) [](design/decisions.md) "
            "[](plans/README.md) [](plans/roadmap.md) [](plans/tech-debt.md) "
            "[](harness/golden-principles.md) [](generated/openapi.json) [](generated/settings.md)\n"
        ),
        "docs/project/DESCRIPTION.md": "# What\n",
        "docs/project/overview.md": "# Overview\n",
        "docs/design/decisions.md": "# Decisions\n\n## D-001: one\n",
        "docs/plans/README.md": "# Plans\n",
        "docs/plans/roadmap.md": "[001](active/001-example.md)\n",
        "docs/plans/tech-debt.md": "# Debt\n\n## TD-001: one\n",
        "docs/plans/active/001-example.md": PLAN.format(status="active", box=" "),
        "docs/harness/golden-principles.md": "| ID | Rule |\n|---|---|\n| GP-01 | one |\n",
        "docs/generated/openapi.json": "{}\n",
        "docs/generated/settings.md": "# Settings\n",
    }
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    (tmp_path / "docs/plans/completed").mkdir()
    return tmp_path


def rules(root: Path) -> list[tuple[str, str, int]]:
    return [(v.rule, v.path, v.line) for v in docs.check(root)]


def write(root: Path, name: str, text: str) -> None:
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(text, encoding="utf-8")


def test_the_minimal_tree_passes(tree):
    assert rules(tree) == []


def test_a_missing_required_document_is_named(tree):
    (tree / "SECURITY.md").unlink()
    assert ("DOCS-REQUIRED", "SECURITY.md", 1) in rules(tree)


def test_a_broken_link_is_reported_at_its_line(tree):
    write(tree, "README.md", "# Readme\n\nsee [it](nowhere.md)\n")
    assert rules(tree) == [("DOCS-LINK", "README.md", 3)]


def test_links_inside_code_are_not_links(tree):
    write(tree, "README.md", "# Readme\n\n```\n[x](nowhere.md)\n```\n\n`[y](nowhere.md)`\n")
    assert rules(tree) == []


def test_external_links_are_not_checked(tree):
    write(tree, "README.md", "# Readme\n[x](https://example.com/a.md) [y](mailto:a@b.c)\n")
    assert rules(tree) == []


def test_an_anchor_must_name_a_heading(tree):
    write(tree, "ARCHITECTURE.md", "# Architecture\n[ok](README.md#getting-started) [bad](README.md#nope)\n")
    assert rules(tree) == [("DOCS-ANCHOR", "ARCHITECTURE.md", 2)]


def test_anchors_follow_githubs_rules():
    text = "# A reasoning model's thinking\n## `guarded`: the agent\n## Same\n## Same\n```\n# not a heading\n```\n"
    assert docs.anchors(text) == {"a-reasoning-models-thinking", "guarded-the-agent", "same", "same-1"}


def test_a_line_link_past_the_end_of_the_file_is_stale(tree):
    write(tree, "src/a.py", "x = 1\ny = 2\n")
    write(tree, "ARCHITECTURE.md", "# Architecture\n[ok](src/a.py:2) [stale](src/a.py:9)\n")
    assert rules(tree) == [("DOCS-LINK", "ARCHITECTURE.md", 2)]


def test_a_document_nobody_links_to_is_an_orphan(tree):
    write(tree, "docs/notes.md", "# Notes\n")
    assert rules(tree) == [("DOCS-ORPHAN", "docs/notes.md", 1)]


def test_a_plan_whose_status_disagrees_with_its_folder_fails(tree):
    write(tree, "docs/plans/active/001-example.md", PLAN.format(status="completed", box="x"))
    assert rules(tree) == [("DOCS-PLAN", "docs/plans/active/001-example.md", 3)]


def test_a_plan_missing_a_section_fails(tree):
    text = PLAN.format(status="active", box=" ").replace("## Decision log", "## Decisions")
    write(tree, "docs/plans/active/001-example.md", text)
    [violation] = docs.check(tree)
    assert violation.rule == "DOCS-PLAN" and "Decision log" in violation.message


def test_a_completed_plan_with_an_unchecked_box_fails(tree):
    (tree / "docs/plans/active/001-example.md").unlink()
    write(tree, "docs/plans/completed/001-example.md", PLAN.format(status="completed", box=" "))
    write(tree, "docs/plans/roadmap.md", "[001](completed/001-example.md)\n")
    assert rules(tree) == [("DOCS-PLAN", "docs/plans/completed/001-example.md", 11)]


def test_an_id_defined_twice_fails(tree):
    write(tree, "docs/plans/tech-debt.md", "# Debt\n\n## TD-001: one\n\n## TD-001: again\n")
    assert rules(tree) == [("DOCS-ID", "docs/plans/tech-debt.md", 5)]


def test_the_map_has_a_size_limit(tree):
    claude = (tree / "CLAUDE.md").read_text(encoding="utf-8")
    write(tree, "CLAUDE.md", claude + "line\n" * docs.MAP_MAX_LINES)
    assert rules(tree) == [("DOCS-MAP", "CLAUDE.md", docs.MAP_MAX_LINES + 1)]


def test_every_violation_carries_a_fix(tree):
    (tree / "README.md").unlink()
    write(tree, "docs/notes.md", "[x](gone.md)\n")
    found = docs.check(tree)
    assert found and all(v.fix for v in found)
