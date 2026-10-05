"""Architecture invariants that do not depend on the choice of layers.

    uv run poe arch

Rules (each violation prints rule, file:line and a FIX line):

    ARCH-SIZE    a module in src/ is longer than 400 lines, or longer than its
                 allow-listed ceiling; a ceiling that could be lower must be lowered.
                 The Settings class in src/config.py is not counted (D-010)
    ARCH-PRINT   `print` in src/ outside src/cli.py: use logging
    ARCH-ENV     the environment is read outside src/config.py
    ARCH-ENVEX   a Settings field is missing from .env.example, or .env.example
                 lists something that is not a setting
    ARCH-SECRET  a tracked file contains something shaped like a credential
    ARCH-ALLOW   an allow-list entry is stale, or names no tech-debt item
    ARCH-LAYER   an import against the layers of src/ (harness/layers.py)
    ARCH-OWNER   an IO or framework library imported outside its owning layer
    ARCH-ERROR   an exception outside src/errors.py's hierarchy (harness/error_rules.py)
    ARCH-LOG     prose logging instead of events (harness/log_rules.py)
    ARCH-SEALED  sealed eval data (eval/sealed/): a plaintext is tracked or not
                 gitignored, differs from its sealed copy, or a sealed file is missing

Existing violations live in harness/arch-allowlist.toml, each tied to a TD
item; entries may only be removed or tightened.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from harness import error_rules, layers, log_rules
from harness.report import ROOT, Violation, finish

MAX_LINES = 400
PRINT_ALLOWED = {"src/cli.py"}
ENV_OWNER = "src/config.py"
# Declaration lists that ARCH-SIZE does not count (D-010): one field and its doc
# comment per setting is data, not logic, and adding a setting is that module's job.
SIZE_EXEMPT_CLASSES = {ENV_OWNER: "Settings"}
ALLOWLIST = ROOT / "harness" / "arch-allowlist.toml"

_SECRET_SHAPES = [
    (re.compile(r"gsk_[A-Za-z0-9]{20,}"), "a Groq API key"),
    (re.compile(r"lsv2_(?:pt|sk)_[A-Za-z0-9_]{20,}"), "a LangSmith API key"),
    (re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}"), "an OpenAI-style API key"),
    (re.compile(r"\bhf_[A-Za-z0-9]{30,}"), "a HuggingFace token"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "an AWS access key id"),
    (re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"), "a private key"),
]
# An env-style line giving a secret setting a value: `.env` content pasted into
# a tracked file. Not applied to Python, where `ADMIN_PASSWORD = "..."` is a
# test constant; placeholders such as `lsv2_...` or `<your key>` are allowed.
_SECRET_SETTING = re.compile(
    r"^[ \t]*(?:GROQ_API_KEY|LANGSMITH_API_KEY|ADMIN_PASSWORD|EVAL_DATA_KEY)=[ \t]*([^\s#]+)", re.MULTILINE
)
_PLACEHOLDER = re.compile(r"\.\.\.|…|<|>|x{4}|changeme", re.IGNORECASE)
_BINARY_SUFFIXES = {".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".enc"}
_ENV_EXAMPLE_KEY = re.compile(r"^#?\s*([A-Z][A-Z0-9_]+)=", re.MULTILINE)


@dataclass
class Allowlist:
    size: dict[str, tuple[int, str]] = field(default_factory=dict)  # path -> (max_lines, debt)
    env: dict[str, str] = field(default_factory=dict)  # path -> debt
    print_: dict[str, str] = field(default_factory=dict)  # path -> debt
    layer: dict[tuple[str, str], str] = field(default_factory=dict)  # (module, imported module) -> debt
    owner: dict[tuple[str, str], str] = field(default_factory=dict)  # (module, library) -> debt
    error: dict[str, str] = field(default_factory=dict)  # qualified class name -> debt
    log: dict[str, str] = field(default_factory=dict)  # path -> debt

    @classmethod
    def load(cls, path: Path) -> Allowlist:
        if not path.exists():
            return cls()
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return cls(
            size={e["path"]: (int(e["max_lines"]), e["debt"]) for e in data.get("size", [])},
            env={e["path"]: e["debt"] for e in data.get("env", [])},
            print_={e["path"]: e["debt"] for e in data.get("print", [])},
            layer={(e["module"], e["imports"]): e["debt"] for e in data.get("layer", [])},
            owner={(e["module"], e["library"]): e["debt"] for e in data.get("owner", [])},
            error={e["class"]: e["debt"] for e in data.get("error", [])},
            log={e["path"]: e["debt"] for e in data.get("log", [])},
        )


def python_modules(root: Path) -> list[Path]:
    return sorted((root / "src").rglob("*.py"))


# --- rules -----------------------------------------------------------------


def counted_lines(path: str, text: str) -> int:
    """A module's length for ARCH-SIZE: every line, less any exempt declaration class."""
    total = len(text.splitlines())
    exempt = SIZE_EXEMPT_CLASSES.get(path)
    if exempt:
        for node in ast.parse(text).body:
            if isinstance(node, ast.ClassDef) and node.name == exempt and node.end_lineno is not None:
                total -= node.end_lineno - node.lineno + 1
    return total


