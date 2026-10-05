"""ARCH-ERROR, on small trees built in tmp_path."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness import arch, error_rules

ERRORS = """
class AppError(Exception):
    code = "internal_error"

class Invalid(AppError):
    code = "invalid_request"
"""


def write(root: Path, name: str, text: str) -> None:
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(text, encoding="utf-8")


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    write(tmp_path, "src/errors.py", ERRORS)
    write(tmp_path, "src/tools.py", "from src.errors import Invalid\n\nclass ToolError(Invalid):\n    pass\n")
    return tmp_path


def found(root: Path, allowed: dict[str, str] | None = None) -> list[tuple[str, str, int]]:
    violations, _ = error_rules.check(root, allowed or {})
    return [(v.rule, v.path, v.line) for v in violations]


def test_errors_inside_the_hierarchy_pass(tree):
    assert found(tree) == []


def test_an_exception_outside_the_hierarchy_fails_at_its_class(tree):
    write(tree, "src/store.py", "import os\n\nclass StoreError(RuntimeError):\n    pass\n")
    assert found(tree) == [("ARCH-ERROR", "src/store.py", 3)]


def test_a_class_deriving_from_a_hierarchy_member_by_attribute_counts(tree):
    write(tree, "src/forms.py", "from src import errors\n\nclass Unreadable(errors.Invalid, ValueError):\n    pass\n")
    assert found(tree) == []


def test_membership_is_transitive_across_modules(tree):
    write(tree, "src/more.py", "from src.tools import ToolError\n\nclass Narrower(ToolError, KeyError):\n    pass\n")
    assert found(tree) == []


def test_private_control_flow_exceptions_are_exempt(tree):
    write(tree, "src/xlsx.py", "class _Unspliceable(Exception):\n    pass\n")
    assert found(tree) == []


def test_building_an_http_exception_fails(tree):
    write(
        tree, "src/api.py", "from fastapi import HTTPException\n\ndef f():\n    raise HTTPException(status_code=404)\n"
    )
    [violation] = error_rules.check(tree, {})[0]
    assert (violation.rule, violation.path, violation.line) == ("ARCH-ERROR", "src/api.py", 4)
    assert "src/errors.py" in violation.fix


def test_an_allow_listed_exception_passes_and_a_stale_entry_fails(tree):
    write(tree, "src/docling.py", "class DoclingError(RuntimeError):\n    pass\n")
    allow = arch.Allowlist(error={"src.docling.DoclingError": "TD-001"})
    assert [(v.rule, v.path) for v in arch.check_errors(tree, allow)] == []
    write(tree, "src/docling.py", "from src.errors import Invalid\n\nclass DoclingError(Invalid):\n    pass\n")
    assert [(v.rule, v.path) for v in arch.check_errors(tree, allow)] == [("ARCH-ALLOW", "harness/arch-allowlist.toml")]
