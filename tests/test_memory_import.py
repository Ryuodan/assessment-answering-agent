"""The knowledge base holds documents; the answer memory holds what we said.

Two things used to blur. The knowledge base panel listed the whole answer
memory as one "source" with a remove button beside it, and its "clear
everything" dropped the memory's vectors along with the policies -- either way
leaving hundreds of rows on the memory page pointing at nothing. And a filled
questionnaire was imported into the memory from the knowledge base panel, with
whatever a model guessed from its text going straight in. These tests hold the
separation, and that answers now come into the memory one at a time.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import answer_memory, service
from src.api import app
from src.config import settings
from src.forms import reading
from tests import forms_fixtures as shapes


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def corpus(memory_index):
    """The fake index, which the knowledge routes reach through `knowledge.get_store`."""
    return memory_index


def _index_a_policy_and_some_answers(memory_index):
    memory_index.records.extend(
        [
            {
                "id": "policy::0",
                "text": "3.1 Access is reviewed quarterly.",
                "metadata": {"source_type": "guideline", "source_name": "T2 - Access Policy.pdf"},
            },
            {
                "id": "Answer memory::0",
                "text": "Q: Do you review access?\nA: Yes.",
                "metadata": {
                    "source_type": "prior_answer",
                    "source_name": "Answer memory",
                    "entry_id": "MEM-1",
                    "question": "Do you review access?",
                    "answer": "Yes.",
                },
            },
        ]
    )


# --- the knowledge base is documents ---------------------------------------------


def test_the_knowledge_base_lists_documents_not_the_answer_memory(corpus, client):
    memory_index = corpus
    _index_a_policy_and_some_answers(memory_index)

    body = client.get("/api/knowledge").json()

    assert [s["name"] for s in body["sources"]] == ["T2 - Access Policy.pdf"]
    assert body["prior_answer_chunks"] == 1, "still counted, and linked to the memory page"


def test_previous_answers_cannot_be_removed_as_though_they_were_a_document(corpus, client):
    memory_index = corpus
    _index_a_policy_and_some_answers(memory_index)

    response = client.delete("/api/knowledge/sources/Answer memory")

    assert response.status_code == 400
    assert "Answer memory page" in response.json()["detail"]
    assert any(r["metadata"]["source_type"] == "prior_answer" for r in memory_index.records)


def test_a_document_can_still_be_removed(corpus, client):
    memory_index = corpus
    _index_a_policy_and_some_answers(memory_index)

    assert client.delete("/api/knowledge/sources/T2 - Access Policy.pdf").status_code == 200
    assert [r["metadata"]["source_name"] for r in memory_index.records] == ["Answer memory"]


def test_removing_a_document_that_is_not_indexed_says_so(corpus, client):
    _index_a_policy_and_some_answers(corpus)

    response = client.delete("/api/knowledge/sources/Never Uploaded.pdf")

    assert response.status_code == 404
    assert len(corpus.records) == 2


def test_clearing_the_knowledge_base_leaves_the_answer_memory_standing(corpus, client):
    memory_index = corpus
    _index_a_policy_and_some_answers(memory_index)

    assert client.delete("/api/knowledge").status_code == 200

    assert [r["metadata"]["source_type"] for r in memory_index.records] == ["prior_answer"]


# --- reading a filled questionnaire ---------------------------------------------------


async def test_a_filled_spreadsheet_gives_its_own_answers(tmp_path):
    pairs = await service.answered_pairs(shapes.already_answered(tmp_path / "hr.xlsx"))

    assert [p.question for p in pairs] == [
        "Has the human resources process been defined and approved?",
        "Do employees receive regular cybersecurity awareness training?",
    ]
    assert "approved in March" in pairs[0].answer, "status and comment, joined"


async def test_a_blank_questionnaire_gives_nothing(tmp_path):
    assert await service.answered_pairs(shapes.simple(tmp_path / "blank.xlsx")) == []


async def test_the_configured_reading_is_used_and_the_rules_only_when_they_find_more(tmp_path, monkeypatch):
    """Guarded is how questionnaires are opened and it stays that way. Reading
    back what somebody already wrote is a different job: on Litware the guarded
    reading found none of 183 answers, and the rules found all of them."""
    monkeypatch.setattr(settings, "detection_strategy", "guarded")
    path = shapes.already_answered(tmp_path / "hr.xlsx")
    real = reading.read
    asked = []

    def read(path, strategy="rules"):
        asked.append(strategy)
        found = real(path, "rules")
        if strategy == "guarded":
            for question in found.form.questions:  # the Litware failure, staged
                question.targets = {}
        return found

    monkeypatch.setattr(reading, "read", read)

    pairs = await service.answered_pairs(path)

    assert asked == ["guarded", "rules"], "the configured strategy first"
    assert len(pairs) == 2, "the rules found them, so the rules' reading is kept"


async def test_on_a_tie_the_configured_reading_is_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "detection_strategy", "guarded")
    path = shapes.already_answered(tmp_path / "hr.xlsx")
    real = reading.read

    def read(path, strategy="rules"):
        found = real(path, "rules")
        for question in found.form.questions:
            question.text = f"[{strategy}] {question.text}"
        return found

    monkeypatch.setattr(reading, "read", read)

    pairs = await service.answered_pairs(path)

    assert all(p.question.startswith("[guarded]") for p in pairs)


# --- answers are added one at a time -----------------------------------------------------


@pytest.mark.parametrize(
    "route",
    [
        "/api/memory/import/read",
        "/api/memory/import",
        "/api/knowledge/prior-assessments",
    ],
)
def test_nothing_takes_a_whole_questionnaire_into_the_answer_memory(client, route, memory_index):
    """Adding to the memory is deliberate: one answer written on the memory page,
    or an edited answer approved on its card. A file read in wholesale is
    hundreds of answers nobody read one by one, each retrieved afterwards as
    something we said."""
    response = client.post(
        route,
        json={
            "source_name": "Vendor.xlsx",
            "pairs": [
                {"question": "Do you review access?", "answer": "Yes."},
            ],
        },
    )

    assert response.status_code in (404, 405)
    assert answer_memory.count() == 0 and memory_index.records == []


def test_no_page_offers_an_import(client):
    for page in ("/", "/workbench", "/memory"):
        body = client.get(page).text
        assert 'id="priorInput"' not in body
        assert "importPanel" not in body and "/api/memory/import" not in body
    assert 'href="memory"' in client.get("/").text, "the knowledge base points at the memory"


def test_add_an_answer_comes_before_the_list_it_lands_in(client):
    body = client.get("/memory").text
    assert body.index("Two answers that disagree") < body.index("Add an answer") < body.index("Everything we have said")


def test_an_answer_added_by_hand_is_remembered(client, memory_index):
    body = client.post(
        "/api/memory",
        json={
            "question": "Do you review access?",
            "answer": "Yes, quarterly.",
        },
    ).json()

    [entry] = answer_memory.entries()
    assert body["entry_id"] == entry.entry_id and entry.origin == "manual"


# --- a box nobody ticked is not an answer ------------------------------------------------


@pytest.mark.parametrize("cell", ["", "   ", "☐", "☐ ☐", "-", "—", "..."])
def test_an_unticked_box_or_a_dash_is_an_empty_cell(cell):
    """The team's BCM form asks for Yes or No by ticking a box and ships with
    "☐" in every answer cell. Read as answers, eleven of them were offered for
    import into the memory -- and the guard against overwriting existing
    answers would have protected them from ever being answered."""
    from src.forms.model import Role, Target

    assert Target(id="t", role=Role.ANSWER, existing=cell).is_empty


@pytest.mark.parametrize("cell", ["Yes", "N/A", "☒", "✓", "X", "0", "نعم"])
def test_a_ticked_box_or_any_word_is_an_answer(cell):
    from src.forms.model import Role, Target

    assert not Target(id="t", role=Role.ANSWER, existing=cell).is_empty
