"""Architecture invariants that do not depend on the choice of layers.

    uv run poe arch

Rules (each violation prints rule, file:line and a FIX line):

    ARCH-SIZE    a module in src/ is longer than 400 lines, or longer than its
                 allow-listed ceiling; a ceiling that could be lower must be lowered
    ARCH-PRINT   `print` in src/ outside src/cli.py: use logging
    ARCH-ENV     the environment is read outside src/config.py
    ARCH-ENVEX   a Settings field is missing from .env.example, or .env.example
                 lists something that is not a setting
    ARCH-SECRET  a tracked file contains something shaped like a credential
    ARCH-ALLOW   an allow-list entry is stale, or names no tech-debt item

Existing violations live in harness/arch-allowlist.toml, each tied to a TD
item; entries may only be removed or tightened. Layer import rules come with
plan 003.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from harness.report import ROOT, Violation, finish

MAX_LINES = 400
PRINT_ALLOWED = {"src/cli.py"}
ENV_OWNER = "src/config.py"
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

    @classmethod
    def load(cls, path: Path) -> Allowlist:
        if not path.exists():
            return cls()
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return cls(
            size={e["path"]: (int(e["max_lines"]), e["debt"]) for e in data.get("size", [])},
            env={e["path"]: e["debt"] for e in data.get("env", [])},
            print_={e["path"]: e["debt"] for e in data.get("print", [])},
        )


def python_modules(root: Path) -> list[Path]:
    return sorted((root / "src").rglob("*.py"))


# --- rules -----------------------------------------------------------------


def check_size(root: Path, allow: Allowlist) -> list[Violation]:
    violations: list[Violation] = []
    seen: set[str] = set()
    for module in python_modules(root):
        path = rel_to(module, root)
        lines = len(module.read_text(encoding="utf-8").splitlines())
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
    )


def main() -> int:
    return finish("arch", check())


if __name__ == "__main__":
    sys.exit(main())
