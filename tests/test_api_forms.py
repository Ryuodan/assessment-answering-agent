"""The questionnaire routes, exercised through the app.

The tool tests cover what each operation decides. These cover the wiring: that
a spreadsheet is accepted where the knowledge base would refuse it, that a long
run can be watched while it is still going, that the download exists only once
the file has been filled, and that one team cannot reach another's work.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import identity, tools
from src.api import app
from src.config import settings
from src.models import AnsweredQuestion
from tests import forms_fixtures as shapes

ALICE = "m.alsaif@t2.sa"
CODE = "TEAM-CODE-FOR-TESTS"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def answers_yes(monkeypatch):
    async def fake(questions, language=None, run_id=None, **extra):
        return [
            AnsweredQuestion(
                question=question,
                answer="Yes, an approved policy is in place and reviewed annually.",
                confidence=0.9,
                needs_review=False,
                citations=["T2 - Information Security Policy.pdf §3.1"],
            )
            for question in questions
        ]

    monkeypatch.setattr("src.tools.service.answer_questions", fake)


def _upload(client, path, name=None):
    with open(path, "rb") as handle:
        return client.post(
            "/api/forms",
            files={
                "file": (
                    name or path.name,
                    handle.read(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )


# --- the two pages ---------------------------------------------------------


def test_the_front_door_is_the_conversation(client):
    """A person meeting this for the first time should meet the thing that
    needs nothing explained. The workbench is where you go for the controls."""
    body = client.get("/").text
    assert 'id="prompt"' in body, "the composer, so this is the conversation"
    assert "<title>Assessment Answering Agent</title>" in body
    assert 'href="workbench"' in body, "and it has to say how to reach the other one"


def test_the_workbench_has_its_own_address(client):
    body = client.get("/workbench").text
    assert 'id="questionList"' in body, "the question list, so this is the workbench"
    assert "<title>Workbench" in body


def test_the_old_chat_address_still_arrives(client):
    """Somebody has this bookmarked. A moved page is a redirect, not a 404."""
    moved = client.get("/chat", follow_redirects=False)
    # Relative, so it stays inside the prefix the deployment serves the app under.
    assert moved.status_code == 308 and moved.headers["location"] == "./"
    assert 'id="prompt"' in client.get("/chat").text


# --- opening ---------------------------------------------------------------


def test_a_spreadsheet_is_accepted(client, tmp_path):
    """The knowledge base takes only PDF and Word. Checking a questionnaire
    against that list refused every .xlsx before the parser saw it."""
    response = _upload(client, shapes.simple(tmp_path / "vendor.xlsx"))
    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["questions"] == 4
    assert body["format"] == "xlsx"


def test_opening_reports_what_was_found_without_answering(client, tmp_path):
    body = _upload(client, shapes.legend_sheet(tmp_path / "legend.xlsx")).json()
    assert body["counts"]["answered"] == 0
    used = [part for part in body["parts"] if part["used"]]
    skipped = [part for part in body["parts"] if not part["used"]]
    assert [part["name"] for part in used] == ["Questions"]
    assert skipped and skipped[0]["findings"][0]["because"]


def test_uncertain_readings_are_flagged_for_confirmation(client, tmp_path):
    body = _upload(client, shapes.headless_numbered(tmp_path / "headless.xlsx")).json()
    findings = [f for part in body["parts"] for f in part["findings"]]
    assert any(not finding["confident"] for finding in findings)


def test_a_file_type_that_is_not_a_form_is_refused(client, tmp_path):
    path = tmp_path / "policy.pdf"
    path.write_bytes(b"%PDF-1.4")
    response = _upload(client, path)
    assert response.status_code == 400
    assert ".pdf is not a questionnaire" in response.json()["detail"]


def test_an_unreadable_questionnaire_is_a_422(client, tmp_path):
    path = tmp_path / "broken.xlsx"
    path.write_bytes(b"not a spreadsheet")
    response = _upload(client, path)
    assert response.status_code == 422
    assert "not a readable" in response.json()["detail"]


def test_questionnaires_are_listed(client, tmp_path):
    _upload(client, shapes.simple(tmp_path / "one.xlsx"))
    _upload(client, shapes.simple(tmp_path / "two.xlsx"))
    listed = client.get("/api/forms").json()["forms"]
    assert [form["source_name"] for form in listed] == ["two.xlsx", "one.xlsx"]


def test_an_unknown_questionnaire_is_a_404(client):
    assert client.get("/api/forms/nope").status_code == 404


# --- answering -------------------------------------------------------------


def test_answering_returns_the_batch_with_its_answers(client, tmp_path, answers_yes):
    batch_id = _upload(client, shapes.simple(tmp_path / "vendor.xlsx")).json()["id"]
    body = client.post(f"/api/forms/{batch_id}/answer", json={}).json()

    assert body["attempted"] == 4 and body["answered"] == 4
    assert body["batch"]["counts"]["answered"] == 4
    assert all(question["answer"] for question in body["batch"]["questions"])


def test_a_scope_narrows_what_is_answered(client, tmp_path, answers_yes):
    batch_id = _upload(client, shapes.simple(tmp_path / "vendor.xlsx")).json()["id"]
    body = client.post(f"/api/forms/{batch_id}/answer", json={"scope": {"matching": "multi-factor"}}).json()
    assert body["attempted"] == 1 and body["scope"] == "mentioning 'multi-factor'"


def test_the_batch_id_is_the_run_id(client, tmp_path, monkeypatch):
    """A large questionnaire is minutes of silence otherwise, and the interface
    polls `/api/assessments/progress/{id}` to fill it. That only works if the id
    it already has -- the batch -- is the one progress is filed under.

    Asserted on the id handed to the pipeline rather than on a progress
    snapshot, because the stand-in below replaces the very function that starts
    the tracking. Progress itself belongs to `service` and is tested there.
    """
    seen: dict = {}

    async def fake(questions, language=None, run_id=None, **extra):
        seen["run_id"] = run_id
        return [AnsweredQuestion(question=q, answer="Yes.", confidence=0.9) for q in questions]

    monkeypatch.setattr("src.tools.service.answer_questions", fake)
    batch_id = _upload(client, shapes.simple(tmp_path / "vendor.xlsx")).json()["id"]
    client.post(f"/api/forms/{batch_id}/answer", json={})
    assert seen["run_id"] == batch_id


def test_revising_needs_an_instruction(client, tmp_path, answers_yes):
    batch_id = _upload(client, shapes.simple(tmp_path / "vendor.xlsx")).json()["id"]
    assert client.post(f"/api/forms/{batch_id}/revise", json={"instruction": ""}).status_code == 422


def test_revising_rewrites_what_is_already_answered(client, tmp_path, answers_yes):
    batch_id = _upload(client, shapes.simple(tmp_path / "vendor.xlsx")).json()["id"]
    client.post(f"/api/forms/{batch_id}/answer", json={})
    body = client.post(f"/api/forms/{batch_id}/revise", json={"instruction": "Keep it to one sentence."}).json()
    assert body["attempted"] == 4


# --- correcting ------------------------------------------------------------


def test_an_answer_can_be_written_by_hand(client, tmp_path, answers_yes):
    opened = _upload(client, shapes.simple(tmp_path / "vendor.xlsx")).json()
    question = opened["questions"][0]["id"]
    body = client.post(
        f"/api/forms/{opened['id']}/answers",
        json={"question_id": question, "text": "We use AES-256 throughout."},
    ).json()

    written = next(q for q in body["questions"] if q["id"] == question)
    assert written["answer"] == "We use AES-256 throughout."
    assert written["edited_by"] == identity.LOCAL_EMAIL


def test_a_broad_answer_request_does_not_replace_the_files_own_answers(client, tmp_path, answers_yes):
    """The route the workbench calls when somebody presses Answer. Whatever the
    page sends, the two questions the file arrived answered stay as they are."""
    opened = _upload(client, shapes.already_answered(tmp_path / "last year.xlsx")).json()
    outcome = client.post(f"/api/forms/{opened['id']}/answer", json={}).json()

    assert outcome["attempted"] == 2 and outcome["protected"] == 2
    kept = outcome["batch"]["questions"][0]
    assert kept["existing"].startswith("Yes. The HR process")
    assert not kept["answer"]


def test_replacing_an_answer_takes_saying_so(client, tmp_path, answers_yes):
    opened = _upload(client, shapes.already_answered(tmp_path / "last year.xlsx")).json()
    question = opened["questions"][0]["id"]
    outcome = client.post(
        f"/api/forms/{opened['id']}/answer",
        json={"scope": {"ids": [question]}, "replace_existing": True},
    ).json()

    assert outcome["attempted"] == 1
    written = next(q for q in outcome["batch"]["questions"] if q["id"] == question)
    assert written["answer"].startswith("Yes, an approved policy")


def test_an_answer_can_be_left_blank_and_brought_back(client, tmp_path, answers_yes):
    opened = _upload(client, shapes.simple(tmp_path / "vendor.xlsx")).json()
    question = opened["questions"][0]["id"]
    client.post(f"/api/forms/{opened['id']}/answer", json={})

    blanked = client.post(
        f"/api/forms/{opened['id']}/blank",
        json={"question_id": question},
    ).json()
    assert next(q for q in blanked["questions"] if q["id"] == question)["blanked"]

    # And the cell is written empty, so last year's answer is cleared rather
    # than left standing.
    assert client.post(f"/api/forms/{opened['id']}/fill").json()["written"] == 4

    back = client.post(
        f"/api/forms/{opened['id']}/blank",
        json={"question_id": question, "blank": False},
    ).json()
    restored = next(q for q in back["questions"] if q["id"] == question)
    assert not restored["blanked"] and not restored["answer"]


def test_blanking_a_question_the_file_does_not_have_is_a_400(client, tmp_path):
    batch_id = _upload(client, shapes.simple(tmp_path / "vendor.xlsx")).json()["id"]
    response = client.post(f"/api/forms/{batch_id}/blank", json={"question_id": "nope"})
    assert response.status_code == 400


def test_writing_an_unknown_question_is_a_400(client, tmp_path):
    batch_id = _upload(client, shapes.simple(tmp_path / "vendor.xlsx")).json()["id"]
    response = client.post(f"/api/forms/{batch_id}/answers", json={"question_id": "nope", "text": "x"})
    assert response.status_code == 400


def test_withdrawing_an_approval_over_http_restores_the_review(client, tmp_path, monkeypatch):
    """TD-053, through the route both pages call."""

    async def flagged(questions, language=None, run_id=None, **extra):
        return [
            AnsweredQuestion(
                question=q,
                answer="Yes.",
                confidence=0.85,
                needs_review=True,
                review_reasons=["the reviewer did not find the answer grounded"],
            )
            for q in questions
        ]

    monkeypatch.setattr("src.tools.service.answer_questions", flagged)
    opened = _upload(client, shapes.simple(tmp_path / "vendor.xlsx")).json()
    question = opened["questions"][0]["id"]
    client.post(f"/api/forms/{opened['id']}/answer", json={})

    approved = client.post(f"/api/forms/{opened['id']}/approve", json={"question_id": question}).json()
    shown = next(q for q in approved["questions"] if q["id"] == question)
    assert shown["will_be_written"] is True
    assert shown["answered"]["before_approval"] == {"needs_review": True, "confidence_reason": ""}

    withdrawn = client.post(
        f"/api/forms/{opened['id']}/approve", json={"question_id": question, "approved": False}
    ).json()
    shown = next(q for q in withdrawn["questions"] if q["id"] == question)
    assert shown["needs_review"] is True and shown["will_be_written"] is False
    assert shown["answered"]["before_approval"] is None


def test_an_empty_brief_is_a_400(client, tmp_path, answers_yes):
    opened = _upload(client, shapes.simple(tmp_path / "vendor.xlsx")).json()
    question = opened["questions"][0]["id"]
    client.post(f"/api/forms/{opened['id']}/answer", json={})

    response = client.post(
        f"/api/forms/{opened['id']}/answers", json={"question_id": question, "text": "", "which": "brief"}
    )

    assert response.status_code == 400 and response.json()["code"] == "operation_refused"


# --- filling and downloading -----------------------------------------------


def test_the_download_does_not_exist_until_the_form_is_filled(client, tmp_path, answers_yes):
    batch_id = _upload(client, shapes.simple(tmp_path / "vendor.xlsx")).json()["id"]
    client.post(f"/api/forms/{batch_id}/answer", json={})
    assert client.get(f"/api/forms/{batch_id}/file").status_code == 404

    filled = client.post(f"/api/forms/{batch_id}/fill").json()
    assert filled["written"] == 4 and filled["intact"] is True

    download = client.get(f"/api/forms/{batch_id}/file")
    assert download.status_code == 200
    assert download.content[:2] == b"PK", "a real .xlsx comes back"


def test_writing_anyway_over_http_writes_only_the_answers_named(client, tmp_path, monkeypatch):
    """Plan 029's review: "Write them in anyway" names the held answers the person
    agreed to, and the response says how many went in."""

    async def flagged(questions, language=None, run_id=None, **extra):
        return [AnsweredQuestion(question=q, answer="Yes.", confidence=0.3, needs_review=True) for q in questions]

    monkeypatch.setattr("src.tools.service.answer_questions", flagged)
    opened = _upload(client, shapes.simple(tmp_path / "vendor.xlsx")).json()
    first, second = (q["id"] for q in opened["questions"][:2])
    client.post(f"/api/forms/{opened['id']}/answer", json={})

    gated = client.post(f"/api/forms/{opened['id']}/fill", json={"include_unreviewed": False}).json()
    assert len(gated["held_back"]) == 4 and gated["written_anyway"] == 0

    anyway = client.post(
        f"/api/forms/{opened['id']}/fill", json={"include_unreviewed": True, "unreviewed_ids": [first, second]}
    ).json()
    assert anyway["written_anyway"] == 2 and anyway["written"] == 2
    assert first not in anyway["held_back"] and len(anyway["held_back"]) == 2


def test_filling_reports_what_was_left_blank_and_why(client, tmp_path, answers_yes):
    path = shapes.build(
        tmp_path / "ev.xlsx",
        [
            shapes.SheetSpec(
                "Q",
                {
                    "A1": "S.No",
                    "B1": "Question",
                    "C1": "Response",
                    "D1": "Evidence",
                    "A2": "1.0",
                    "B2": "Does the vendor have documented security policies?",
                    "A3": "2.0",
                    "B3": "Does the vendor review those policies annually?",
                    "A4": "3.0",
                    "B4": "Are staff bound by non-disclosure agreements?",
                },
            )
        ],
    )
    batch_id = _upload(client, path).json()["id"]
    client.post(f"/api/forms/{batch_id}/answer", json={})
    filled = client.post(f"/api/forms/{batch_id}/fill").json()
    assert any("evidence" in why for why in filled["blank"].values())


def test_a_status_column_is_filled_from_the_files_own_words(client, tmp_path, answers_yes):
    batch_id = _upload(client, shapes.status_and_comment(tmp_path / "woodgrove.xlsx")).json()["id"]
    client.post(f"/api/forms/{batch_id}/answer", json={})
    client.post(f"/api/forms/{batch_id}/fill")

    from src.forms.xlsx_package import Workbook
    from src import batches as batch_store

    batch = batch_store.load(batch_id)
    with Workbook(tools._filled_path(batch)) as workbook:
        assert workbook["Human Resources"].value(2, "C") == "Fully Compliant"


# --- who may see what ------------------------------------------------------


def test_a_questionnaire_is_scoped_to_its_team(client, tmp_path, monkeypatch):
    """Another team's id reads as absent, not forbidden: which ids exist is not
    something a caller should learn."""
    batch_id = _upload(client, shapes.simple(tmp_path / "vendor.xlsx")).json()["id"]

    identity.ensure_team("privacy")
    identity.update_user(identity.LOCAL_EMAIL, team_id="privacy")
    assert client.get(f"/api/forms/{batch_id}").status_code == 404
    assert client.get("/api/forms").json()["forms"] == []


def test_the_routes_need_a_session_when_sign_in_is_on(client, tmp_path):
    identity.ensure_team(settings.default_team)
    identity.set_access_code(settings.default_team, CODE)
    identity.add_user(ALICE)

    assert client.get("/api/forms").status_code == 401
    assert client.post("/api/forms/anything/fill").status_code == 401

    client.post("/api/auth/session", json={"email": ALICE, "code": CODE})
    assert client.get("/api/forms").status_code == 200


# --- correcting what detection decided --------------------------------------


def test_the_column_mapping_is_reported(client, tmp_path):
    """Detection proposes; this is the other half of that sentence."""
    batch_id = _upload(client, shapes.status_and_comment(tmp_path / "woodgrove.xlsx")).json()["id"]
    [sheet] = client.get(f"/api/forms/{batch_id}/columns").json()["sheets"]
    assert sheet["sheet"] == "Human Resources"
    assert {c["column"]: c["role"] for c in sheet["columns"]} == {"C": "status", "D": "answer"}


def test_a_column_can_be_corrected(client, tmp_path, answers_yes):
    """The consequential correction: the answers were going into the wrong
    column, and a person can move them before anything is written."""
    batch_id = _upload(client, shapes.simple(tmp_path / "vendor.xlsx")).json()["id"]
    body = client.post(
        f"/api/forms/{batch_id}/columns", json={"sheet": "Questionnaire", "column": "E", "role": "answer"}
    ).json()
    assert body["questions"][0]["targets"][0]["id"] == "Questionnaire!E2"

    client.post(f"/api/forms/{batch_id}/answer", json={})
    client.post(f"/api/forms/{batch_id}/fill")

    from src import batches as batch_store
    from src.forms.xlsx_package import Workbook

    with Workbook(tools._filled_path(batch_store.load(batch_id))) as workbook:
        sheet = workbook["Questionnaire"]
        assert sheet.value(2, "E").startswith("Yes, an approved policy")
        assert sheet.value(2, "C") == "", "the column it used to use is left alone"


def test_a_column_can_be_switched_off(client, tmp_path, answers_yes):
    batch_id = _upload(client, shapes.simple(tmp_path / "vendor.xlsx")).json()["id"]
    body = client.post(
        f"/api/forms/{batch_id}/columns", json={"sheet": "Questionnaire", "column": "C", "role": "ignore"}
    ).json()
    assert body["questions"][0]["targets"] == []


def test_a_column_belonging_to_the_other_party_cannot_be_chosen(client, tmp_path):
    batch_id = _upload(client, shapes.simple(tmp_path / "vendor.xlsx")).json()["id"]
    response = client.post(
        f"/api/forms/{batch_id}/columns", json={"sheet": "Questionnaire", "column": "D", "role": "theirs"}
    )
    assert response.status_code == 400
    assert "cannot be written" in response.json()["detail"]


def test_a_question_can_be_set_aside_and_brought_back(client, tmp_path, answers_yes):
    """Detection over-reports on purpose, so unticking a row is ordinary."""
    opened = _upload(client, shapes.simple(tmp_path / "vendor.xlsx")).json()
    first = opened["questions"][0]["id"]

    body = client.patch(f"/api/forms/{opened['id']}/questions", json={"changes": [{"id": first, "skip": True}]}).json()
    assert body["questions"][0]["skip"] is True

    answered = client.post(f"/api/forms/{opened['id']}/answer", json={}).json()
    assert answered["attempted"] == 3, "a question set aside is not answered"

    back = client.patch(f"/api/forms/{opened['id']}/questions", json={"changes": [{"id": first, "skip": False}]}).json()
    assert back["questions"][0]["skip"] is False


def test_a_question_set_aside_is_never_written(client, tmp_path, answers_yes):
    opened = _upload(client, shapes.simple(tmp_path / "vendor.xlsx")).json()
    client.post(f"/api/forms/{opened['id']}/answer", json={})
    client.patch(
        f"/api/forms/{opened['id']}/questions", json={"changes": [{"id": opened["questions"][0]["id"], "skip": True}]}
    )

    filled = client.post(f"/api/forms/{opened['id']}/fill").json()
    assert filled["written"] == 3


def test_a_questions_wording_can_be_corrected(client, tmp_path):
    opened = _upload(client, shapes.simple(tmp_path / "vendor.xlsx")).json()
    body = client.patch(
        f"/api/forms/{opened['id']}/questions",
        json={
            "changes": [
                {"id": opened["questions"][0]["id"], "text": "Do you hold ISO 27001 certification?"},
            ]
        },
    ).json()
    assert body["questions"][0]["text"] == "Do you hold ISO 27001 certification?"


def test_correcting_is_recorded(client, tmp_path):
    from src import batches as batch_store, events

    opened = _upload(client, shapes.simple(tmp_path / "vendor.xlsx")).json()
    client.post(f"/api/forms/{opened['id']}/columns", json={"sheet": "Questionnaire", "column": "E", "role": "answer"})
    kinds = [e.kind for e in events.for_subject(batch_store.SUBJECT, opened["id"])]
    assert events.ROLES_CORRECTED in kinds


def test_an_answer_carries_its_sources_and_reasoning(client, tmp_path, answers_yes):
    """The interface shows the evidence and why an answer was flagged. A
    confidence number with nothing behind it is not something anyone can check."""
    batch_id = _upload(client, shapes.simple(tmp_path / "vendor.xlsx")).json()["id"]
    body = client.post(f"/api/forms/{batch_id}/answer", json={}).json()
    answered = body["batch"]["questions"][0]["answered"]
    assert answered["citations"] == ["T2 - Information Security Policy.pdf §3.1"]
    assert "evidence" in answered and "review_reasons" in answered
    assert "confidence_reason" in answered


def test_the_filled_file_is_served_as_what_it_is(client, tmp_path, answers_yes):
    """Served as an unknown blob, a browser has nothing to hand it to."""
    opened = _upload(client, shapes.simple(tmp_path / "vendor.xlsx")).json()
    client.post(f"/api/forms/{opened['id']}/answer", json={})
    client.post(f"/api/forms/{opened['id']}/fill")

    response = client.get(f"/api/forms/{opened['id']}/file")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "attachment" in response.headers["content-disposition"]


def test_rewording_can_be_held_to_the_answers_just_written(client, tmp_path, answers_yes, monkeypatch):
    """A questionnaire is answered in sittings. The wording box beside the
    answer button applies to that sitting only -- an earlier one may hold
    answers somebody has since read and corrected by hand, and rewording those
    because a later batch asked for a house style throws that work away."""
    from src import rewrite

    async def shorten(answered, instruction, language=None):
        revised = answered.model_copy(deep=True)
        revised.answer = "Reworded."
        return revised

    opened = _upload(client, shapes.simple(tmp_path / "vendor.xlsx")).json()
    ids = [q["id"] for q in opened["questions"]]

    client.post(f"/api/forms/{opened['id']}/answer", json={"scope": {"ids": ids[:2]}})
    client.post(f"/api/forms/{opened['id']}/answers", json={"question_id": ids[0], "text": "Corrected by a person."})
    client.post(f"/api/forms/{opened['id']}/answer", json={"scope": {"ids": ids[2:]}})

    monkeypatch.setattr(rewrite, "rewrite", shorten)
    outcome = client.post(
        f"/api/forms/{opened['id']}/revise",
        json={
            "instruction": "Keep it short.",
            "scope": {"ids": ids[2:]},
        },
    ).json()

    assert outcome["attempted"] == 2
    answers = {q["id"]: q["answer"] for q in outcome["batch"]["questions"]}
    assert answers[ids[0]] == "Corrected by a person.", "the hand-edited answer is untouched"
    assert answers[ids[2]] == "Reworded."
    assert answers[ids[3]] == "Reworded."


def test_an_edited_answer_is_what_gets_written(client, tmp_path, answers_yes):
    """The bug this closes: an edit made on an answer card lived only in the
    page. It went into every download and *not* into the filled spreadsheet --
    the one place a reviewer would swear they had corrected it."""
    opened = _upload(client, shapes.status_and_comment(tmp_path / "hr.xlsx")).json()
    client.post(f"/api/forms/{opened['id']}/answer", json={})
    client.post(
        f"/api/forms/{opened['id']}/answers",
        json={
            "question_id": opened["questions"][1]["id"],
            "text": "No, this is not in place.",
        },
    )
    client.post(f"/api/forms/{opened['id']}/fill")

    from src.forms.xlsx_package import Workbook
    from src import tools as tool_module

    batch = tool_module.batches.load(opened["id"])
    with Workbook(tool_module._filled_path(batch)) as workbook:
        sheet = workbook["Human Resources"]
        assert sheet.value(3, "D") == "No, this is not in place."
        assert sheet.value(3, "C") == "Non Compliant", (
            "the status is re-read from the person's words, not left as the model's"
        )
