"""A typed list, or a PDF's or a Word text's questions, is a questionnaire with no file (plan 033).

They were answered on the page and kept nowhere a page could read: a reload
lost them, and their answers went to `runs`, which no page lists. Now each is a
questionnaire (`form_batches`, format "list"), made by `POST /api/forms/list`,
listed and opened like a file's, answered with progress and the running guard,
and every card action works on it. Fill is refused with `nothing_to_fill`: its
answers are downloaded instead.

The pipeline is never called: answering, rewording and shortening are stubbed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src import batches, busy, identity, products, tools
from src.api import app
from src.config import settings
from src.models import AnsweredQuestion, AssessmentResult, Question, QuestionType

TEAM = settings.default_team
ANSWER = "Yes, every backup is encrypted with AES-256."
CODE = "TEAM-CODE-FOR-TESTS"
ALICE = "alice@example.com"
BOB = "bob@example.com"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def drafted(monkeypatch: pytest.MonkeyPatch) -> list[Question]:
    """Every question answered, confidently; the questions the pipeline was given are kept."""
    seen: list[Question] = []

    async def fake(questions: list[Question], language: Any = None, run_id: Any = None, **extra: Any):
        seen.extend(questions)
        answers = [
            AnsweredQuestion(
                question=q, answer=ANSWER, confidence=0.9, needs_review=False, citations=["Backup Standard §2"]
            )
            for q in questions
        ]
        for answer in answers:
            if extra.get("on_answer"):
                extra["on_answer"](answer)
        return answers

    monkeypatch.setattr("src.tools.service.answer_questions", fake)
    return seen


def make_list(client: TestClient, *questions: str, **fields: str) -> dict[str, Any]:
    response = client.post("/api/forms/list", data={"questions": list(questions), **fields})
    assert response.status_code == 200, response.text
    return response.json()


def as_person(email: str) -> TestClient:
    client = TestClient(app)
    assert client.post("/api/auth/session", json={"email": email, "code": CODE}).status_code == 200
    return client


@pytest.fixture
def team() -> None:
    identity.ensure_team(TEAM, name="Cybersecurity")
    identity.set_access_code(TEAM, CODE)
    identity.add_user(ALICE)
    identity.add_user(BOB)


# --- making one -------------------------------------------------------------------------


def test_typed_questions_are_kept_as_a_questionnaire_with_no_file(client: TestClient) -> None:
    made = make_list(client, "Do you encrypt backups?", "   ", "هل لديكم سياسة لأمن المعلومات؟")

    assert made["format"] == "list"
    assert made["source_name"] == "Typed questions", "the name when none is given"
    assert [(q["id"], q["number"], q["text"], q["language"]) for q in made["questions"]] == [
        ("1", "1", "Do you encrypt backups?", "en"),
        ("2", "2", "هل لديكم سياسة لأمن المعلومات؟", "ar"),
    ], "blank lines are left out, and each question is in its own language"
    assert made["file_present"] is False and made["questions"][0]["targets"] == []
    assert made["counts"]["questions"] == 2 and made["counts"]["still_blank"] == 2
    assert batches.load(made["id"]).source_path.name == "", "nothing was kept on disk"


def test_a_list_has_the_name_given(client: TestClient) -> None:
    made = make_list(client, "Do you encrypt backups?", name="  Northwind   follow-up ")
    assert made["source_name"] == "Northwind follow-up"


def test_nothing_to_keep_is_refused(client: TestClient) -> None:
    response = client.post("/api/forms/list", data={"questions": ["", "  "]})

    assert (response.status_code, response.json()["code"]) == (400, "no_questions_given")
    assert batches.recent(TEAM) == []


def test_a_question_too_long_is_refused(client: TestClient) -> None:
    response = client.post("/api/forms/list", data={"questions": ["x" * 4001]})
    assert (response.status_code, response.json()["code"]) == (400, "question_too_long")


def test_its_product_is_checked_before_anything_is_kept_and_fixed_after(client: TestClient) -> None:
    availo = products.add(None, TEAM, "Availo")
    msegat = products.add(None, TEAM, "Msegat")
    theirs = products.add(None, "privacy", "Theirs")

    refused = client.post("/api/forms/list", data={"questions": ["Q?"], "product": theirs.id})
    assert (refused.status_code, refused.json()["code"]) == (404, "product_not_found")
    assert batches.recent(TEAM) == []

    made = make_list(client, "Q?", product=availo.id)
    assert made["product_id"] == availo.id
    moved = client.post(f"/api/forms/{made['id']}/product", json={"product": msegat.id})
    assert (moved.status_code, moved.json()["code"]) == (409, "product_locked")


def test_a_deleted_products_list_is_kept_read_only(client: TestClient, drafted: list[Question]) -> None:
    availo = products.add(None, TEAM, "Availo")
    made = make_list(client, "Q?", product=availo.id)
    products.delete(identity.local_user(), TEAM, availo.id, confirm="confirm")

    opened = client.get(f"/api/forms/{made['id']}").json()
    assert opened["read_only"] is True
    refused = client.post(f"/api/forms/{made['id']}/answer", json={})
    assert (refused.status_code, refused.json()["code"]) == (409, "product_deleted")


# --- listed and opened like a file's -------------------------------------------------------


def test_it_is_listed_and_opened_like_a_file(client: TestClient) -> None:
    made = make_list(client, "Do you encrypt backups?", name="Follow-up")

    [listed] = client.get("/api/forms").json()["forms"]
    assert (listed["id"], listed["format"], listed["source_name"]) == (made["id"], "list", "Follow-up")
    opened = client.get(f"/api/forms/{made['id']}")
    assert opened.status_code == 200 and opened.json()["questions"][0]["text"] == "Do you encrypt backups?"


def test_somebody_elses_list_is_absent(team: None) -> None:
    alice, bob = as_person(ALICE), as_person(BOB)
    made = make_list(alice, "Do you encrypt backups?")

    assert bob.get(f"/api/forms/{made['id']}").status_code == 404
    assert bob.get("/api/forms").json()["forms"] == []
    assert bob.post(f"/api/forms/{made['id']}/answer", json={}).status_code == 404


# --- answered, with every card action ------------------------------------------------------


def test_it_is_answered_by_the_answer_route(client: TestClient, drafted: list[Question]) -> None:
    """A list's questions have no place in a file, and `Scope.select` passed over every one."""
    made = make_list(client, "Do you encrypt backups?", "Do you enforce MFA?")

    outcome = client.post(f"/api/forms/{made['id']}/answer", json={}).json()

    assert (outcome["attempted"], outcome["answered"]) == (2, 2)
    assert [q.text for q in drafted] == ["Do you encrypt backups?", "Do you enforce MFA?"]
    batch = outcome["batch"]
    assert [q["answer"] for q in batch["questions"]] == [ANSWER, ANSWER]
    assert batch["counts"]["answered"] == 2 and batch["counts"]["still_blank"] == 0
    assert all(q["will_be_written"] for q in batch["questions"]), "the review gate's verdict, as for a file"


