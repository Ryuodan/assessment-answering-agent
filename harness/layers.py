"""Layers of src/ and who may import what: ARCH-LAYER and ARCH-OWNER.

    ARCH-LAYER  a module imports a module of a higher layer; a module belongs to
                no layer; or src/ imports eval, scripts, harness or tests
    ARCH-OWNER  a module imports an owned IO or framework library from outside
                the layers (or module) that own it

The layers and owners are data, in harness/layers.toml. Imports inside
functions count the same as imports at the top of a module: a lazy import is
still a dependency, and hiding one is how the cycles in TD-007 stayed hidden.
Existing violations are allow-listed in harness/arch-allowlist.toml, each
against a TD item; harness/arch.py runs these checks with the others.
"""

from __future__ import annotations

import ast
import tomllib
from dataclasses import dataclass
from pathlib import Path

from harness.report import ROOT, Violation

LAYERS_FILE = ROOT / "harness" / "layers.toml"
OUTSIDE_SRC = {"eval", "scripts", "harness", "tests"}

_FIX_LAYER = (
    "depend downwards instead: move the shared piece into the lower layer, pass it in as a parameter or "
    "callback, or move this module up; the layers are in harness/layers.toml and ARCHITECTURE.md#layers"
)


@dataclass(frozen=True)
class Layering:
    order: tuple[str, ...]
    about: dict[str, str]
    exact: dict[str, str]
    prefixes: dict[str, str]
    owners: dict[str, frozenset[str]]

    @classmethod
    def load(cls, path: Path = LAYERS_FILE) -> Layering:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        exact: dict[str, str] = {}
        prefixes: dict[str, str] = {}
        for layer in data["layer"]:
            for module in layer["modules"]:
                if module.endswith(".*"):
                    prefixes[module[:-2]] = layer["name"]
                else:
                    exact[module] = layer["name"]
        return cls(
            order=tuple(layer["name"] for layer in data["layer"]),
            about={layer["name"]: layer.get("about", "") for layer in data["layer"]},
            exact=exact,
            prefixes=prefixes,
            owners={library: frozenset(allowed) for library, allowed in data.get("owners", {}).items()},
        )

    def layer_of(self, module: str) -> str | None:
        if module in self.exact:
            return self.exact[module]
        matches = [prefix for prefix in self.prefixes if module == prefix or module.startswith(prefix + ".")]
        return self.prefixes[max(matches, key=len)] if matches else None

    def rank(self, layer: str) -> int:
        return self.order.index(layer)

    def may_use(self, module: str, library: str) -> bool:
        allowed = self.owners.get(library)
        return allowed is None or module in allowed or self.layer_of(module) in allowed


def module_name(path: Path, root: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def src_modules(root: Path) -> dict[str, Path]:
    return {module_name(path, root): path for path in sorted((root / "src").rglob("*.py"))}


def imports_of(tree: ast.AST, known: set[str]) -> list[tuple[int, str]]:
    """(line, imported name) for every import, at any depth.

    `from src import tools` names the module src.tools when that is a module,
    and `from src.config import settings` names src.config.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                candidate = f"{node.module}.{alias.name}"
                found.append((node.lineno, candidate if candidate in known else node.module))
    return found


def check(
    root: Path,
    layering: Layering,
    allowed_layer: dict[tuple[str, str], str],
    allowed_owner: dict[tuple[str, str], str],
) -> tuple[list[Violation], set[tuple[str, str]], set[tuple[str, str]]]:
    """Violations, and which allow-list entries were matched (to find stale ones)."""
    modules = src_modules(root)
    known = set(modules)
    violations: list[Violation] = []
    used_layer: set[tuple[str, str]] = set()
    used_owner: set[tuple[str, str]] = set()

    for module, path in modules.items():
        rel = path.relative_to(root).as_posix()
        layer = layering.layer_of(module)
        if layer is None:
            violations.append(
                Violation(
                    "ARCH-LAYER",
                    rel,
                    1,
                    f"{module} belongs to no layer",
                    "add it to the layer it belongs in, in harness/layers.toml (see ARCHITECTURE.md#layers)",
                )
            )
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for line, name in imports_of(tree, known):
            top = name.split(".")[0]
            if top in OUTSIDE_SRC:
                violations.append(
                    Violation(
                        "ARCH-LAYER",
                        rel,
                        line,
                        f"{module} imports {name}, which is outside the application",
                        "the application must not depend on eval/, scripts/, harness/ or tests/; "
                        "move what it needs into src/",
                    )
                )
            elif top == "src":
                target = layering.layer_of(name)
                if target is None or layering.rank(target) <= layering.rank(layer):
                    continue
                if (module, name) in allowed_layer:
                    used_layer.add((module, name))
                    continue
                violations.append(
                    Violation(
                        "ARCH-LAYER",
                        rel,
                        line,
                        f"{module} ({layer}) imports {name} ({target}), a higher layer",
                        _FIX_LAYER,
                    )
                )
            elif not layering.may_use(module, top):
                if (module, top) in allowed_owner:
                    used_owner.add((module, top))
                    continue
                owners = ", ".join(sorted(layering.owners[top]))
                violations.append(
                    Violation(
                        "ARCH-OWNER",
                        rel,
                        line,
                        f"{module} ({layer}) imports {top}, which belongs to {owners}",
                        f"call it through a module of {owners} that already wraps it, or add a function there; "
                        "owners are listed in harness/layers.toml",
                    )
                )
    return violations, used_layer, used_owner
