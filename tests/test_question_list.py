"""Answering a question list, rather than a document.

Two flows converge here. A file can be extracted without being answered, so the
questions can be corrected first; and a list can be answered with no file
involved at all, including a second batch added after the first was answered.
Both end up in the same place: a list of `Question`, answered by the same
per-question graph the document flow fans out to.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import service
from src.api import _detect_language, app
from src.models import AnsweredQuestion, Question


@pytest.fixture
def answered(monkeypatch):
    """Answer every question with an echo, so the wiring is what is tested."""
    seen: list[Question] = []

    async def fake(question: Question, language):
        seen.append(question)
        return AnsweredQuestion(
            question=question,
            answer=f"answer to {question.text}",
            confidence=0.9,
            needs_review=False,
        )

    monkeypatch.setattr(service, "answer_one_question", fake)
    return seen


# --- language of a typed question ------------------------------------------


@pytest.mark.parametrize(("text", "expected"), [
    ("Do you encrypt data at rest?", "en"),
    ("ما هي مدة الاحتفاظ بالبيانات؟", "ar"),
    ("هل تستخدمون AES-256؟", "ar"),
    ("Do you enforce multi-factor authentication on privileged accounts "
     "(المصادقة متعددة العوامل)?", "en"),
    ("", "en"),
])
def test_language_is_detected_from_the_text(text, expected):
    """A typed question has no surrounding window to infer from.

    Counted rather than merely detected: an English question carrying an
    Arabic gloss is still an English question, and answering the whole thing
    in Arabic because of three glossed words would be wrong.
    """
    assert _detect_language(text) == expected


# --- answering a list ------------------------------------------------------


def _post(payload: dict):
    with TestClient(app) as client:
        return client.post("/api/assessments/answer-questions", json=payload)


def test_a_typed_question_is_answered(answered):
    response = _post({"questions": [{"text": "Do you encrypt data at rest?"}]})

    assert response.status_code == 200
    body = response.json()
    assert len(body["answers"]) == 1
    assert body["answers"][0]["answer"] == "answer to Do you encrypt data at rest?"
    assert body["questions_found"] == 1


def test_several_questions_keep_their_order(answered):
    texts = [f"Question number {n}?" for n in range(1, 6)]
    body = _post({"questions": [{"text": t} for t in texts]}).json()

    assert [a["question"]["text"] for a in body["answers"]] == texts


def test_ids_are_assigned_here_not_by_the_caller(answered):
    """Two questions on one id would make the answers ambiguous to match back."""
    body = _post({"questions": [{"text": "First?"}, {"text": "Second?"}]}).json()
    ids = [a["question"]["id"] for a in body["answers"]]

    assert len(set(ids)) == 2


def test_an_arabic_question_is_answered_in_arabic_by_default(answered):
    _post({"questions": [{"text": "ما هي مدة الاحتفاظ بالبيانات؟"}]})
    assert answered[0].language == "ar"


def test_a_forced_language_overrides_detection(answered):
    body = _post({
        "questions": [{"text": "ما هي مدة الاحتفاظ؟"}],
        "language": "en",
    }).json()
    assert body["language"] == "en"


def test_an_explicit_question_language_is_respected(answered):
    _post({"questions": [{"text": "Do you encrypt data?", "language": "ar"}]})
    assert answered[0].language == "ar"


def test_choice_questions_carry_their_options(answered):
    _post({"questions": [{
        "text": "Is this control implemented?",
        "question_type": "single_choice",
        "options": ["Yes", "No", "Partially"],
    }]})
    assert answered[0].options == ["Yes", "No", "Partially"]
    assert answered[0].question_type.value == "single_choice"


# --- what the endpoint refuses ---------------------------------------------


def test_an_empty_list_is_refused():
    assert _post({"questions": []}).status_code == 422


def test_an_empty_question_is_refused():
    assert _post({"questions": [{"text": ""}]}).status_code == 422


def test_an_absurd_batch_is_refused():
    """A bounded list, so one request cannot fan out unboundedly against Groq."""
    assert _post({"questions": [{"text": "q"} for _ in range(500)]}).status_code == 422


def test_surrounding_whitespace_is_trimmed(answered):
    _post({"questions": [{"text": "   Do you encrypt data?  "}]})
    assert answered[0].text == "Do you encrypt data?"


# --- a failing question does not lose the batch ----------------------------


def test_one_failure_does_not_discard_the_others(monkeypatch):
    async def flaky(question: Question, language):
        if question.text == "boom":
            raise RuntimeError("the model went away")
        return AnsweredQuestion(question=question, answer="ok", confidence=0.9, needs_review=False)

    monkeypatch.setattr(service, "answer_one_question", flaky)
    body = _post({"questions": [{"text": "fine"}, {"text": "boom"}, {"text": "also fine"}]}).json()

    assert len(body["answers"]) == 3
    failed = [a for a in body["answers"] if a["question"]["text"] == "boom"][0]
    assert failed["needs_review"] is True


# --- progress --------------------------------------------------------------


def test_a_batch_reports_progress_under_its_run_id(answered):
    with TestClient(app) as client:
        client.post("/api/assessments/answer-questions", json={
            "questions": [{"text": "one?"}, {"text": "two?"}],
            "run_id": "batch-1",
        })
        state = client.get("/api/assessments/progress/batch-1").json()

    assert state["total"] == 2
    assert state["completed"] == 2
    assert state["stage"] == "done"


def test_progress_is_optional(answered):
    """Without a run id the work still happens; it is simply not observable."""
    assert _post({"questions": [{"text": "one?"}]}).status_code == 200


# --- extraction without answering ------------------------------------------


def test_extraction_returns_questions_without_answering(monkeypatch, tmp_path):
    async def fake_text(path):
        return "1. Do you encrypt data?\n2. How long are logs kept?"

    async def fake_extract(text):
        return "en", [
            Question(id="1", text="Do you encrypt data?"),
            Question(id="2", text="How long are logs kept?"),
        ]

    def explode(*args, **kwargs):
        raise AssertionError("extraction must not answer anything")

    monkeypatch.setattr(service, "extracted_document_text", fake_text)
    monkeypatch.setattr(service, "extract_questions", fake_extract)
    monkeypatch.setattr(service, "answer_one_question", explode)

    with TestClient(app) as client:
        response = client.post(
            "/api/assessments/extract",
            files={"file": ("form.pdf", b"%PDF-1.4 stub", "application/pdf")},
        )

    assert response.status_code == 200
    body = response.json()
    assert [q["text"] for q in body["questions"]] == [
        "Do you encrypt data?", "How long are logs kept?"]
    assert body["language"] == "en"
    assert "answers" not in body


def test_extraction_that_finds_nothing_says_so(monkeypatch):
    async def fake_text(path):
        return "a document with no questions in it"

    async def fake_extract(text):
        return "en", []

    monkeypatch.setattr(service, "extracted_document_text", fake_text)
    monkeypatch.setattr(service, "extract_questions", fake_extract)

    with TestClient(app) as client:
        response = client.post(
            "/api/assessments/extract",
            files={"file": ("empty.pdf", b"%PDF-1.4 stub", "application/pdf")},
        )

    assert response.status_code == 422
    assert "No questions" in response.json()["detail"]


def test_extraction_rejects_an_unsupported_file():
    with TestClient(app) as client:
        response = client.post(
            "/api/assessments/extract",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
    assert response.status_code == 415


# --- a file filed under the wrong type --------------------------------------
#
# The two directions are not symmetric. A policy filed as previous answers
# yields no pairs and indexes nothing, which is recoverable but was reported as
# success. An assessment filed as a guideline indexes perfectly well, and every
# answer in it then carries the authority of a policy.

POLICY = "## 3.4 Access Control\n\n" + ("Access rights are granted on least privilege. " * 60)
QUESTIONNAIRE = "| Question | Response |\n" + (
    "| Do you encrypt data at rest? | Yes, AES-256. |\n"
    "| How long are logs retained? | Twelve months. |\n" * 30)


async def test_a_policy_filed_as_previous_answers_is_reported_not_silently_dropped(monkeypatch, tmp_path):
    async def no_pairs(text):
        return []

    monkeypatch.setattr(service, "extract_qa_pairs", no_pairs)
    monkeypatch.setattr(service, "extracted_document_text", lambda path: _async(POLICY))

    path = tmp_path / "policy.pdf"
    path.write_bytes(b"stub")
    result = await service.ingest(path, service.SourceType.PRIOR_ANSWER)

    assert result.chunks_indexed == 0
    assert result.error and "guideline" in result.error
    assert "nothing was indexed" in result.error


async def test_a_questionnaire_filed_as_a_guideline_is_warned_about(monkeypatch, tmp_path):
    indexed = {}

    def fake_add(name, text, content_hash=""):
        indexed["name"] = name
        return 3

    monkeypatch.setattr(service, "extracted_document_text", lambda path: _async(QUESTIONNAIRE))
    monkeypatch.setattr(service.get_store(), "add_guideline", fake_add)
    monkeypatch.setattr(service.get_store(), "source_with_hash", lambda *a, **k: None)

    path = tmp_path / "completed.pdf"
    path.write_bytes(b"stub")
    result = await service.ingest(path, service.SourceType.GUIDELINE)

    # It is indexed — refusing would be worse than warning — but not silently.
    assert result.chunks_indexed == 3
    assert result.warning and "previous answers" in result.warning


async def test_a_real_policy_raises_no_warning(monkeypatch, tmp_path):
    """The threshold must clear every one of the 80 indexed policies."""
    monkeypatch.setattr(service, "extracted_document_text", lambda path: _async(POLICY))
    monkeypatch.setattr(service.get_store(), "add_guideline", lambda *a, **k: 2)
    monkeypatch.setattr(service.get_store(), "source_with_hash", lambda *a, **k: None)

    path = tmp_path / "policy.pdf"
    path.write_bytes(b"stub")
    result = await service.ingest(path, service.SourceType.GUIDELINE)

    assert result.warning is None


@pytest.mark.parametrize(("text", "warned"), [
    ("short", False),                                   # too small to judge
    ("policy text without questions. " * 200, False),
    ("Is this a question? " * 200, True),
])
def test_the_questionnaire_signal_is_measured_not_guessed(text, warned):
    assert (service._looks_like_a_questionnaire(text, "f.pdf") is not None) is warned


def _async(value):
    async def run():
        return value
    return run()


# --- a failure is distinguishable from a bad answer -------------------------


def test_a_failed_question_carries_a_machine_readable_error():
    from src.graph import failed_answer

    answered = failed_answer(Question(id="1", text="q"), RuntimeError("rate limit reached"))

    assert answered.error == "rate limit reached"
    assert answered.answer == ""
    assert answered.needs_review is True


def test_an_error_with_no_message_still_identifies_itself():
    from src.graph import failed_answer

    assert failed_answer(Question(id="1", text="q"), TimeoutError()).error == "TimeoutError"


def test_a_normal_answer_has_no_error(answered):
    body = _post({"questions": [{"text": "Do you encrypt data?"}]}).json()
    assert body["answers"][0]["error"] == ""


def test_a_failed_answer_surfaces_its_error_through_the_api(monkeypatch):
    async def boom(question, language):
        raise RuntimeError("429 rate limit")

    monkeypatch.setattr(service, "answer_one_question", boom)
    body = _post({"questions": [{"text": "Do you encrypt data?"}]}).json()

    assert body["answers"][0]["error"] == "429 rate limit"
    assert body["answers"][0]["answer"] == ""