def test_a_second_run_is_refused_while_one_is_answering(
    client: TestClient, drafted: list[Question], monkeypatch: pytest.MonkeyPatch
) -> None:
    made = make_list(client, "Do you encrypt backups?")
    with monkeypatch.context() as running:  # a run going on in another request
        running.setitem(busy._HELD, made["id"], busy._Hold(run_id="elsewhere", started_at="2026-11-07T09:00:00+00:00"))
        refused = client.post(f"/api/forms/{made['id']}/answer", json={})
        shown = client.get(f"/api/forms/{made['id']}").json()

    assert (refused.status_code, refused.json()["code"]) == (409, "questionnaire_busy")
    assert shown["running"]["run_id"] == "elsewhere" and drafted == []


def test_its_progress_is_reported_under_its_id(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    made = make_list(client, "Do you encrypt backups?")
    seen: list[dict[str, Any] | None] = []

    async def watching(questions: list[Question], language: Any = None, run_id: Any = None, **extra: Any):
        from src import progress

        progress.start(run_id, stage="answering")
        progress.set_total(run_id, len(questions))
        seen.append(client.get(f"/api/assessments/progress/{made['id']}").json())
        progress.finish(run_id)
        return [AnsweredQuestion(question=q, answer=ANSWER, confidence=0.9, needs_review=False) for q in questions]

    monkeypatch.setattr("src.tools.service.answer_questions", watching)
    client.post(f"/api/forms/{made['id']}/answer", json={})

    assert seen and seen[0]["total"] == 1


def test_every_card_action_works_on_it(client: TestClient, drafted: list[Question], monkeypatch) -> None:
    async def reword(answered: AnsweredQuestion, instruction: str, language: Any = None, **_: Any):
        return answered.model_copy(update={"answer": "Reworded: " + answered.answer})

    async def shorten(answered: AnsweredQuestion) -> str:
        return "Yes."

    monkeypatch.setattr("src.tools.rewrite.rewrite", reword)
    monkeypatch.setattr("src.tools.rewrite.shorten", shorten)
    made = make_list(client, "Q one?", "Q two?", "Q three?", "Q four?")
    base = f"/api/forms/{made['id']}"
    client.post(f"{base}/answer", json={})

    edited = client.post(f"{base}/answers", json={"question_id": "1", "text": "We encrypt every backup."}).json()
    assert edited["questions"][0]["by_hand"] is True
    approved = client.post(f"{base}/approve", json={"question_id": "1"}).json()
    assert approved["questions"][0]["approved"] is True
    blanked = client.post(f"{base}/blank", json={"question_id": "2"}).json()
    assert blanked["questions"][1]["blanked"] is True
    aside = client.patch(f"{base}/questions", json={"changes": [{"id": "3", "skip": True}]}).json()
    assert aside["questions"][2]["skip"] is True
    revised = client.post(f"{base}/revise", json={"instruction": "Shorter", "scope": {"ids": ["4"]}}).json()
    assert revised["answered"] == 1 and revised["batch"]["questions"][3]["answer"].startswith("Reworded: ")
    restored = client.post(f"{base}/answers/draft", json={"question_id": "4"}).json()
    assert restored["questions"][3]["answer"] == ANSWER
    brief = client.post(f"{base}/detail", json={"detail": "brief"}).json()
    assert brief["detail"] == "brief" and brief["questions"][3]["brief"] == "Yes."
    one = client.post(f"{base}/answers/length", json={"question_id": "4", "prefer": "full"}).json()
    assert one["questions"][3]["length"] == "full"
    skill = client.post("/api/skills", json={"name": "Formal", "instruction": "Make it formal."}).json()
    styled = client.post(f"{base}/skills/{skill['skill_id']}", json={"scope": {"ids": ["4"]}}).json()
    assert styled["answered"] == 1


def test_the_pipeline_is_given_a_pdf_questions_type_and_options(
    client: TestClient, drafted: list[Question], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The drafter is told the type and the options; `/answer-questions` passed them, and so does a list."""

    async def extract(path: Path):
        return "en", [
            Question(
                id="q1",
                text="Are backups encrypted?",
                section="4 Backup",
                question_type=QuestionType.YES_NO,
                options=["Yes", "No"],
            )
        ]

    monkeypatch.setattr("src.lists.service.extract_assessment_questions", extract)
    pdf = tmp_path / "vendor questions.pdf"
    pdf.write_bytes(b"%PDF-1.4 stand-in")

    with open(pdf, "rb") as handle:
        made = client.post(
            "/api/forms/list", files={"file": (pdf.name, handle.read(), "application/pdf")}, data={"product": ""}
        ).json()
    client.post(f"/api/forms/{made['id']}/answer", json={})

    assert made["format"] == "list" and made["source_name"] == "vendor questions.pdf"
    assert made["file_present"] is True, "the PDF is kept with the list, and deleted with it"
    assert made["questions"][0]["section"] == "4 Backup"
    [given] = drafted
    assert (given.question_type, given.options, given.section) == (QuestionType.YES_NO, ["Yes", "No"], "4 Backup")
    answered = client.get(f"/api/forms/{made['id']}").json()["questions"][0]["answered"]
    assert answered["question"]["question_type"] == "yes_no", "what the card shows beside the question"


def test_typed_questions_beside_a_file_come_after_its_own(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def extract(path: Path):
        return "en", [Question(id="q1", text="From the file?")]

    monkeypatch.setattr("src.lists.service.extract_assessment_questions", extract)
    word = tmp_path / "questions.docx"
    word.write_bytes(b"stand-in")
    with open(word, "rb") as handle:
        made = client.post(
            "/api/forms/list", files={"file": (word.name, handle.read())}, data={"questions": ["Typed too?"]}
        ).json()

    assert [q["text"] for q in made["questions"]] == ["From the file?", "Typed too?"]


def test_a_file_with_no_questions_keeps_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def extract(path: Path):
        return "en", []

    monkeypatch.setattr("src.lists.service.extract_assessment_questions", extract)
    pdf = tmp_path / "prose.pdf"
    pdf.write_bytes(b"%PDF-1.4 no questions")
    with open(pdf, "rb") as handle:
        response = client.post("/api/forms/list", files={"file": (pdf.name, handle.read())})

    assert (response.status_code, response.json()["code"]) == (422, "no_questions_found")
    assert batches.recent(TEAM) == []
    folder = settings.user_upload_dir(TEAM, identity.LOCAL_EMAIL)
    assert not any(folder.iterdir()) if folder.exists() else True, "the upload went too"


def test_a_file_the_list_cannot_read_is_refused(client: TestClient) -> None:
    response = client.post("/api/forms/list", files={"file": ("vendor.xlsx", b"PK")})
    assert (response.status_code, response.json()["code"]) == (415, "document_type_unsupported")


# --- downloaded, not filled ---------------------------------------------------------------


def test_fill_says_there_is_no_file_and_offers_the_downloads(client: TestClient, drafted: list[Question]) -> None:
    made = make_list(client, "Do you encrypt backups?")
    client.post(f"/api/forms/{made['id']}/answer", json={})

    for response in (
        client.post(f"/api/forms/{made['id']}/fill", json={}),
        client.get(f"/api/forms/{made['id']}/file"),
    ):
        assert (response.status_code, response.json()["code"]) == (422, "nothing_to_fill")
        assert "no file to write the answers into" in response.json()["detail"]
        assert "PDF, Word, CSV or JSON" in response.json()["detail"]


def test_the_assistant_is_told_the_same(drafted: list[Question]) -> None:
    from src import lists
    from src.errors import ToolError

    user = identity.local_user()
    batch = lists.open_list(user, [Question(id="1", text="Q?")], name="Follow-up")
    asyncio.run(tools.answer(user, batch.id))

    with pytest.raises(ToolError) as refused:
        tools.fill(user, batch.id)
    assert refused.value.code == "nothing_to_fill"


@pytest.mark.parametrize("route", ["/api/assessments/export/pdf", "/api/assessments/export/docx"])
def test_its_answers_export_as_a_files_do(client: TestClient, drafted: list[Question], route: str) -> None:
    """The page builds the export from the questionnaire's answers, for a list exactly as for a file."""
    made = make_list(client, "Do you encrypt backups?", name="Follow-up")
    batch = client.post(f"/api/forms/{made['id']}/answer", json={}).json()["batch"]
    result = AssessmentResult(
        run_id=batch["id"],
        source_name=batch["source_name"],
        language="en",
        questions_found=batch["counts"]["questions"],
        answers=[AnsweredQuestion.model_validate(q["answered"]) for q in batch["questions"]],
    )

    response = client.post(route, json=result.model_dump(mode="json"))

    assert response.status_code == 200 and response.content
    assert "Follow-up.answers" in response.headers["content-disposition"]


def test_the_old_list_route_still_answers(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Kept for the page until it moves to lists, and for scripts: answered and handed back, nothing listed."""

    async def fake(question: Question, language: Any, **_: Any) -> AnsweredQuestion:
        return AnsweredQuestion(question=question, answer=ANSWER, confidence=0.9)

    monkeypatch.setattr("src.service.answer_one_question", fake)
    body = client.post("/api/assessments/answer-questions", json={"questions": [{"text": "Q?"}]}).json()

    assert body["answers"][0]["answer"] == ANSWER
    assert client.get("/api/forms").json()["forms"] == []
