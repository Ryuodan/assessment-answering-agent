"""ARCH-LAYER and ARCH-OWNER, on a three-layer tree built in tmp_path."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness import arch, layers

LAYERS = """
[[layer]]
name = "low"
modules = ["src", "src.base", "src.settings"]

[[layer]]
name = "middle"
modules = ["src.store", "src.parts.*", "src.parts.special"]

[[layer]]
name = "top"
modules = ["src.app", "src.parts.special_top"]

[owners]
sqlite3 = ["middle"]
pydantic_settings = ["src.settings"]
"""


def write(root: Path, name: str, text: str) -> None:
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(text, encoding="utf-8")


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    write(tmp_path, "harness/layers.toml", LAYERS)
    write(tmp_path, "src/__init__.py", "")
    write(tmp_path, "src/base.py", "import json\n")
    write(tmp_path, "src/settings.py", "from pydantic_settings import BaseSettings\n")
    write(tmp_path, "src/store.py", "import sqlite3\n\nfrom src import base\n")
    write(tmp_path, "src/parts/__init__.py", "")
    write(tmp_path, "src/parts/one.py", "from src.store import connect\n")
    write(tmp_path, "src/parts/special.py", "")
    write(tmp_path, "src/parts/special_top.py", "from src.app import run\n")
    write(tmp_path, "src/app.py", "from src.parts import one\nfrom src.base import x\n")
    return tmp_path


def found(root: Path, allow: arch.Allowlist | None = None) -> list[tuple[str, str, int]]:
    return [(v.rule, v.path, v.line) for v in arch.check_layers(root, allow or arch.Allowlist())]


def test_a_layered_tree_passes(tree):
    assert found(tree) == []


def test_importing_a_higher_layer_fails_at_its_line(tree):
    write(tree, "src/store.py", "import sqlite3\n\nfrom src.app import run\n")
    [violation] = arch.check_layers(tree, arch.Allowlist())
    assert (violation.rule, violation.path, violation.line) == ("ARCH-LAYER", "src/store.py", 3)
    assert "src.store (middle) imports src.app (top)" in violation.message
    assert violation.fix


def test_an_import_inside_a_function_counts_too(tree):
    write(tree, "src/base.py", "def later():\n    from src import store\n    return store\n")
    assert found(tree) == [("ARCH-LAYER", "src/base.py", 2)]


def test_an_exact_assignment_beats_a_package_pattern(tree):
    # src.parts.special_top is "top" by name, though src.parts.* is "middle".
    assert arch.layers.Layering.load(tree / "harness/layers.toml").layer_of("src.parts.special_top") == "top"
    assert found(tree) == []


def test_a_module_in_no_layer_fails(tree):
    write(tree, "src/newcomer.py", "")
    [violation] = arch.check_layers(tree, arch.Allowlist())
    assert (violation.rule, violation.path) == ("ARCH-LAYER", "src/newcomer.py")
    assert "harness/layers.toml" in violation.fix


@pytest.mark.parametrize("outside", ["tests.conftest", "harness.report", "scripts.selfcheck", "eval.house"])
def test_the_application_never_imports_the_tooling_around_it(tree, outside):
    write(tree, "src/base.py", f"import {outside}\n")
    assert found(tree) == [("ARCH-LAYER", "src/base.py", 1)]


def test_an_owned_library_outside_its_layer_fails(tree):
    write(tree, "src/app.py", "import sqlite3\n")
    [violation] = arch.check_layers(tree, arch.Allowlist())
    assert (violation.rule, violation.path, violation.line) == ("ARCH-OWNER", "src/app.py", 1)
    assert "belongs to middle" in violation.message


def test_a_library_owned_by_one_module_is_refused_to_its_neighbours(tree):
    write(tree, "src/base.py", "from pydantic_settings import BaseSettings\n")
    assert found(tree) == [("ARCH-OWNER", "src/base.py", 1)]


def test_an_allow_listed_violation_passes_and_a_stale_entry_fails(tree):
    write(tree, "src/store.py", "from src.app import run\n")
    allow = arch.Allowlist(layer={("src.store", "src.app"): "TD-001"})
    assert found(tree, allow) == []
    write(tree, "src/store.py", "")
    assert found(tree, allow) == [("ARCH-ALLOW", "harness/arch-allowlist.toml", 1)]


def test_a_tree_without_a_layers_file_has_nothing_to_enforce(tree):
    (tree / "harness/layers.toml").unlink()
    write(tree, "src/store.py", "from src.app import run\n")
    assert found(tree) == []


# --- this repository --------------------------------------------------------


def test_this_repository_defines_its_layers():
    assert layers.LAYERS_FILE.exists(), "harness/layers.toml is missing, so ARCH-LAYER would check nothing"


def test_every_module_of_this_repository_has_a_layer():
    layering = layers.Layering.load()
    unplaced = [module for module in layers.src_modules(layers.ROOT) if layering.layer_of(module) is None]
    assert not unplaced
