"""Benchmark items must not leak into what the system is built from.

    uv run poe eval-contamination     # needs the sealed data unlocked for the house set

A score means something only while the system has not been shown the test.
Two ways it could be:

- **In the code.** A benchmark question or a reference answer copied into a
  prompt, an example, or a page. Checked by looking for any run of `WINDOW`
  consecutive words of a benchmark text in `src/`.
- **In the answer memory.** A house-set question that is also a remembered
  question measures recall, not drafting. The house set was built to keep them
  apart (docs/measurements/evaluation.md, "Splitting the team's answers"); this
  checks that it still does, on normalised text.

The golden set is tracked in plain text, so `tests/test_contamination.py`
checks it on every run. The house set is sealed, so it is checked here, by the
evaluation runner before every run, and by `poe eval-contamination`.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

WINDOW = 10
"""Words in a row that count as copied. Ten is past any stock phrase a policy and a prompt might share."""

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
SOURCE_SUFFIXES = {".py", ".html", ".js", ".css", ".md", ".json", ".txt"}


@dataclass(frozen=True)
class Leak:
    item: str
    """The benchmark item's id."""
    where: str
    """The file (or 'answer memory') it was found in."""
    words: str
    """The shared run of words, so a person can judge it."""


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def _windows(words: list[str], n: int = WINDOW) -> set[tuple[str, ...]]:
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def normalise(text: str) -> str:
    return " ".join(_words(text))


def in_sources(items: Iterable[tuple[str, str]], sources: dict[str, str], n: int = WINDOW) -> list[Leak]:
    """Every item (id, text) with a run of `n` words that also appears in a source file."""
    index: dict[tuple[str, ...], str] = {}
    for name, text in sources.items():
        for window in _windows(_words(text), n):
            index.setdefault(window, name)
    leaks: list[Leak] = []
    for item, text in items:
        for window in _windows(_words(text), n):
            if window in index:
                leaks.append(Leak(item, index[window], " ".join(window)))
                break
    return leaks


def in_memory(questions: Iterable[tuple[str, str]], remembered: Iterable[str]) -> list[Leak]:
    """Every benchmark question (id, text) that is, normalised, a remembered question."""
    known = {normalise(text) for text in remembered}
    return [Leak(item, "answer memory", text) for item, text in questions if normalise(text) in known]


def source_texts(root: Path) -> dict[str, str]:
    """What the system is built from: everything under src/ that holds text."""
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8", errors="replace")
        for path in sorted((root / "src").rglob("*"))
        if path.suffix in SOURCE_SUFFIXES and path.is_file()
    }


def check(cases: list, memory_questions: list[str] | None = None, root: Path | None = None) -> list[Leak]:
    """What a runner checks before it spends anything: the cases against src/ and, given it, the memory."""
    root = root or Path(__file__).resolve().parent.parent
    leaks = in_sources(
        [(c.test_id, c.question) for c in cases] + [(c.test_id + ":reference", c.answer) for c in cases],
        source_texts(root),
    )
    if memory_questions is not None:
        leaks += in_memory([(c.test_id, c.question) for c in cases], memory_questions)
    return leaks


KNOWN: dict[str, str] = {
    # The drafting prompt's example of stating a position as a fact is, nearly
    # word for word, the team's answer to this question (found 2026-10-06, plan 013).
    "HOUSE-096": "TD-033",
}
"""Leaks found and recorded, each against a tech-debt item. A runner leaves these
cases out and says so; any other leak stops it. Like every allow-list here, it
only shrinks: an entry goes when its leak is fixed."""


def _case_id(leak: Leak) -> str:
    return leak.item.split(":")[0]


def report(leaks: list[Leak]) -> list[Leak]:
    """Print every leak; return the ones not yet recorded in KNOWN."""
    new = [leak for leak in leaks if _case_id(leak) not in KNOWN]
    for leak in leaks:
        known = f" (known, {KNOWN[_case_id(leak)]})" if leak not in new else ""
        print(f'LEAK {leak.item} in {leak.where}{known}: "{leak.words[:80]}"')
    if new:
        print(f"  {len(new)} benchmark item(s) found where the system can see them.")
        print("  FIX: remove the copied text from src/ (or the question from the memory); a leak that")
        print("       cannot be fixed now goes in KNOWN (eval/contamination.py) against a tech-debt item")
    return new


def screen(cases: list, memory_questions: list[str] | None = None, root: Path | None = None) -> list | None:
    """The cases a runner may score: known leaks left out and counted. None when a new leak stops the run."""
    leaks = check(cases, memory_questions, root)
    if report(leaks):
        print("  not running.")
        return None
    left_out = sorted({_case_id(leak) for leak in leaks})
    if left_out:
        print(f"  left out as known leaks: {', '.join(left_out)} ({', '.join(sorted({KNOWN[i] for i in left_out}))})")
    return [c for c in cases if c.test_id not in left_out]


def main() -> int:
    from eval.house import load_house_set, load_memory_set

    cases = load_house_set()
    leaks = check(cases, [m.question for m in load_memory_set()])
    new = report(leaks)
    print(
        f"contamination: {len(cases)} house-set cases checked, {len(leaks)} leak(s), {len(new)} not yet known",
        file=sys.stderr,
    )
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main())