def check_size(root: Path, allow: Allowlist) -> list[Violation]:
    violations: list[Violation] = []
    seen: set[str] = set()
    for module in python_modules(root):
        path = rel_to(module, root)
        lines = counted_lines(path, module.read_text(encoding="utf-8"))
        ceiling, debt = allow.size.get(path, (MAX_LINES, ""))
        if path in allow.size:
            seen.add(path)
        if lines > ceiling:
            limit = f"its allow-listed ceiling is {ceiling} ({debt})" if debt else f"the limit is {MAX_LINES}"
            violations.append(
                Violation(
                    "ARCH-SIZE",
                    path,
                    ceiling + 1,
                    f"module has {lines} lines; {limit}",
                    "move a cohesive group of functions into its own module (behind tests); never raise the ceiling",
                )
            )
        elif debt and lines <= MAX_LINES:
            violations.append(
                Violation(
                    "ARCH-ALLOW",
                    "harness/arch-allowlist.toml",
                    1,
                    f"{path} is now {lines} lines, within the limit; its size entry is no longer needed",
                    f"delete the [[size]] entry for {path}, and mark {debt} resolved if nothing else remains",
                )
            )
        elif debt and lines < ceiling:
            violations.append(
                Violation(
                    "ARCH-ALLOW",
                    "harness/arch-allowlist.toml",
                    1,
                    f"{path} shrank to {lines} lines; its ceiling is still {ceiling}",
                    f"set max_lines = {lines} for {path} (ceilings only go down)",
                )
            )
    for path in sorted(set(allow.size) - seen):
        violations.append(
            Violation(
                "ARCH-ALLOW",
                "harness/arch-allowlist.toml",
                1,
                f"size entry for {path}, which does not exist",
                f"delete the [[size]] entry for {path}",
            )
        )
    return violations


def _calls_print(tree: ast.AST) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print"
    ]


def _reads_environment(tree: ast.AST) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv", "putenv"):
            if isinstance(node.value, ast.Name) and node.value.id == "os":
                lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.module in ("os", "dotenv"):
            if node.module == "dotenv" or any(a.name in ("environ", "getenv", "putenv") for a in node.names):
                lines.append(node.lineno)
        elif isinstance(node, ast.Import) and any(a.name == "dotenv" for a in node.names):
            lines.append(node.lineno)
    return lines


def check_print_and_env(root: Path, allow: Allowlist) -> list[Violation]:
    violations: list[Violation] = []
    print_seen: set[str] = set()
    env_seen: set[str] = set()
    for module in python_modules(root):
        path = rel_to(module, root)
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=path)
        if path not in PRINT_ALLOWED:
            hits = _calls_print(tree)
            if hits and path in allow.print_:
                print_seen.add(path)
            elif hits:
                violations.extend(
                    Violation(
                        "ARCH-PRINT",
                        path,
                        line,
                        "print() in application code",
                        "use `logger = logging.getLogger(__name__)` and log an event instead",
                    )
                    for line in hits
                )
        if path != ENV_OWNER:
            hits = _reads_environment(tree)
            if hits and path in allow.env:
                env_seen.add(path)
            elif hits:
                violations.extend(
                    Violation(
                        "ARCH-ENV",
                        path,
                        line,
                        "reads the environment outside src/config.py",
                        "add a field to Settings in src/config.py (and to .env.example), then use `settings.<field>`",
                    )
                    for line in hits
                )
    for kind, entries, seen in (("print", allow.print_, print_seen), ("env", allow.env, env_seen)):
        for path in sorted(set(entries) - seen):
            violations.append(
                Violation(
                    "ARCH-ALLOW",
                    "harness/arch-allowlist.toml",
                    1,
                    f"[[{kind}]] entry for {path}, which no longer has that violation",
                    f"delete the [[{kind}]] entry for {path}, and mark {entries[path]} resolved if nothing else remains",
                )
            )
    return violations


