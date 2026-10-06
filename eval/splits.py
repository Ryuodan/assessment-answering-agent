"""Which house-set questionnaires may be tuned against, and which are kept for a final check.

The house set's five questionnaires were all run, and changes kept or dropped on
their scores, before this split existed (TD-014). So "final" here means held
out *from 2026-10-06 on*, not never seen: a clean final split needs
questionnaires nobody has scored against yet.

    dev     tune against it as often as you like
    final   run it to confirm a change, with a reason; every run is recorded in
            eval/final_runs.jsonl, so how often it has been looked at is visible

The split is by questionnaire, never by question: a questionnaire asks the same
control several ways, and a question whose sibling sits in the other split
measures memory rather than drafting. Files are named in `eval/splits.json` by
a hash of their name, because the names say who the customers are and the
data itself is sealed (plan 002).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Protocol, TypeVar

Split = Literal["dev", "final", "all"]

SPLITS_FILE = Path(__file__).resolve().parent / "splits.json"
FINAL_RUNS = Path(__file__).resolve().parent / "final_runs.jsonl"


class _Case(Protocol):
    file: str


C = TypeVar("C", bound=_Case)


def file_key(file: str) -> str:
    """A stable name for a questionnaire that does not say whose it is."""
    return hashlib.sha256(file.encode("utf-8")).hexdigest()[:12]


def assignments(path: Path = SPLITS_FILE) -> dict[str, str]:
    """file key -> "dev" or "final"."""
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {key: "dev" for key in data["dev"]}
    out.update({key: "final" for key in data["final"]})
    return out


def select(cases: Iterable[C], split: Split, path: Path = SPLITS_FILE) -> list[C]:
    """The cases of one split. A questionnaire with no split is an error, not a guess."""
    cases = list(cases)
    if split == "all":
        return cases
    where = assignments(path)
    unknown = sorted({file_key(case.file) for case in cases} - set(where))
    if unknown:
        raise ValueError(
            f"questionnaire(s) {', '.join(unknown)} are in no split.\n"
            f"  FIX: add each key to 'dev' or 'final' in {path.name}; a new questionnaire belongs in 'final'"
        )
    return [case for case in cases if where[file_key(case.file)] == split]


def record_final_run(label: str, reason: str, summary: dict, path: Path = FINAL_RUNS) -> None:
    """Append one look at the final split: when, why, and what it scored. No content."""
    entry = {
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "label": label,
        "reason": reason,
        "cases": summary.get("cases"),
        "graded": summary.get("graded"),
        "agreement": summary.get("agreement"),
        "form": summary.get("form"),
        "failures": summary.get("failures"),
    }
    with path.open("a", encoding="utf-8") as log:
        log.write(json.dumps(entry, ensure_ascii=False) + "\n")


def final_runs(path: Path = FINAL_RUNS) -> int:
    """How many times the final split has been looked at."""
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
