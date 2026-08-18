from pathlib import Path

ROOT = Path(".")
OUTPUT = Path("all_python_code.txt")

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

with OUTPUT.open("w", encoding="utf-8") as out:
    for path in sorted(ROOT.rglob("*.py")):

        # Skip excluded directories
        if any(part in SKIP_DIRS for part in path.parts):
            continue

        out.write("\n" + "=" * 100 + "\n")
        out.write(f"FILE: {path.as_posix()}\n")
        out.write("=" * 100 + "\n\n")

        try:
            out.write(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            out.write("[Could not read this file as UTF-8]\n")

        out.write("\n\n")

print(f"Created: {OUTPUT}")