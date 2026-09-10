"""Two people, one team, one questionnaire — and everything they share.

The other API tests each check one route. This checks the thing the team
actually does: one person opens a file and answers it, another reads the same
answers, corrects one, approves it, and the approval reaches the answer memory
where the first person can see it. Then somebody else's team tries the same and
gets nothing.

It is written as a sequence rather than as isolated cases because that is where
the bugs in a shared system live: not in whether a route works, but in whether
what one person did is visible, attributable and safe to the next.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import answer_memory, events, identity
from src.api import app
from src.config import settings
from src.models import AnsweredQuestion
from tests import forms_fixtures as shapes

ALICE = "m.alsaif@t2.sa"
BOB = "mohammed.sa.alsaif@gmail.com"
CAROL = "carol@example.com"
CODE = "TEAM-CODE-FOR-TESTS"
OTHER_CODE = "OTHER-TEAM-CODE"


@pytest.fixture
def team():
    """One team with two members, and a second team with one."""
    identity.ensure_team(settings.default_team, name="Cybersecurity")
    identity.set_access_code(settings.default_team, CODE)
    identity.add_user(ALICE)
    identity.add_user(BOB)

    identity.ensure_team("privacy", name="Privacy")
    identity.set_access_code("privacy", OTHER_CODE)
    identity.add_user(CAROL, team_id="privacy")


def as_person(email: str, code: str = CODE) -> TestClient:
    """A signed-in client of their own, so two people hold two sessions."""
    client = TestClient(app)
    assert client.post("/api/auth/session", json={"email": email, "code": code}).status_code == 200
    return client


@pytest.fixture
def answers_yes(monkeypatch):
    async def fake(questions, language=None, run_id=None, **extra):
        return [
            AnsweredQuestion(
                question=question,
                answer="Yes. Access rights are reviewed every quarter.",
                confidence=0.9, needs_review=False,
            )
            for question in questions
        ]

    monkeypatch.setattr("src.tools.service.answer_questions", fake)


def _open(client, tmp_path, name="vendor.xlsx"):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(shapes.simple(path), "rb") as handle:
        return client.post("/api/forms", files={"file": (
            name, handle.read(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )}).json()


# --- the shared questionnaire ----------------------------------------------


def test_a_teammate_picks_up_the_file_the_other_one_opened(team, tmp_path, answers_yes):
    alice, bob = as_person(ALICE), as_person(BOB)
    batch_id = _open(alice, tmp_path)["id"]

    assert batch_id in [f["id"] for f in bob.get("/api/forms").json()["forms"]]
    assert bob.get(f"/api/forms/{batch_id}").status_code == 200


def test_another_team_cannot_see_it_at_all(team, tmp_path, answers_yes):
    batch_id = _open(as_person(ALICE), tmp_path)["id"]
    carol = as_person(CAROL, OTHER_CODE)

    assert carol.get("/api/forms").json()["forms"] == []
    assert carol.get(f"/api/forms/{batch_id}").status_code == 400
    assert carol.post(f"/api/forms/{batch_id}/fill").status_code == 400


def test_one_answers_and_the_other_corrects_and_approves(
    team, tmp_path, answers_yes, memory_index
):
    alice, bob = as_person(ALICE), as_person(BOB)
    batch_id = _open(alice, tmp_path)["id"]
    alice.post(f"/api/forms/{batch_id}/answer", json={"scope": {}})

    question_id = bob.get(f"/api/forms/{batch_id}").json()["questions"][0]["id"]
    bob.post(f"/api/forms/{batch_id}/answers", json={
        "question_id": question_id,
        "text": "Yes. Access rights are reviewed quarterly by the system owner.",
    })
    approved = bob.post(f"/api/forms/{batch_id}/approve", json={"question_id": question_id}).json()

    # Alice sees Bob's correction, and the file is ready to be written.
    hers = alice.get(f"/api/forms/{batch_id}").json()["questions"][0]
    assert "system owner" in hers["answer"]
    assert hers["will_be_written"] is True

    # And it is Bob's name on it, in the memory and in the event log.
    entry = answer_memory.get(approved["remembered"])
    assert entry.approved_by == BOB
    assert [e.actor_email for e in events.recent(settings.default_team, kind=events.MEMORY_ADDED)] == [BOB]


def test_the_answer_memory_is_the_teams_not_one_persons(team, tmp_path, answers_yes, memory_index):
    alice, bob = as_person(ALICE), as_person(BOB)
    added = alice.post("/api/memory", json={
        "question": "Do you encrypt backups?", "answer": "Yes, with AES-256.",
    }).json()

    listed = bob.get("/api/memory").json()["entries"]

    assert [e["entry_id"] for e in listed] == [added["entry_id"]]
    assert listed[0]["approved_by"] == ALICE, "shared, and still attributable"

    # And either of them may correct or retire it: this is a team's record of
    # what the team says, not a pile of personal notes.
    assert bob.patch(f"/api/memory/{added['entry_id']}", json={
        "answer": "Yes, with AES-256 at rest and in transit.",
    }).status_code == 200
    assert "in transit" in alice.get("/api/memory").json()["entries"][0]["answer"]


def test_a_disagreement_is_raised_once_and_settled_by_whoever_gets_there_first(
    team, memory_index
):
    alice, bob = as_person(ALICE), as_person(BOB)
    first = answer_memory.record("Do you run drills?", "Yes, annually.")
    second = answer_memory.record("Do you run drills?", "No, not yet.")
    answer_memory.raise_conflict(first.entry_id, second.entry_id, "the two answers disagree")

    assert len(alice.get("/api/memory/conflicts").json()["conflicts"]) == 1
    assert len(bob.get("/api/memory/conflicts").json()["conflicts"]) == 1

    bob.post("/api/memory/conflicts/resolve", json={
        "entry_id": first.entry_id, "other_id": second.entry_id, "resolution": "keep_this",
    })

    assert alice.get("/api/memory/conflicts").json()["conflicts"] == [], "settled for both"
    assert answer_memory.conflicts(open_only=False)[0].resolved_by == BOB


def test_the_knowledge_base_is_shared_and_the_memory_page_is_not_open_to_strangers(team):
    """The corpus has no owner — it is what the organisation is bound by. The
    routes that manage it still need a session, which is what stops a passer-by
    reading the policies through the API."""
    stranger = TestClient(app)
    assert stranger.get("/api/memory").status_code == 401
    assert stranger.post("/api/memory", json={"question": "q", "answer": "a"}).status_code == 401
    assert stranger.get("/api/memory/conflicts").status_code == 401

    assert as_person(ALICE).get("/api/memory").status_code == 200
    assert as_person(BOB).get("/api/memory").status_code == 200


def test_shared_does_not_mean_public(team):
    """Everything that reads the corpus out, writes into it, or empties it.

    These were reachable without a session while the questionnaire routes beside
    them were not — including `DELETE /api/knowledge`, which is the whole
    knowledge base. Shared with the team is not shared with whoever can reach
    the port.
    """
    stranger = TestClient(app)

    assert stranger.get("/api/knowledge").status_code == 401
    assert stranger.delete("/api/knowledge").status_code == 401
    assert stranger.delete("/api/knowledge/sources/anything.pdf").status_code == 401
    assert stranger.get("/api/search", params={"q": "password"}).status_code == 401
    assert stranger.get("/api/documents").status_code == 401
    assert stranger.get("/api/documents/uploaded/uploaded/x.pdf/text").status_code == 401
    assert stranger.post("/api/assessments/export/pdf", json={}).status_code == 401

    assert as_person(ALICE).get("/api/knowledge").status_code == 200


def test_who_changed_the_corpus_is_recorded(team, tmp_path, monkeypatch):
    """Managing the knowledge base is a team activity, so it is attributable."""
    from src.models import IngestResult

    async def indexed(path, source_type, authority="ours"):
        return IngestResult(
            source_name=path.name, source_type=source_type, chunks_indexed=12,
        )

    monkeypatch.setattr("src.api.service.ingest", indexed)
    alice = as_person(ALICE)
    policy = tmp_path / "T2 - Access Control Policy.pdf"
    policy.write_bytes(b"%PDF-1.4 anything")

    with open(policy, "rb") as handle:
        alice.post("/api/knowledge/guidelines", files={"files": (policy.name, handle.read(), "application/pdf")})
    as_person(BOB).delete(f"/api/knowledge/sources/{policy.name}")

    log = {event.kind: event for event in events.recent(settings.default_team, limit=20)}
    assert log[events.DOCUMENT_INDEXED].actor_email == ALICE
    assert log[events.DOCUMENT_INDEXED].payload["chunks"] == 12
    assert log[events.SOURCE_REMOVED].actor_email == BOB
    assert log[events.SOURCE_REMOVED].subject_id == policy.name


# --- one name, two people ---------------------------------------------------


def test_two_different_files_with_one_name_do_not_overwrite_each_other(team, tmp_path):
    """Everybody's vendor questionnaire is called the vendor questionnaire.

    The second upload used to land on the first one's bytes, which silently
    repointed a batch that had already been read — column by column — at
    somebody else's spreadsheet.
    """
    alice, bob = as_person(ALICE), as_person(BOB)
    mine = _open(alice, tmp_path / "a", "Vendor Questionnaire.xlsx")
    theirs = shapes.legend_sheet(tmp_path / "b" / "Vendor Questionnaire.xlsx")
    with open(theirs, "rb") as handle:
        bob.post("/api/forms", files={"file": (
            "Vendor Questionnaire.xlsx", handle.read(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )})

    still = alice.get(f"/api/forms/{mine['id']}").json()
    assert [q["text"] for q in still["questions"]] == [q["text"] for q in mine["questions"]]


def test_the_same_file_twice_is_the_same_file(team, tmp_path):
    """Re-uploading is how a person reopens their own work. A folder of
    `(2)`, `(3)`, `(4)` copies of one document helps nobody."""
    alice = as_person(ALICE)
    first = _open(alice, tmp_path, "Vendor Questionnaire.xlsx")
    second = _open(alice, tmp_path, "Vendor Questionnaire.xlsx")

    assert first["id"] != second["id"], "two batches"
    assert len(list((settings.upload_dir).glob("Vendor*"))) == 1, "one file"


def test_two_batches_over_one_questionnaire_fill_their_own_copies(
    team, tmp_path, answers_yes
):
    """Both get their own answers back, not whichever was written last."""
    alice, bob = as_person(ALICE), as_person(BOB)
    hers = _open(alice, tmp_path, "Shared.xlsx")["id"]
    his = _open(bob, tmp_path, "Shared.xlsx")["id"]

    alice.post(f"/api/forms/{hers}/answer", json={"scope": {}})
    written = alice.post(f"/api/forms/{hers}/fill").json()
    empty = bob.post(f"/api/forms/{his}/fill").json()

    assert written["written"] > 0
    assert empty["written"] == 0, "Bob answered nothing, so his copy holds nothing"
    assert alice.get(f"/api/forms/{hers}/file").status_code == 200

    # And the two copies are two files, so his empty fill did not replace hers.
    from src import batches as batch_store
    from src import tools as ops

    mine = ops._filled_path(batch_store.load(hers))
    theirs = ops._filled_path(batch_store.load(his))
    assert mine != theirs
    assert mine.exists() and theirs.exists()
    assert mine.read_bytes() != theirs.read_bytes()

    alice, bob = as_person(ALICE), as_person(BOB)
    batch_id = _open(alice, tmp_path)["id"]
    alice.post(f"/api/forms/{batch_id}/answer", json={"scope": {}})
    question_id = bob.get(f"/api/forms/{batch_id}").json()["questions"][0]["id"]
    bob.post(f"/api/forms/{batch_id}/answers", json={
        "question_id": question_id, "text": "Yes, every quarter, owned by the CISO.",
    })
    bob.post(f"/api/forms/{batch_id}/approve", json={"question_id": question_id})

    log = events.recent(settings.default_team, limit=50)
    kinds = {event.kind: event.actor_email for event in log}

    assert kinds[events.FORM_OPENED] == ALICE
    assert kinds[events.BATCH_ANSWERED] == ALICE
    assert kinds[events.ANSWER_EDITED] == BOB
    assert kinds[events.MEMORY_ADDED] == BOB
