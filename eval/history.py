"""A durable record of every evaluation run.

One JSON Lines file, appended to and never rewritten. Each line is one scored
run: its label, when it happened, the settings that produced it, and the numbers
it scored. Runs are only comparable when you can see what was different about
them, and "what was different" is exactly what gets forgotten between sessions —
so the retrieval and model settings are captured with the scores rather than
left in someone's memory of which flag was set that afternoon.

JSON Lines rather than a single JSON array so that an interrupted or concurrent
run cannot corrupt the history: appending a line is atomic enough for this, and
a truncated final line costs one record instead of the file.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.config import PROJECT_ROOT, settings

logger = logging.getLogger(__name__)

HISTORY_PATH = PROJECT_ROOT / "eval" / "history.jsonl"

# The settings that plausibly change a score. Recorded per run so a later
# comparison can tell a real improvement from a configuration difference.
_TRACKED_SETTINGS = (
    "groq_chat_model",
    "eval_judge_model",
    "top_k_guidelines",
    "top_k_prior_answers",
    "query_expansion",
    "max_search_queries",
    "hybrid_search",
    "lexical_weight",
    "reranker_enabled",
    "reranker_model",
    "max_answer_attempts",
    # How much evidence reaches the drafter. Left untracked until a sweep of it
    # produced two runs whose sidecars were identical, which is exactly the
    # confusion this list exists to prevent.
    "max_evidence_chunks",
    "max_prior_answer_chunks",
    "max_expanded_parts",
    "query_agreement_weight",
    # Describes this process, not necessarily the index being queried: chunking
    # settings take effect at ingest, so a run can query an index built under
    # different ones. Re-index before trusting a comparison across a change here.
    "chunk_size",
    "chunk_overlap",
    "review_confidence_threshold",
)


def current_configuration() -> dict:
    """The tracked settings, as they stand in this process."""
    return {name: _plain(getattr(settings, name)) for name in _TRACKED_SETTINGS if hasattr(settings, name)}


def _plain(value):
    return value if isinstance(value, (str, int, float, bool, type(None))) else str(value)


def configuration_path(answers_file: str | Path) -> Path:
    """Sidecar holding the settings that produced an answers file."""
    answers = Path(answers_file)
    return answers.with_suffix(answers.suffix + ".config.json")


def save_configuration(answers_file: str | Path) -> None:
    """Record the settings in force, beside the answers they produced."""
    path = configuration_path(answers_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current_configuration(), indent=2), encoding="utf-8")


def configuration_for(answers_file: str | Path) -> tuple[dict, bool]:
    """The settings that produced `answers_file`, and whether they are its own.

    Re-scoring an archived answers file with a different judge was recording
    the *scoring* process's model and retrieval settings as though they had
    produced the answers — which is worse than recording nothing, because the
    row looks authoritative and is wrong. The sidecar is written when the
    answers are generated, so it survives being scored later by anyone.
    """
    path = configuration_path(answers_file)
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8")), True
        except ValueError:
            logger.warning("Unreadable configuration sidecar at %s", path)
    return {}, False


def record(report: dict, *, golden_set: str, answers_file: str, notes: str = "") -> dict:
    """Append one run to the history file and return the entry written."""
    produced_by, from_sidecar = configuration_for(answers_file)
    entry = {
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "label": report.get("label", ""),
        "golden_set": golden_set,
        "answers_file": answers_file,
        "notes": notes,
        "summary": report.get("summary", {}),
        "categories": report.get("categories", {}),
        "scores": {case["test_id"]: case["score"] for case in report.get("cases", [])},
        # What produced the answers. Absent for a file generated before the
        # sidecar existed, in which case it is left empty rather than guessed at.
        "configuration": produced_by,
        "configuration_known": from_sidecar,
        # What graded them. Always the scoring process, always accurate.
        "judge_model": _plain(getattr(settings, "eval_judge_model", "")),
    }

    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.info("Recorded run '%s' in %s", entry["label"], HISTORY_PATH)
    return entry


def load() -> list[dict]:
    """Every recorded run, oldest first. A corrupt line is skipped, not fatal."""
    if not HISTORY_PATH.is_file():
        return []

    entries = []
    for number, line in enumerate(HISTORY_PATH.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except ValueError:
            logger.warning("Skipping unreadable history line %d", number)
    return entries


def format_history(entries: list[dict]) -> str:
    """The history as a terminal table, oldest first."""
    if not entries:
        return f"No runs recorded yet. They will appear in {HISTORY_PATH}."

    lines = [
        f"\n=== {len(entries)} recorded runs — {HISTORY_PATH} ===",
        f"{'when':<18}{'label':<24}{'set':>5}{'acc':>8}{'facts':>8}{'review':>8}  drafter / retrieval -> judge",
    ]
    for entry in entries:
        summary = entry.get("summary", {})
        configuration = entry.get("configuration", {})
        retrieval = [f"k={configuration.get('top_k_guidelines', '?')}"]
        if configuration.get("query_expansion"):
            retrieval.append("expand")
        if configuration.get("hybrid_search"):
            retrieval.append("bm25")
        if configuration.get("reranker_enabled"):
            retrieval.append("rerank")
        if configuration.get("max_answer_attempts"):
            retrieval.append(f"tries={configuration['max_answer_attempts']}")

        model = str(configuration.get("groq_chat_model", "")).split("/")[-1]
        if not entry.get("configuration_known", True):
            model, retrieval = "(not recorded)", []
        judge = str(entry.get("judge_model", "")).split("/")[-1]
        lines.append(
            f"{entry.get('recorded_at', '')[:16]:<18}"
            f"{entry.get('label', '')[:23]:<24}"
            f"{summary.get('n', 0):>5}"
            f"{summary.get('accuracy_pct', 0):>7.1f}%"
            f"{summary.get('fact_recall_pct', 0):>7.1f}%"
            f"{summary.get('needs_review', 0):>4}/{summary.get('n', 0):<3}"
            f"  {model} · {' '.join(retrieval)}" + (f" -> {judge}" if judge else "")
        )
    return "\n".join(lines)
