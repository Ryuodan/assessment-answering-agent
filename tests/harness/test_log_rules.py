"""ARCH-LOG, on small trees built in tmp_path."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness import arch, log_rules

CONVERTED = """from src.logs import get_logger

logger = get_logger(__name__)


def f(email):
    logger.info("storage.files_removed", person=email, files=3)
"""


def write(root: Path, name: str, text: str) -> None:
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(text, encoding="utf-8")


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    write(tmp_path, "src/logs.py", "import logging\n\nlogging.getLogger(__name__)\n")
    write(tmp_path, "src/storage.py", CONVERTED)
    return tmp_path


def found(root: Path, allowed: dict[str, str] | None = None) -> list[tuple[str, str, int]]:
    violations, _ = log_rules.check(root, allowed or {})
    return [(v.rule, v.path, v.line) for v in violations]


def test_event_logging_passes_and_src_logs_may_use_the_stdlib(tree):
    assert found(tree) == []


def test_a_standard_library_logger_fails(tree):
    write(tree, "src/new.py", "import logging\n\nlogger = logging.getLogger(__name__)\n")
    [violation] = log_rules.check(tree, {})[0]
    assert (violation.rule, violation.path, violation.line) == ("ARCH-LOG", "src/new.py", 3)
    assert "get_logger" in violation.fix


@pytest.mark.parametrize(
    "call",
    [
        'logger.info("Removed %d files", 3)',
        'logger.info("removed")',
        'logger.info(f"storage.{kind}")',
        "logger.info(name)",
        'logger.warning("Storage over limit")',
    ],
)
def test_an_event_logger_needs_a_literal_dotted_event_name(tree, call):
    write(tree, "src/storage.py", CONVERTED + f"\n\ndef g(kind, name):\n    {call}\n")
    assert found(tree) == [("ARCH-LOG", "src/storage.py", 11)]


def test_an_allow_listed_module_passes_and_a_converted_one_must_leave(tree):
    write(tree, "src/old.py", "import logging\n\nlogger = logging.getLogger(__name__)\n")
    allow = arch.Allowlist(log={"src/old.py": "TD-001"})
    assert arch.check_logs(tree, allow) == []
    write(tree, "src/old.py", CONVERTED)
    assert [(v.rule, v.path) for v in arch.check_logs(tree, allow)] == [("ARCH-ALLOW", "harness/arch-allowlist.toml")]
