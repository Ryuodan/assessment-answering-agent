"""The scoring behind the two numbers the system is judged by.

`eval/house.py` had no tests, and it produces the only figures anybody quotes
about this system: how often it writes what the security team would have
written, on questions the memory has never seen, and on questions it holds.
What those numbers *mean* depends on two things that are easy to get wrong and
were both wrong at some point -- which half of a set an average came from, and
which side of the review gate a count is on.
"""

from __future__ import annotations

from eval.house import (
    NEAR_TWIN,
    HouseCase,
    HouseResult,
    Agreement,
    Register,
    format_summary,
    load_house_set,
    load_memory_set,
    summarise,
)


def result(**overrides) -> HouseResult:
    case = HouseCase(
        test_id=overrides.pop("test_id", "T1"),
        question=overrides.pop("question", "Do you encrypt backups?"),
        answer=overrides.pop("reference", "Yes, backups are encrypted."),
        file=overrides.pop("file", "vendor.xlsx"),
    )
    shape = Register(words=12, opens_with_verdict=True, cites_a_clause=False, hedges=False)
    base = dict(case=case, answer="Yes, with AES-256.", register=1.0, shape=shape)
    score = overrides.pop("score", 5)
    base.update(overrides)
    item = HouseResult(**base)
    item.agreement = Agreement(
        verdict=overrides.get("verdict", "same"), score=score, note="",
    )
    return item


# --- the review gate, the right way round -----------------------------------


def test_held_back_counts_what_a_person_has_to_read():
    """This was reported as its own opposite -- "would be written into the file
    unreviewed" -- which inverts the one number in the summary that says how
    much human work a run leaves behind."""
    results = [
        result(test_id="A", needs_review=True, confidence=0.9),
        result(test_id="B", needs_review=False, confidence=0.2),
        result(test_id="C", needs_review=False, confidence=0.9),
        result(test_id="D", needs_review=False, confidence=0.95),
    ]

    summary = summarise(results)

    assert summary["held_back"] == 2, "flagged, or below the floor"
    assert "held back for a person to read: 2 of 4" in format_summary("x", summary)
    assert "2 would be written as they stand" in format_summary("x", summary)


# --- which half of the set a number came from -------------------------------


def test_the_score_is_split_by_whether_the_memory_had_a_twin():
    """A single held-out average mixes two different questions: can it reuse an
    answer we have given before, and can it answer something new from the
    policies. Which one a case is depends on the customer who sent the form."""
    results = [
        result(test_id="near-1", twin=0.95, score=5),
        result(test_id="near-2", twin=NEAR_TWIN, score=5),
        result(test_id="far-1", twin=0.61, score=1),
        result(test_id="far-2", twin=0.40, score=1),
    ]

    summary = summarise(results)

    assert summary["with_a_twin"] == {"cases": 2, "agreement": 100.0, "form": 100.0}
    assert summary["without_a_twin"]["cases"] == 2
    assert summary["without_a_twin"]["agreement"] == 20.0
    assert summary["agreement"] == 60.0, "the average of the two halves it is made of"


def test_an_empty_half_reports_nothing_rather_than_dividing_by_zero():
    summary = summarise([result(twin=0.99)])
    assert summary["without_a_twin"] == {"cases": 0, "agreement": 0.0, "form": 0.0}


def test_finding_its_own_answer_is_reported_as_a_share():
    results = [result(test_id="A", found_own_answer=True), result(test_id="B")]
    assert summarise(results)["found_own_answer"] == 50.0


# --- the sets themselves ----------------------------------------------------


def test_the_two_sets_share_no_questionnaire():
    """What makes the held-out number an estimate of the real thing.

    The split is by file, not by row: the questionnaires behind the answer
    memory and the ones graded against it are different customers' forms. A
    re-import that let one file into both would quietly turn the headline
    number into a measure of recall.
    """
    held_out, remembered = load_house_set(), load_memory_set()

    assert held_out and remembered
    assert not ({c.file for c in held_out} & {c.file for c in remembered})


def test_every_case_carries_a_reference_answer():
    """A case with no reference cannot be graded, and would be averaged in as
    a zero rather than excluded."""
    for case in load_house_set() + load_memory_set():
        assert case.question.strip(), case.test_id
        assert case.answer.strip(), case.test_id


# --- how close the memory already was ---------------------------------------


async def test_the_nearest_remembered_question_is_found(monkeypatch):
    """Normalised once and compared by dot product. The naive version
    recomputed both norms inside a 698x698 loop and spent minutes of CPU
    before the first question was answered."""
    import eval.house as house

    vectors = {
        "Do you encrypt backups?": [1.0, 0.0, 0.0],
        "Are backups encrypted?": [0.9, 0.1, 0.0],
        "Who is the DPO?": [0.0, 1.0, 0.0],
    }

    class Fake:
        def embed_documents(self, texts):
            return [vectors[text] for text in texts]

    monkeypatch.setattr("src.embeddings.get_embeddings", lambda: Fake())

    asked = [house.HouseCase(test_id="A", question="Do you encrypt backups?", answer="Yes")]
    remembered = [
        house.HouseCase(test_id="M1", question="Are backups encrypted?", answer="Yes"),
        house.HouseCase(test_id="M2", question="Who is the DPO?", answer="Nobody"),
    ]

    [twin] = await house.nearest_in_memory(asked, remembered)

    assert 0.99 < twin <= 1.0, "the paraphrase, not the unrelated question"
    assert await house.nearest_in_memory(asked, []) == [0.0], "an empty memory is not an error"


# --- the spreadsheet a person reads -----------------------------------------


def test_the_report_has_the_columns_it_was_asked_for(tmp_path):
    """The deliverable is the workbook, not the JSON: file, question, the
    team's answer, ours, and the judge's mark."""
    import pytest

    pytest.importorskip("openpyxl", reason="pip install -e '.[reports]'")
    from openpyxl import load_workbook

    from scripts.eval_to_xlsx import build

    out = build({
        "label": "a run",
        "summary": {"graded": 1, "agreement": 80.0, "form": 100.0, "held_back": 1,
                    "median_words_ours": 40, "median_words_theirs": 12,
                    "with_a_twin": {"cases": 0, "agreement": 0.0},
                    "without_a_twin": {"cases": 1, "agreement": 80.0}},
        "cases": [{
            "test_id": "T1", "file": "vendor.xlsx", "question": "Do you encrypt backups?",
            "reference": "Yes.", "answer": "Yes, with AES-256.", "verdict": "broader",
            "agreement_score": 4, "note": "same position, more detail",
            "confidence": 0.9, "needs_review": True, "twin": 0.71,
            "found_own_answer": False,
        }],
    }, tmp_path / "report.xlsx", "A run")

    sheet = load_workbook(out)["Results"]
    assert [cell.value for cell in sheet[1]][:5] == [
        "file name", "question", "real answer", "generated answer", "Judge score/approval",
    ]
    assert [cell.value for cell in sheet[2]][:5] == [
        "vendor.xlsx", "Do you encrypt backups?", "Yes.", "Yes, with AES-256.", "4/5 agrees",
    ]
    assert "cited its own memory entry" not in [cell.value for cell in sheet[1]], (
        "a column empty on every row invites the reader to wonder what broke"
    )
    assert sheet["I2"].value == "held for review"
