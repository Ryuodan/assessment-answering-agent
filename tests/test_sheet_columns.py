"""Every column of a questionnaire's sheets, to choose where its answers go (plan 043).

Detection offered only the columns it had chosen. A file it read wrong -- its
answer column taken for a status -- left a person with no way to point the
answers at the right one, and a column set to "do not write here" vanished
from the list. Nothing here changes how a file is read.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import identity, lists, sheet_columns, tools
from src.api import app
from src.errors import QuestionnaireNotFound
from src.identity import User
from src.models import Question
from tests import forms_fixtures as shapes


@pytest.fixture
def user():
    return identity.local_user()


@pytest.fixture
def hr(user, tmp_path):
    """Status in C, comments in D, as detection reads them."""
    return tools.open_form(user, shapes.status_and_comment(tmp_path / "hr.xlsx"))


def by_letter(sheet: dict) -> dict[str, dict]:
    return {column["column"]: column for column in sheet["columns"]}


def test_every_column_beside_the_questions_is_offered_with_its_heading(user, hr) -> None:
    [sheet] = sheet_columns.every_column(user, hr.id)

    assert sheet["sheet"] == "Human Resources", "the hidden sheet of dropdown words has no questions"
    columns = by_letter(sheet)
    assert list(columns) == ["A", "B", "C", "D", "E"], "and the blank one after the last, for an empty answer column"
    assert [columns[c]["heading"] for c in "BCD"] == ["HR Security", "Compliance Status", "Additional Comments"]
    assert columns["A"]["sample"] == "1.0", "a value from beside the questions, to know a headless column by"
    assert columns["B"]["detected"] == "question"
    assert columns["C"]["detected"] == "status"
    assert columns["E"] == {"column": "E", "heading": "", "sample": "", "detected": ""}


def test_a_column_set_aside_is_still_offered(user, hr) -> None:
    tools.set_column_role(user, hr.id, "Human Resources", "D", "ignore")

    assert [c["column"] for c in tools.column_roles(user, hr.id)[0]["columns"]] == ["C"], "where answers go now"
    assert "D" in by_letter(sheet_columns.every_column(user, hr.id)[0]), "and where else they could"


def test_the_answers_can_be_pointed_at_a_column_detection_took_for_a_status(user, hr) -> None:
    """The case that needed it: a file's answers were written as a status, its answer column unused."""
    tools.set_column_role(user, hr.id, "Human Resources", "C", "answer")

    assert {c["column"]: c["role"] for c in tools.column_roles(user, hr.id)[0]["columns"]} == {"C": "answer"}
    assert by_letter(sheet_columns.every_column(user, hr.id)[0])["C"]["detected"] == "answer"


def test_a_long_cell_is_shortened(user, tmp_path) -> None:
    batch = tools.open_form(user, shapes.simple(tmp_path / "vendor.xlsx"))
    sample = by_letter(sheet_columns.every_column(user, batch.id)[0])["B"]["sample"]

    assert len(sample) == sheet_columns.SHOWN_CHARS and sample.endswith("…")


def test_a_list_has_no_columns(user) -> None:
    listed = lists.open_list(user, [Question(id="q1", text="Do you encrypt backups?")], name="typed")

    assert sheet_columns.every_column(user, listed.id) == []


def test_through_the_api_and_only_for_its_owner(user, hr) -> None:
    with TestClient(app) as client:
        body = client.get(f"/api/forms/{hr.id}/columns/every").json()
        assert [c["column"] for c in body["sheets"][0]["columns"]] == ["A", "B", "C", "D", "E"]

    stranger = User(email="someone@example.test", team_id=user.team_id, role="member")
    with pytest.raises(QuestionnaireNotFound):
        sheet_columns.every_column(stranger, hr.id)
