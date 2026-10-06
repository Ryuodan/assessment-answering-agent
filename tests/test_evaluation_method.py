"""The evaluation's method (plan 013): splits, contamination, failures kept out of scores, run comparison.

Synthetic cases throughout: the house set is customers' data and sealed, so no
test reads it. The golden set is tracked in plain text and is checked against
`src/` directly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval import contamination, splits
from eval.dataset import load_golden_set
from eval.house import Agreement, HouseCase, HouseResult, register_score, summarise
from scripts import compare_runs

ROOT = Path(__file__).resolve().parent.parent


def case(test_id: str, file: str = "a.xlsx", question: str = "Is data encrypted at rest?") -> HouseCase:
    return HouseCase(test_id=test_id, question=question, answer="Yes.", file=file)


# --- splits -------------------------------------------------------------------


def test_split_is_by_questionnaire_and_refuses_an_unassigned_one(tmp_path: Path) -> None:
    table = tmp_path / "splits.json"
    table.write_text(
        json.dumps({"dev": [splits.file_key("a.xlsx")], "final": [splits.file_key("b.xlsx")]}), encoding="utf-8"
    )
    cases = [case("1", "a.xlsx"), case("2", "b.xlsx"), case("3", "a.xlsx")]

    assert [c.test_id for c in splits.select(cases, "dev", table)] == ["1", "3"]
    assert [c.test_id for c in splits.select(cases, "final", table)] == ["2"]
    assert len(splits.select(cases, "all", table)) == 3
    with pytest.raises(ValueError, match="in no split"):
        splits.select([case("4", "c.xlsx")], "dev", table)


def test_the_committed_splits_name_no_questionnaire() -> None:
    data = json.loads(splits.SPLITS_FILE.read_text(encoding="utf-8"))
    keys = data["dev"] + data["final"]
    assert len(keys) == len(set(keys)), "a questionnaire is in both splits"
    assert all(len(key) == 12 and all(ch in "0123456789abcdef" for ch in key) for key in keys)


def test_every_look_at_the_final_split_is_recorded(tmp_path: Path) -> None:
    log = tmp_path / "final_runs.jsonl"
    assert splits.final_runs(log) == 0
    splits.record_final_run("after the prompt change", "confirming plan 0XX", {"agreement": 61.0}, log)
    splits.record_final_run("again", "a second look", {"agreement": 60.2}, log)
    assert splits.final_runs(log) == 2
    entry = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert entry["reason"] == "confirming plan 0XX" and entry["agreement"] == 61.0


# --- contamination ------------------------------------------------------------


def test_a_copied_question_is_found_and_a_shared_phrase_is_not() -> None:
    question = "Does the vendor encrypt customer data at rest using AES 256 with keys held in an HSM?"
    sources = {
        "src/prompts.py": f'EXAMPLE = "{question}"',
        "src/other.py": "# the vendor encrypt customer data",
    }
    leaks = contamination.in_sources([("q1", question), ("q2", "Is MFA enforced?")], sources)
    assert [(leak.item, leak.where) for leak in leaks] == [("q1", "src/prompts.py")]
    assert not contamination.in_sources([("q1", question)], {"src/other.py": sources["src/other.py"]})


def test_a_question_already_in_the_memory_is_found_whatever_its_punctuation() -> None:
    leaks = contamination.in_memory([("q1", "Is data encrypted at rest?")], ["is data   ENCRYPTED at rest"])
    assert [leak.item for leak in leaks] == ["q1"]


def test_no_golden_set_question_is_in_the_code() -> None:
    items = [(c.test_id, c.question) for c in load_golden_set()]
    assert items
    leaks = contamination.in_sources(items, contamination.source_texts(ROOT))
    assert not leaks, f"benchmark questions copied into src/: {[(leak.item, leak.where) for leak in leaks]}"


# --- failures are not scores --------------------------------------------------


def result(test_id: str, score: int | None, failure: str = "") -> HouseResult:
    c = case(test_id)
    form, shape = register_score(c, "Yes, it is.")
    agreement = None if score is None else Agreement(verdict="same" if score == 5 else "contradicts", score=score)
    return HouseResult(case=c, answer="Yes, it is.", register=form, shape=shape, agreement=agreement, failure=failure)


def test_failures_are_counted_apart_and_left_out_of_the_score() -> None:
    results = [
        result("1", 5),
        result("2", 5),
        result("3", None, "answering: rate limited"),
        result("4", None, "judging: failed"),
    ]
    summary = summarise(results)
    assert summary["graded"] == 2
    assert summary["agreement"] == 100.0, "a failed case must not pull the score down"
    assert summary["failures"] == {"answering": 1, "judging": 1}
    assert summary["excluded"] == 0, "a failure is not an unanswerable reference"
    assert summary["comparable"] is False


def test_a_run_with_few_failures_stays_comparable() -> None:
    results = [result(str(n), 5) for n in range(40)] + [result("x", None, "answering: timeout")]
    assert summarise(results)["comparable"] is True


# --- comparing runs -----------------------------------------------------------


def row(test_id: str, score: int | None, failure: str = "") -> dict:
    return {
        "test_id": test_id,
        "verdict": "" if score is None else "same",
        "agreement_score": score,
        "failure": failure,
    }


def test_compare_counts_moves_and_sets_noise_and_failures_apart() -> None:
    before = {r["test_id"]: r for r in [row("a", 5), row("b", 0), row("c", 3), row("d", 5), row("e", 5)]}
    after = {
        r["test_id"]: r for r in [row("a", 5), row("b", 5), row("c", 0), row("d", 3), row("e", None, "judging: failed")]
    }
    result = compare_runs.compare(before, after, unstable={"d"})
    assert result["better"] == ["b"]
    assert result["worse"] == ["c"]
    assert result["within_noise"] == ["d"]
    assert result["same"] == 1
    assert result["failed_in_either"] == 1


def test_a_known_leak_is_left_out_and_a_new_one_stops_the_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    copied = "Every privileged session is recorded and the recordings are kept for one full year"
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "prompts.py").write_text(f'EXAMPLE = "{copied}"', encoding="utf-8")
    cases = [case("H-1", question=copied), case("H-2")]

    assert contamination.screen(cases, root=tmp_path) is None, "an unrecorded leak must stop the run"

    monkeypatch.setitem(contamination.KNOWN, "H-1", "TD-999")
    assert [c.test_id for c in contamination.screen(cases, root=tmp_path)] == ["H-2"]
