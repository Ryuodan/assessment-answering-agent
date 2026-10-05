"""The arch check, rule by rule, on small trees built in tmp_path.

Fake credentials are assembled at runtime so that this file never contains
one, or the real check would (rightly) flag it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness import arch

CONFIG = """
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
    groq_api_key: str = ""
    max_evidence_chunks: int = 14
"""


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    write(tmp_path, "src/config.py", CONFIG)
    write(tmp_path, "src/app.py", "import logging\n\nlogger = logging.getLogger(__name__)\n")
    write(tmp_path, ".env.example", "GROQ_API_KEY=\n# MAX_EVIDENCE_CHUNKS=14\n")
    write(tmp_path, "docs/plans/tech-debt.md", "# Debt\n\n## TD-001: big modules\n")
    return tmp_path


def write(root: Path, name: str, text: str) -> None:
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(text, encoding="utf-8")


def allow(root: Path, text: str) -> Path:
    path = root / "allow.toml"
    path.write_text(text, encoding="utf-8")
    return path


def rules(root: Path, allowlist: Path | None = None) -> list[tuple[str, str, int]]:
    return [(v.rule, v.path, v.line) for v in arch.check(root, allowlist or root / "none.toml")]


def lines(n: int) -> str:
    return "x = 1\n" * n


def test_a_clean_tree_passes(tree):
    assert rules(tree) == []


def test_a_module_over_the_limit_fails(tree):
    write(tree, "src/big.py", lines(arch.MAX_LINES + 1))
    assert rules(tree) == [("ARCH-SIZE", "src/big.py", arch.MAX_LINES + 1)]


def test_an_allow_listed_module_may_not_grow_past_its_ceiling(tree):
    write(tree, "src/big.py", lines(501))
    allowlist = allow(tree, '[[size]]\npath = "src/big.py"\nmax_lines = 500\ndebt = "TD-001"\n')
    assert rules(tree, allowlist) == [("ARCH-SIZE", "src/big.py", 501)]


def test_a_shrunken_module_must_lower_its_ceiling(tree):
    write(tree, "src/big.py", lines(450))
    allowlist = allow(tree, '[[size]]\npath = "src/big.py"\nmax_lines = 500\ndebt = "TD-001"\n')
    [violation] = arch.check(tree, allowlist)
    assert violation.rule == "ARCH-ALLOW" and "max_lines = 450" in violation.fix


def test_a_module_back_under_the_limit_must_leave_the_allowlist(tree):
    write(tree, "src/big.py", lines(10))
    allowlist = allow(tree, '[[size]]\npath = "src/big.py"\nmax_lines = 500\ndebt = "TD-001"\n')
    [violation] = arch.check(tree, allowlist)
    assert violation.rule == "ARCH-ALLOW" and "delete" in violation.fix


def test_an_allowlist_entry_must_name_a_known_debt(tree):
    write(tree, "src/big.py", lines(450))
    allowlist = allow(tree, '[[size]]\npath = "src/big.py"\nmax_lines = 450\ndebt = "TD-999"\n')
    assert rules(tree, allowlist) == [("ARCH-ALLOW", "harness/arch-allowlist.toml", 1)]


def test_print_in_application_code_fails_at_its_line(tree):
    write(tree, "src/app.py", "def f():\n    print('debug')\n")
    assert rules(tree) == [("ARCH-PRINT", "src/app.py", 2)]


def test_the_cli_may_print(tree):
    write(tree, "src/cli.py", "print('usage')\n")
    assert rules(tree) == []


@pytest.mark.parametrize(
    "source",
    [
        "import os\nx = os.environ['A']\n",
        "import os\nx = os.getenv('A')\n",
        "from os import environ\n",
        "from dotenv import load_dotenv\n",
    ],
)
def test_reading_the_environment_outside_config_fails(tree, source):
    write(tree, "src/app.py", source)
    [violation] = arch.check(tree, tree / "none.toml")
    assert violation.rule == "ARCH-ENV" and violation.path == "src/app.py"


def test_config_may_read_the_environment(tree):
    write(tree, "src/config.py", CONFIG + "\nimport os\nX = os.environ.get('Y')\n")
    assert rules(tree) == []


def test_a_setting_missing_from_the_example_env_fails_at_the_field(tree):
    write(tree, ".env.example", "GROQ_API_KEY=\n")
    assert rules(tree) == [("ARCH-ENVEX", "src/config.py", 5)]


def test_an_example_env_key_that_is_not_a_setting_fails_at_its_line(tree):
    write(tree, ".env.example", "GROQ_API_KEY=\nMAX_EVIDENCE_CHUNKS=14\nLEFTOVER=1\n")
    assert rules(tree) == [("ARCH-ENVEX", ".env.example", 3)]


def test_a_key_shaped_string_in_any_file_fails_without_printing_it(tree):
    fake = "gsk_" + "A1b2" * 10
    write(tree, "notes.txt", f"line one\nkey: {fake}\n")
    [violation] = arch.check(tree, tree / "none.toml")
    assert (violation.rule, violation.path, violation.line) == ("ARCH-SECRET", "notes.txt", 2)
    assert fake not in violation.render()


def test_an_env_line_with_a_real_value_fails_but_a_placeholder_does_not(tree):
    write(tree, "README.md", "```\nLANGSMITH_API_KEY=lsv2_...\nGROQ_API_KEY=<your key>\n```\n")
    assert rules(tree) == []
    write(tree, "README.md", "GROQ_API_KEY=" + "abc123" * 4 + "\n")
    assert rules(tree) == [("ARCH-SECRET", "README.md", 1)]


def test_a_python_test_constant_is_not_an_env_line(tree):
    write(tree, "tests/test_x.py", 'ADMIN_PASSWORD = "correct-horse"\n')
    assert rules(tree) == []


def test_every_violation_carries_a_fix(tree):
    write(tree, "src/app.py", "import os\nprint(os.getenv('A'))\n" + lines(arch.MAX_LINES))
    found = arch.check(tree, tree / "none.toml")
    assert {v.rule for v in found} == {"ARCH-SIZE", "ARCH-PRINT", "ARCH-ENV"}
    assert all(v.fix for v in found)
