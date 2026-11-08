"""Approve all (plan 041): the held-back answers a person confirmed, and nothing else.

The user's two conditions were a confirmation, which the pages ask for, and
that nothing goes into the answer memory, which is decided here.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import answer_memory, batches, events, identity, questionnaire, tools
from src.api import app
from src.models import AnsweredQuestion, Question
from tests import forms_fixtures as shapes


@pytest.fixture
def user():
    return identity.local_user()


@pytest.fixture
def batch(user, tmp_path):
    """Four questions: held, confident, failed, held."""
    opened = tools.open_form(user, shapes.simple(tmp_path / "vendor.xlsx"))
    held = {"confidence": 0.4, "needs_review": True, "review_reasons": ["the sources disagree"]}
    questions = [Question(id=q.id, text=q.text) for q in opened.form.questions]
    batches.save_answers(
        opened.id,
        [
            AnsweredQuestion(question=questions[0], answer="Partly.", **held),
            AnsweredQuestion(question=questions[1], answer="Yes.", confidence=0.9, needs_review=False),
            AnsweredQuestion(question=questions[2], answer="", error="the model was unavailable"),
            AnsweredQuestion(question=questions[3], answer="Probably.", **held),
        ],
    )
    return opened


def ids(batch) -> list[str]:
    return [question.id for question in batch.form.questions]


def written(user, batch) -> list[bool]:
    return [question["will_be_written"] for question in tools.inspect(user, batch.id)["questions"]]


def test_it_releases_what_is_held_and_nothing_else(user, batch):
    assert written(user, batch) == [False, True, False, False]

    approved = questionnaire.approve_held(user, batch.id, ids(batch))

    first, confident, failed, last = ids(batch)
    assert approved == [first, last]
    assert written(user, batch) == [True, True, False, True]
    stored = batches.answers(batch.id)
    assert stored[first].confidence_reason == tools.APPROVED
    assert stored[first].answer == "Partly.", "approving does not change a word"
    assert stored[confident].confidence_reason != tools.APPROVED, "it was going in anyway: no name nobody earned"
    assert batches.edited_by(batch.id)[first] == user.email
    assert confident not in batches.edited_by(batch.id)
    assert failed not in approved


def test_only_the_answers_the_confirmation_counted(user, batch):
    first, _, _, last = ids(batch)

    assert questionnaire.approve_held(user, batch.id, [first]) == [first]

    assert batches.answers(batch.id)[last].confidence_reason != tools.APPROVED


def test_an_answer_approved_since_is_left_as_it_is(user, batch):
    first, _, _, last = ids(batch)
    tools.approve_answer(user, batch.id, first)

    assert questionnaire.approve_held(user, batch.id, [first, last]) == [last]


def test_a_blank_or_set_aside_answer_is_not_approved(user, batch):
    first, _, _, last = ids(batch)
    tools.blank_answer(user, batch.id, first)
    tools.set_questions(user, batch.id, [{"id": last, "skip": True}])

    assert questionnaire.approve_held(user, batch.id, [first, last]) == []


def test_nothing_reaches_the_answer_memory(user, batch, monkeypatch):
    def refused(*args, **kwargs):
        raise AssertionError("Approve all wrote to the answer memory")

    monkeypatch.setattr(answer_memory, "record", refused)

    assert questionnaire.approve_held(user, batch.id, ids(batch))


def test_words_a_person_wrote_do_not_reach_the_memory_either(user, batch, monkeypatch):
    """Single-click approval teaches the memory a person's words. Approve all never does."""
    question = batch.form.questions[0]
    tools.set_answer(user, batch.id, question.id, "Our own words.")
    before = answer_memory.get(tools._memory_id(batch.id, question.id), user.team_id)

    approved = questionnaire.approve_held(user, batch.id, ids(batch))

    assert question.id not in approved, "written by a person: it was not held"
    assert answer_memory.get(tools._memory_id(batch.id, question.id), user.team_id) == before is None


def test_each_approval_is_on_the_record_and_marked_as_bulk(user, batch):
    first, _, _, last = ids(batch)

    questionnaire.approve_held(user, batch.id, ids(batch))

    recorded = [e.payload for e in events.of_kind(user.team_id, events.ANSWER_EDITED) if e.payload.get("bulk")]
    assert sorted(p["question_id"] for p in recorded) == sorted([first, last])
    assert all(p["approved"] is True for p in recorded)


def test_one_can_be_withdrawn_afterwards(user, batch):
    first, *_ = ids(batch)
    questionnaire.approve_held(user, batch.id, ids(batch))

    tools.approve_answer(user, batch.id, first, approved=False)

    assert written(user, batch)[0] is False


def test_the_route_says_which_were_approved(user, batch):
    client = TestClient(app)
    first, _, _, last = ids(batch)

    response = client.post(f"/api/forms/{batch.id}/approve-all", json={"question_ids": ids(batch)})

    assert response.status_code == 200
    assert response.json()["approved"] == [first, last]
    assert [q["will_be_written"] for q in response.json()["questions"]] == [True, True, False, True]


def test_the_route_needs_something_to_approve(batch):
    assert TestClient(app).post(f"/api/forms/{batch.id}/approve-all", json={"question_ids": []}).status_code == 422
