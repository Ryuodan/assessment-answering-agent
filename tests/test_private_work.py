"""What a person does is theirs; what the team decides is the team's.

Conversations, questionnaires and answered runs were scoped to a team: every
member's history listed every member's, and any of them could be opened by id.
A questionnaire arrives from another company, usually under an NDA, and a
conversation is what somebody said while they were working -- half-formed
instructions, corrections, a file nobody else has any business reading.

What stays shared is what the team is bound by: the policies in the knowledge
base, and the answer memory, which is the record of how this organisation
answers. These tests hold that line from both sides, through the routes a
person actually uses.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import conversations, identity, runs
from src.agents import assistant
from src.api import app
from src.config import settings
from src.models import AnsweredQuestion, AssessmentResult, Question
from tests import forms_fixtures as shapes

ALICE = "m.alsaif@t2.sa"
BOB = "mohammed.sa.alsaif@gmail.com"
CODE = "TEAM-CODE-FOR-TESTS"


@pytest.fixture
def team():
    identity.ensure_team(settings.default_team, name="Cybersecurity")
    identity.set_access_code(settings.default_team, CODE)
    identity.add_user(ALICE)
    identity.add_user(BOB)


def as_person(email: str) -> TestClient:
    client = TestClient(app)
    assert client.post("/api/auth/session", json={"email": email, "code": CODE}).status_code == 200
    return client


def a_person(email: str) -> identity.User:
    return identity.User(email=email, team_id=settings.default_team)


def _open(client, tmp_path, name="vendor.xlsx"):
    path = tmp_path / name
    if not path.exists():
        shapes.simple(path)
    with open(path, "rb") as handle:
        return client.post(
            "/api/forms",
            files={
                "file": (
                    name,
                    handle.read(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        ).json()


# --- conversations ---------------------------------------------------------------------


def test_a_conversation_is_listed_only_for_the_person_who_had_it(team):
    mine = assistant.start(a_person(ALICE), "Answer the Barq questionnaire")
    theirs = assistant.start(a_person(BOB), "What does our retention policy say?")

    alice, bob = as_person(ALICE), as_person(BOB)

    assert [c["id"] for c in alice.get("/api/chat").json()["conversations"]] == [mine.id]
    assert [c["id"] for c in bob.get("/api/chat").json()["conversations"]] == [theirs.id]


def test_a_colleague_cannot_open_or_forget_your_conversation(team):
    mine = assistant.start(a_person(ALICE), "Answer the Barq questionnaire")
    bob = as_person(BOB)

    assert bob.get(f"/api/chat/{mine.id}").status_code == 404
    assert bob.delete(f"/api/chat/{mine.id}").status_code == 404
    assert bob.post(
        "/api/chat",
        json={
            "conversation_id": mine.id,
            "message": "carry on",
        },
    ).status_code in (404, 503), "nor continue it"

    assert conversations.load(mine.id) is not None, "and none of that removed it"
    assert as_person(ALICE).get(f"/api/chat/{mine.id}").status_code == 200


def test_forgetting_your_own_conversation_still_works(team):
    mine = assistant.start(a_person(ALICE), "Answer the Barq questionnaire")

    assert as_person(ALICE).delete(f"/api/chat/{mine.id}").status_code == 200
    assert conversations.load(mine.id) is None


def test_the_history_says_when_it_was_and_which_file_it_was_about(team, tmp_path):
    """The list gave a title the assistant wrote from the first sentence
    somebody typed, which for half of them is "answer these"."""
    alice = as_person(ALICE)
    batch = _open(alice, tmp_path, "Barq 3rd Party Review.xlsx")
    conversation = assistant.start(a_person(ALICE), "Answer these")
    conversation.batch_id = batch["id"]
    conversations.save(conversation)

    [listed] = alice.get("/api/chat").json()["conversations"]

    assert listed["source_name"] == "Barq 3rd Party Review.xlsx"
    assert listed["updated_at"] and listed["created_at"]


# --- questionnaires --------------------------------------------------------------------


def test_a_questionnaire_and_its_answers_belong_to_whoever_uploaded_it(team, tmp_path):
    alice, bob = as_person(ALICE), as_person(BOB)
    batch = _open(alice, tmp_path)

    assert bob.get("/api/forms").json()["forms"] == []
    assert bob.get(f"/api/forms/{batch['id']}").status_code == 404
    assert alice.get(f"/api/forms/{batch['id']}").status_code == 200


def test_a_colleague_cannot_read_or_open_the_file_itself(team):
    from src import service

    name = "Barq Privacy Questionnaire.pdf"
    service.save_upload(name, b"%PDF-1.4 hers", settings.default_team, owner=ALICE)
    alice, bob = as_person(ALICE), as_person(BOB)

    assert [d["name"] for d in alice.get("/api/documents").json()["documents"]] == [name]
    assert alice.get(f"/api/documents/uploaded/uploaded/{name}/file").status_code == 200
    assert bob.get("/api/documents").json()["documents"] == []
    assert bob.get(f"/api/documents/uploaded/uploaded/{name}/file").status_code == 404


def test_a_questionnaire_from_before_the_split_is_still_only_its_owners(team, tmp_path):
    """Uploads used to go to one folder for the whole team, and the files are
    still there. The batch that reads one says whose it is."""
    alice, bob = as_person(ALICE), as_person(BOB)
    name = "Old Vendor Review.pdf"
    legacy = settings.upload_dir / name
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(b"%PDF-1.4 from before")
    assert bob.get("/api/documents").json()["documents"], "unclaimed, it is the team's"

    from src import batches
    from src.forms.model import DetectedForm

    batches.create(a_person(ALICE), legacy, DetectedForm(source_name=name, format="docx"))

    assert [d["name"] for d in alice.get("/api/documents").json()["documents"]] == [name]
    assert bob.get("/api/documents").json()["documents"] == []
    assert bob.get(f"/api/documents/uploaded/uploaded/{name}/file").status_code == 404
    assert alice.get(f"/api/documents/uploaded/uploaded/{name}/file").status_code == 200


def test_an_upload_lands_in_the_uploaders_own_folder(team, tmp_path):
    _open(as_person(ALICE), tmp_path, "Barq 3rd Party Review.xlsx")

    hers = settings.user_upload_dir(settings.default_team, ALICE)
    assert [path.name for path in hers.iterdir()] == ["Barq 3rd Party Review.xlsx"]
    assert not list(settings.upload_dir.glob("Barq*")), "not in the team's folder"


# --- answered runs ---------------------------------------------------------------------


def _a_run(email: str, run_id: str) -> None:
    runs.save(
        a_person(email),
        AssessmentResult(
            run_id=run_id,
            source_name="Vendor Review.xlsx",
            language="en",
            questions_found=1,
            answers=[
                AnsweredQuestion(
                    question=Question(id="1", text="Do you encrypt backups?"),
                    answer="Yes.",
                    confidence=0.9,
                    needs_review=False,
                )
            ],
        ),
    )


def test_a_run_is_listed_and_opened_only_by_the_person_who_ran_it(team):
    _a_run(ALICE, "hers")
    _a_run(BOB, "his")
    alice, bob = as_person(ALICE), as_person(BOB)

    assert [r["run_id"] for r in alice.get("/api/runs").json()["runs"]] == ["hers"]
    assert [r["run_id"] for r in bob.get("/api/runs").json()["runs"]] == ["his"]
    assert alice.get("/api/runs/his").status_code == 404
    assert alice.get("/api/runs/hers").status_code == 200


# --- and what the team still shares -----------------------------------------------------


def test_the_knowledge_base_and_the_answer_memory_are_still_the_teams(team, memory_index):
    """The point of the split is the files and the conversations. What this
    organisation says, and the policies it says it from, are the team's."""
    alice, bob = as_person(ALICE), as_person(BOB)
    added = alice.post(
        "/api/memory",
        json={
            "question": "Do you encrypt backups?",
            "answer": "Yes, with AES-256.",
        },
    ).json()

    listed = bob.get("/api/memory").json()["entries"]

    assert [entry["entry_id"] for entry in listed] == [added["entry_id"]]
    assert bob.get("/api/knowledge").status_code == 200
    assert bob.get("/api/search", params={"q": "backups", "mode": "keyword"}).status_code == 200
