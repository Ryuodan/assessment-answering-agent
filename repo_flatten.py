from pathlib import Path

ROOT = Path(".")
OUTPUT = Path("repo_export.txt")

# Directories/files to skip
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
}

SKIP_FILES = {
    ".env",
    "repo_export.txt",
}

# Extensions worth including
INCLUDE_EXTENSIONS = {
    ".py",
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".sql",
    ".html",
    ".css",
    ".js",
    ".ts",
}

files = []

for path in ROOT.rglob("*"):
    if not path.is_file():
        continue

    # Skip anything inside excluded directories
    if any(part in SKIP_DIRS for part in path.parts):
        continue

    if path.name in SKIP_FILES:
        continue

    if path.suffix.lower() in INCLUDE_EXTENSIONS:
        files.append(path)

files.sort()

with OUTPUT.open("w", encoding="utf-8") as f:
    f.write("# REPOSITORY STRUCTURE\n\n")

    for path in files:
        f.write(f"{path.as_posix()}\n")

    f.write("\n\n# FILE CONTENTS\n\n")

    for path in files:
        f.write("\n" + "=" * 80 + "\n")
        f.write(f"FILE: {path.as_posix()}\n")
        f.write("=" * 80 + "\n\n")

        try:
            f.write(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            f.write("[Could not decode this file as UTF-8]\n")

        f.write("\n\n")

print(f"Exported {len(files)} files to {OUTPUT}")