def settings_fields(config: Path) -> dict[str, int]:
    """Field name -> line, read from the Settings class without importing it.

    Importing src.config would read the real .env and start tracing; the
    checks must not touch the developer's configuration.
    """
    tree = ast.parse(config.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            return {
                stmt.target.id: stmt.lineno
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
                if stmt.target.id != "model_config"
            }
    return {}


def check_env_example(root: Path) -> list[Violation]:
    config, example = root / ENV_OWNER, root / ".env.example"
    if not config.exists() or not example.exists():
        return []
    fields = settings_fields(config)
    text = example.read_text(encoding="utf-8")
    keys = {m.group(1).lower(): text[: m.start()].count("\n") + 1 for m in _ENV_EXAMPLE_KEY.finditer(text)}
    violations = [
        Violation(
            "ARCH-ENVEX",
            ENV_OWNER,
            line,
            f"setting '{name}' is not listed in .env.example",
            f"add `{name.upper()}=<default>` to .env.example with a comment saying what it does",
        )
        for name, line in fields.items()
        if name not in keys
    ]
    violations += [
        Violation(
            "ARCH-ENVEX",
            ".env.example",
            line,
            f"'{key.upper()}' is not a field of Settings in src/config.py",
            "remove it from .env.example, or add the setting to Settings",
        )
        for key, line in keys.items()
        if key not in fields
    ]
    return violations


def tracked_files(root: Path) -> list[Path]:
    try:
        listed = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout.splitlines()
        return [root / p for p in listed if (root / p).is_file()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return [p for p in root.rglob("*") if p.is_file()]


def check_secrets(root: Path) -> list[Violation]:
    violations: list[Violation] = []
    for file in tracked_files(root):
        if file.suffix.lower() in _BINARY_SUFFIXES:
            continue
        try:
            text = file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        shapes = list(_SECRET_SHAPES)
        if file.suffix != ".py":
            shapes.append((_SECRET_SETTING, "a secret setting with a value"))
        for pattern, what in shapes:
            for match in pattern.finditer(text):
                if pattern is _SECRET_SETTING and _PLACEHOLDER.search(match.group(1)):
                    continue
                line = text[: match.start()].count("\n") + 1
                # The value itself is never printed: this output goes to logs and chats.
                violations.append(
                    Violation(
                        "ARCH-SECRET",
                        rel_to(file, root),
                        line,
                        f"looks like {what} (value not shown)",
                        "stop: remove it, rotate the credential, and keep secrets in .env only; "
                        "if it is a test value, build it at runtime instead of writing it out",
                    )
                )
    return violations


def check_allowlist_debts(root: Path, allow: Allowlist) -> list[Violation]:
    debt_file = root / "docs" / "plans" / "tech-debt.md"
    known = (
        set(re.findall(r"^## (TD-\d{3})", debt_file.read_text(encoding="utf-8"), re.MULTILINE))
        if debt_file.exists()
        else set()
    )
    named = [(p, d) for p, (_, d) in allow.size.items()] + list(allow.env.items()) + list(allow.print_.items())
    named += [(f"{m} -> {i}", d) for (m, i), d in allow.layer.items()]
    named += [(f"{m} -> {lib}", d) for (m, lib), d in allow.owner.items()]
    named += list(allow.error.items())
    named += list(allow.log.items())
    return [
        Violation(
            "ARCH-ALLOW",
            "harness/arch-allowlist.toml",
            1,
            f"the entry for {path} names '{debt}', which is not an item in docs/plans/tech-debt.md",
            "name the TD item that explains this violation, or add one",
        )
        for path, debt in named
        if debt not in known
    ]


def indexed_files(root: Path) -> set[str]:
    """Paths in the git index; empty outside a repository (the tests)."""
    try:
        listed = subprocess.run(
            ["git", "ls-files", "--cached"], cwd=root, capture_output=True, text=True, encoding="utf-8", check=True
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return set()
    return set(listed.splitlines())


def git_ignores(root: Path) -> Callable[[str], bool]:
    def ignored(path: str) -> bool:
        try:
            return subprocess.run(["git", "check-ignore", "-q", path], cwd=root, check=False).returncode in (0, 128)
        except FileNotFoundError:
            return True

    return ignored


def check_sealed(root: Path, indexed: set[str], ignored: Callable[[str], bool]) -> list[Violation]:
    """Sealed eval data stays sealed (plan 002, GP-16).

    Reads the manifest's SHA-256 of each plaintext, so it needs no key: a local
    plaintext that hashes differently is one somebody changed without sealing.
    """
    sealed_dir = root / "eval" / "sealed"
    manifest = sealed_dir / "manifest.json"
    if not manifest.exists():
        return []
    hashes: dict[str, str] = json.loads(manifest.read_text(encoding="utf-8"))["sha256"]
    violations: list[Violation] = []
    for name, expected in sorted(hashes.items()):
        plain = f"eval/{name}"
        if plain in indexed:
            violations.append(
                Violation(
                    "ARCH-SEALED",
                    plain,
                    1,
                    "the plaintext of a sealed file is tracked by git",
                    f"`git rm --cached {plain}` (the file stays on disk), and keep it listed in .gitignore",
                )
            )
        elif not ignored(plain):
            violations.append(
                Violation(
                    "ARCH-SEALED",
                    ".gitignore",
                    1,
                    f"{plain} is sealed but not gitignored, so `git add` would commit the plaintext",
                    f"add `{plain}` to .gitignore",
                )
            )
        if not (sealed_dir / f"{name}.enc").exists():
            violations.append(
                Violation(
                    "ARCH-SEALED",
                    "eval/sealed/manifest.json",
                    1,
                    f"the manifest lists {name}, but eval/sealed/{name}.enc is missing",
                    "restore it with `git checkout -- eval/sealed`, or seal again with `uv run poe eval-seal`",
                )
            )
        local = root / plain
        if local.exists() and hashlib.sha256(local.read_bytes()).hexdigest() != expected:
            violations.append(
                Violation(
                    "ARCH-SEALED",
                    plain,
                    1,
                    "differs from its sealed copy",
                    "if you changed it on purpose, run `uv run poe eval-seal` and commit eval/sealed/; "
                    "if not, restore the sealed version with `uv run poe eval-unlock --force`",
                )
            )
    for enc in sorted(sealed_dir.glob("*.enc")):
        if enc.name.removesuffix(".enc") not in hashes:
            violations.append(
                Violation(
                    "ARCH-SEALED",
                    rel_to(enc, root),
                    1,
                    "a sealed file the manifest does not list",
                    "seal through `uv run poe eval-seal`, which writes both, or delete the stray file",
                )
            )
    return violations


def check_layers(root: Path, allow: Allowlist, layers_file: Path | None = None) -> list[Violation]:
    """ARCH-LAYER and ARCH-OWNER, plus allow-list entries they no longer need.

    A tree without a layers file has no layers to enforce (the other rules'
    tests build such trees); tests/harness/test_layers.py holds that this
    repository has one.
    """
    path = layers_file or root / "harness" / "layers.toml"
    if not path.exists():
        return []
    layering = layers.Layering.load(path)
    violations, used_layer, used_owner = layers.check(root, layering, allow.layer, allow.owner)
    stale = [(f"[[layer]] {m} -> {i}", d) for (m, i), d in allow.layer.items() if (m, i) not in used_layer]
    stale += [(f"[[owner]] {m} -> {lib}", d) for (m, lib), d in allow.owner.items() if (m, lib) not in used_owner]
    violations += [
        Violation(
            "ARCH-ALLOW",
            "harness/arch-allowlist.toml",
            1,
            f"{entry} no longer happens",
            f"delete that entry, and mark {debt} resolved if nothing else remains",
        )
        for entry, debt in stale
    ]
    return violations


def check_errors(root: Path, allow: Allowlist) -> list[Violation]:
    """ARCH-ERROR, plus allow-list entries it no longer needs."""
    if not (root / "src").is_dir():
        return []
    violations, used = error_rules.check(root, allow.error)
    violations += [
        Violation(
            "ARCH-ALLOW",
            "harness/arch-allowlist.toml",
            1,
            f"[[error]] {name} is now inside the AppError hierarchy, or gone",
            f"delete that entry, and mark {debt} resolved if nothing else remains",
        )
        for name, debt in allow.error.items()
        if name not in used
    ]
    return violations


def check_logs(root: Path, allow: Allowlist) -> list[Violation]:
    """ARCH-LOG, plus allow-list entries it no longer needs."""
    if not (root / "src").is_dir():
        return []
    violations, used = log_rules.check(root, allow.log)
    violations += [
        Violation(
            "ARCH-ALLOW",
            "harness/arch-allowlist.toml",
            1,
            f"[[log]] {path} no longer makes a standard-library logger",
            f"delete that entry, and mark {debt} resolved when the list is empty",
        )
        for path, debt in allow.log.items()
        if path not in used
    ]
    return violations


def rel_to(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def check(root: Path = ROOT, allowlist: Path | None = None) -> list[Violation]:
    allow = Allowlist.load(allowlist if allowlist is not None else root / "harness" / "arch-allowlist.toml")
    return (
        check_size(root, allow)
        + check_print_and_env(root, allow)
        + check_env_example(root)
        + check_secrets(root)
        + check_allowlist_debts(root, allow)
        + check_sealed(root, indexed_files(root), git_ignores(root))
        + check_layers(root, allow)
        + check_errors(root, allow)
        + check_logs(root, allow)
    )


def main() -> int:
    return finish("arch", check())


if __name__ == "__main__":
    sys.exit(main())
