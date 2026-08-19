"""The evaluation history file.

A run is only comparable to another when you can see what was configured
differently, so the settings travel with the scores.
"""

from __future__ import annotations

import json

import pytest

from eval import history
from src.config import settings


@pytest.fixture(autouse=True)
def history_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_PATH", tmp_path / "history.jsonl")


def _report(label="run", accuracy=70.0):
    return {
        "label": label,
        "summary": {"n": 2, "accuracy_pct": accuracy, "fact_recall_pct": 50.0, "needs_review": 1},
        "categories": {"Direct Extraction": {"n": 2, "accuracy_pct": accuracy, "points": 7}},
        "cases": [{"test_id": "TC-001", "score": 4}, {"test_id": "TC-002", "score": 3}],
    }


def test_a_recorded_run_captures_the_settings_that_produced_it(tmp_path):
    answers = tmp_path / "run.json"
    answers.write_text("{}", encoding="utf-8")
    history.save_configuration(answers)

    entry = history.record(_report(), golden_set="golden.json", answers_file=str(answers))

    assert entry["configuration"]["top_k_guidelines"] == settings.top_k_guidelines
    assert entry["configuration"]["query_expansion"] == settings.query_expansion
    assert entry["configuration_known"] is True
    assert entry["judge_model"] == settings.eval_judge_model
    assert entry["scores"] == {"TC-001": 4, "TC-002": 3}


def test_settings_are_left_empty_rather_than_guessed_when_unknown():
    """Re-scoring an archived file must not claim the scorer's settings made it."""
    entry = history.record(_report(), golden_set="golden.json", answers_file="never_written.json")

    assert entry["configuration"] == {}
    assert entry["configuration_known"] is False
    # The judge is always knowable, because this process is the one grading.
    assert entry["judge_model"] == settings.eval_judge_model


def test_an_unknown_configuration_is_shown_as_such():
    history.record(_report("archived"), golden_set="g.json", answers_file="never_written.json")
    assert "(not recorded)" in history.format_history(history.load())


def test_runs_accumulate_rather_than_overwrite():
    history.record(_report("first", 60.0), golden_set="g.json", answers_file="a.json")
    history.record(_report("second", 75.0), golden_set="g.json", answers_file="b.json")

    entries = history.load()

    assert [entry["label"] for entry in entries] == ["first", "second"]


def test_a_corrupt_line_costs_one_record_not_the_file():
    history.record(_report("good"), golden_set="g.json", answers_file="a.json")
    with history.HISTORY_PATH.open("a", encoding="utf-8") as handle:
        handle.write("{ truncated\n")
    history.record(_report("also good"), golden_set="g.json", answers_file="b.json")

    assert [entry["label"] for entry in history.load()] == ["good", "also good"]


def test_history_is_empty_before_any_run():
    assert history.load() == []
    assert "No runs recorded yet" in history.format_history([])


def test_formatted_history_names_the_configuration(tmp_path):
    answers = tmp_path / "a.json"
    answers.write_text("{}", encoding="utf-8")
    history.save_configuration(answers)
    history.record(_report("with-expansion"), golden_set="g.json", answers_file=str(answers))

    rendered = history.format_history(history.load())

    assert "with-expansion" in rendered
    assert "k=" in rendered
    # The judge belongs on the row too: it sets the scale the score is on.
    assert settings.eval_judge_model.split("/")[-1] in rendered


def test_records_are_valid_json_lines():
    history.record(_report("one"), golden_set="g.json", answers_file="a.json")
    history.record(_report("two"), golden_set="g.json", answers_file="b.json")

    lines = history.HISTORY_PATH.read_text(encoding="utf-8").strip().split("\n")

    assert len(lines) == 2
    assert all(json.loads(line)["label"] for line in lines)


# --- the golden set itself -------------------------------------------------


def test_the_extended_golden_set_is_well_formed():
    """A malformed case would be found only when a scoring run wasted its budget."""
    from eval.dataset import load_golden_set

    cases = load_golden_set()
    ids = [case.test_id for case in cases]

    assert len(cases) >= 42
    assert len(ids) == len(set(ids)), "duplicate test ids"
    for case in cases:
        assert case.expected_core_facts, f"{case.test_id} has no expected facts"
        assert case.question.strip(), f"{case.test_id} has no question"
        assert case.question_language in ("ar", "en"), case.test_id


def test_the_new_cases_cover_the_added_corpus():
    from eval.dataset import load_golden_set

    categories = {case.category for case in load_golden_set()}

    assert "Regulatory Reference" in categories
    assert "Cross-Source Synthesis" in categories


def test_arabic_cases_are_asked_in_arabic():
    from eval.dataset import load_golden_set

    for case in load_golden_set():
        if case.question_language == "ar":
            assert case.as_question(0).language == "ar", case.test_id
