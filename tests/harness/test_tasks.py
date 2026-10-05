"""The task definitions themselves (D-008, GP-15)."""

from __future__ import annotations

import tomllib

from harness.check import GATE
from harness.report import ROOT

TASKS = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["poe"]["tasks"]


def test_every_task_runs_its_tool_as_python_dash_m():
    """A .venv launcher hard-codes the interpreter it was installed with; this
    .venv's `pytest.exe` once ran another checkout's interpreter."""
    offenders = {name: task["cmd"] for name, task in TASKS.items() if not task["cmd"].startswith("python -m ")}
    assert not offenders, f"start these with `python -m`: {offenders}"


def test_the_gate_runs_tasks_that_exist_in_the_order_documented():
    assert [name for name, _ in GATE] == ["fmt", "lint", "types", "arch", "docs", "test"]
    assert all(name in TASKS for name, _ in GATE)
