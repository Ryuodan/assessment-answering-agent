"""The answer memory: the record, the sweep, and the page that manages it.

`test_memory.py` covers what two remembered answers mean to each other. This
covers what happens to them: which are retrievable, which are kept as history,
what an approval teaches, and what a person can undo.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import answer_memory, store, tools
from src.api import app
from src.models import Evidence, SourceType
from tests import forms_fixtures as shapes
from tests.conftest import FakeVectorStore, bare_store


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def answers_yes(monkeypatch):
    from src.models import AnsweredQuestion

    async def fake(questions, language=None, run_id=None, **extra):
        return [
            AnsweredQuestion(
                question=question,
                answer="Yes. Access reviews are carried out every quarter.",
                confidence=0.9,
                needs_review=False,
            )
            for question in questions
        ]

    monkeypatch.setattr("src.tools.service.answer_questions", fake)


class Pair:
    """What `extract_qa_pairs` returns, as far as `adopt_file` is concerned."""

    def __init__(self, question, answer, section=""):
        self.question, self.answer, self.section = question, answer, section


# --- the record ------------------------------------------------------------


def test_an_answer_is_remembered_and_found_again(memory_index):
    entry = answer_memory.record("Do you encrypt backups?", "Yes, with AES-256.")

    assert answer_memory.get(entry.entry_id).answer == "Yes, with AES-256."
    assert entry.stands and entry.origin == "manual"
    assert [record["id"] for record in memory_index.records] == [entry.entry_id], (
        "the row and its vector are one thing addressed two ways"
    )


def test_an_entry_needs_both_halves(memory_index):
    with pytest.raises(ValueError):
        answer_memory.record("Do you encrypt backups?", "   ")


def test_correcting_an_entry_re_indexes_it_and_asks_for_a_fresh_scan(memory_index):
    entry = answer_memory.record("Do you encrypt backups?", "Yes.", scanned=True)
    answer_memory.mark_scanned(entry.entry_id)
    assert not answer_memory.pending()

    answer_memory.update(entry.entry_id, answer="Yes, with AES-256 at rest.")

    assert answer_memory.get(entry.entry_id).answer == "Yes, with AES-256 at rest."
    assert [e.entry_id for e in answer_memory.pending()] == [entry.entry_id]
    assert len(memory_index.records) == 1, "replaced, not duplicated"
    assert "AES-256" in memory_index.records[0]["text"]


def test_an_entry_keeps_its_provenance_and_is_filed_under_one_name(memory_index):
    """Which questionnaire an answer was given in is what a reviewer needs.

    Which *source* it is indexed under is a different question, and the answer
    to it is one bucket: re-indexing a corrected import under the questionnaire
    it came from would add a one-chunk file to the knowledge base for a file
    nobody uploaded, where a `remove` would delete a memory entry.
    """
    answer_memory.adopt_file("PSAT Questionnaire.xlsx", [Pair("Do you run drills?", "Yes.")])
    entry = answer_memory.entries()[0]

    answer_memory.update(entry.entry_id, answer="Yes, twice a year.")

    [indexed] = [r for r in memory_index.records if r["metadata"]["entry_id"] == entry.entry_id]
    assert indexed["metadata"]["source_name"] == answer_memory.MEMORY_SOURCE
    assert indexed["metadata"]["from_file"] == "PSAT Questionnaire.xlsx"
    assert answer_memory.get(entry.entry_id).from_file == "PSAT Questionnaire.xlsx"


def test_forgetting_an_entry_takes_its_vector_with_it(memory_index):
    entry = answer_memory.record("Do you encrypt backups?", "Yes.")

    assert answer_memory.remove(entry.entry_id) is True
    assert answer_memory.get(entry.entry_id) is None
    assert memory_index.records == []
    assert answer_memory.remove(entry.entry_id) is False


def test_forgetting_an_imported_answer_takes_its_vector_too(memory_index):
    """The bulk import stored its chunks under `<source>::<chunk>` and put the
    entry id in the metadata, so a delete by id alone missed all six hundred
    and ninety-eight of them: forgotten from the record, still retrieved, and
    re-adopted the next time the process read the index."""
    memory_index.records.append(
        {
            "id": "Answer memory — the security team's own answers::17",
            "text": "Q: Do you run drills?\nA: Yes, annually.",
            "metadata": {
                "source_type": "prior_answer",
                "entry_id": "MEM-0018",
                "question": "Do you run drills?",
                "answer": "Yes, annually.",
                "source_name": "Answer memory — the security team's own answers",
            },
        }
    )
    answer_memory.forget_sync()
    assert [e.entry_id for e in answer_memory.entries()] == ["MEM-0018"], "adopted"

    assert answer_memory.remove("MEM-0018") is True

    assert memory_index.records == [], "the vector went with the row"


def test_forgetting_the_replacement_puts_the_replaced_answer_back(memory_index):
    """Otherwise the older answer is neither retrievable nor replaced by anything."""
    old = answer_memory.record("Do you encrypt backups?", "No.")
    new = answer_memory.record("Do you encrypt backups?", "Yes, with AES-256.")
    answer_memory.supersede(old.entry_id, by=new.entry_id, because="our position changed")
    assert not answer_memory.get(old.entry_id).stands

    answer_memory.remove(new.entry_id)

    assert answer_memory.get(old.entry_id).stands


def test_a_superseded_entry_is_kept_as_history(memory_index):
    old = answer_memory.record("Are you ISO 27001 certified?", "No, not yet.")
    new = answer_memory.record("Are you ISO 27001 certified?", "Yes, since 2024.")
    answer_memory.supersede(old.entry_id, by=new.entry_id, because="our position changed")

    assert answer_memory.get(old.entry_id) is not None, "an assessor may ask what we said"
    assert answer_memory.superseded_ids() == {old.entry_id}
    assert [e.entry_id for e in answer_memory.entries(standing=True)] == [new.entry_id]
    assert [e.entry_id for e in answer_memory.entries(standing=False)] == [old.entry_id]

    answer_memory.restore(old.entry_id)
    assert answer_memory.superseded_ids() == set()


def test_a_questionnaire_becomes_rows_and_a_corrected_upload_replaces_them(memory_index):
    answer_memory.adopt_file(
        "vendor.xlsx",
        [
            Pair("Do you encrypt backups?", "Yes."),
            Pair("Is MFA enforced?", "Yes."),
            Pair("Are logs retained?", "For twelve months."),
        ],
    )
    assert answer_memory.count() == 3
    assert len(answer_memory.pending()) == 3, "unscanned, which is what puts them in the sweep"

    answer_memory.adopt_file(
        "vendor.xlsx",
        [
            Pair("Do you encrypt backups?", "Yes, with AES-256."),
            Pair("Is MFA enforced?", "Yes."),
        ],
    )

    remaining = {e.question: e.answer for e in answer_memory.entries()}
    assert remaining == {
        "Do you encrypt backups?": "Yes, with AES-256.",
        "Is MFA enforced?": "Yes.",
    }, "the pair the corrected file dropped is gone, and the changed one is changed"


# --- retrieval -------------------------------------------------------------


def _prior(entry_id: str, text: str, score: float = 0.9) -> Evidence:
    return Evidence(
        source_type=SourceType.PRIOR_ANSWER,
        source_name="vendor.xlsx",
        snippet=text,
        score=score,
        entry_id=entry_id,
    )


def test_a_superseded_answer_is_not_retrieved_but_is_still_searchable(memory_index):
    """The filter is the whole mechanism: the vector stays, and a person
    looking for what we said in 2023 can still find it."""
    old = answer_memory.record("Are you certified?", "No.")
    new = answer_memory.record("Are you certified?", "Yes, ISO 27001.")
    answer_memory.supersede(old.entry_id, by=new.entry_id)

    index = bare_store(FakeVectorStore([]))
    kept = index._still_standing([_prior(old.entry_id, "No."), _prior(new.entry_id, "Yes.")])

    assert [item.entry_id for item in kept] == [new.entry_id]
    assert answer_memory.get(old.entry_id).answer == "No."


def test_nothing_superseded_means_nothing_dropped(memory_index):
    index = bare_store(FakeVectorStore([]))
    evidence = [_prior("a::0", "one"), _prior("a::1", "two")]
    assert index._still_standing(evidence) == evidence


def test_an_indexed_answer_from_before_the_memory_existed_still_has_an_id():
    """Its Chroma id was built from these two fields, so it is recoverable."""
    assert answer_memory.entry_id_of({"source_name": "vendor.xlsx", "chunk": 3}) == "vendor.xlsx::3"
    assert answer_memory.entry_id_of({"entry_id": "mem-abc", "chunk": 3}) == "mem-abc"
    assert answer_memory.entry_id_of({"chunk": 3}) == ""


def test_answers_indexed_before_the_record_existed_are_adopted(monkeypatch, memory_index):
    index = bare_store(
        FakeVectorStore(
            [
                {
                    "text": "Q: Do you encrypt backups?\nA: Yes.",
                    "metadata": {
                        "source_type": SourceType.PRIOR_ANSWER.value,
                        "source_name": "old.xlsx",
                        "chunk": 0,
                        "question": "Do you encrypt backups?",
                        "answer": "Yes.",
                    },
                    "id": "old.xlsx::0",
                }
            ]
        )
    )
    monkeypatch.setattr("src.knowledge.get_store", lambda team_id=None: index)

    entries = answer_memory.entries()

    assert [e.entry_id for e in entries] == ["old.xlsx::0"]
    assert entries[0].origin == "import" and entries[0].from_file == "old.xlsx"


def test_an_approved_answer_is_still_an_approved_answer_after_a_rebuild(monkeypatch, memory_index):
    """The record can be rebuilt from the index, and must come back the same.

    Filed as an import, an approved answer loses its date and its reviewer —
    and an entry with no date can supersede nothing, which is most of what
    approving one is for.
    """
    answer_memory.record(
        "Do you encrypt backups?",
        "Yes, with AES-256.",
        origin="approved",
        approved_by="alice@t2.sa",
        from_file="Vendor.xlsx",
    )
    rebuilt = bare_store(
        FakeVectorStore([{"text": r["text"], "metadata": r["metadata"], "id": r["id"]} for r in memory_index.records])
    )
    monkeypatch.setattr("src.knowledge.get_store", lambda team_id=None: rebuilt)
    store.connect().execute("DELETE FROM memory_entries")
    store.connect().commit()
    answer_memory.forget_sync()

    [entry] = answer_memory.entries()

    assert entry.origin == "approved"
    assert entry.approved_by == "alice@t2.sa"
    assert entry.approved_on, "and it can still supersede something"
    assert entry.from_file == "Vendor.xlsx"


def test_adoption_keeps_the_questionnaire_an_answer_was_actually_given_in(monkeypatch, memory_index):
    """A bulk import files many questionnaires under one synthetic source name.

    Taking that name as the provenance made every imported answer look like a
    row of one enormous form -- and the sweep skips pairs from the same form, so
    it silently compared nothing at all. The real name is in the metadata.
    """
    index = bare_store(
        FakeVectorStore(
            [
                {
                    "text": "Q: Do you run drills?\nA: Yes.",
                    "metadata": {
                        "source_type": SourceType.PRIOR_ANSWER.value,
                        "source_name": "Answer memory",
                        "entry_id": "MEM-0001",
                        "chunk": 0,
                        "from_file": "Vendor Security Questionnaire.xlsx",
                        "question": "Do you run drills?",
                        "answer": "Yes.",
                    },
                    "id": "MEM-0001",
                },
                {
                    "text": "Q: Do you run drills?\nA: No.",
                    "metadata": {
                        "source_type": SourceType.PRIOR_ANSWER.value,
                        "source_name": "Answer memory",
                        "entry_id": "MEM-0002",
                        "chunk": 0,
                        "from_file": "Bank Third Party Assessment.xlsx",
                        "question": "Do you run drills?",
                        "answer": "No.",
                    },
                    "id": "MEM-0002",
                },
            ]
        )
    )
    monkeypatch.setattr("src.knowledge.get_store", lambda team_id=None: index)

    files = {entry.entry_id: entry.from_file for entry in answer_memory.entries()}

    assert files == {
        "MEM-0001": "Vendor Security Questionnaire.xlsx",
        "MEM-0002": "Bank Third Party Assessment.xlsx",
    }


# --- the sweep -------------------------------------------------------------


@pytest.fixture
def confirms(monkeypatch):
    """The model, agreeing that everything proposed is the same question."""
    seen = []

    async def same(question, candidates):
        seen.append((question, [c.question for c in candidates]))
        return candidates

    monkeypatch.setattr(answer_memory, "_same_question", same)
    return seen


@pytest.fixture
def near_neighbour(monkeypatch):
    """Retrieval that returns every remembered entry as a close match.

    The question-against-question re-scoring is stubbed through as well: it is
    the one step that talks to the embedding host, and it has its own test.
    """

    async def search(self, query, source_type, k, expand=True):
        return [_prior(entry.entry_id, entry.answer, score=0.93) for entry in answer_memory.entries(limit=50)]

    async def close(question, candidates):
        return candidates

    monkeypatch.setattr("src.knowledge.KnowledgeStore.search", search)
    monkeypatch.setattr(answer_memory, "_close_questions", close)


async def test_only_questions_that_embed_close_enough_are_asked_about(monkeypatch, memory_index):
    """The index scores "Q: … A: …" as one document, so two identical questions
    with different answers come back at 0.76. The threshold was measured
    question against question, and this is where that comparison happens."""
    near = answer_memory.record("Do you encrypt backups?", "Yes.")
    far = answer_memory.record("Is MFA enforced?", "Yes.")
    vectors = {
        "Do you encrypt backups?": [1.0, 0.0],
        "Are backups encrypted?": [0.96, 0.28],  # ~0.96 against the first
        "Is MFA enforced?": [0.2, 0.98],  # ~0.2
    }

    class Fake:
        async def aembed_documents(self, texts):
            return [vectors[text] for text in texts]

    monkeypatch.setattr("src.embeddings.get_embeddings", lambda: Fake())

    close = await answer_memory._close_questions("Are backups encrypted?", [near, far])

    assert [entry.entry_id for entry in close] == [near.entry_id]


async def test_a_later_answer_supersedes_the_one_it_disagrees_with(memory_index, confirms, near_neighbour):
    old = answer_memory.record(
        "Are you ISO 27001 certified?",
        "No, we are not certified.",
        approved_on="2023-01-01T00:00:00+00:00",
        origin="approved",
    )
    new = answer_memory.record(
        "Are you certified to ISO 27001?",
        "Yes, certified since 2024.",
        approved_on="2025-01-01T00:00:00+00:00",
        origin="approved",
    )

    findings = await answer_memory.scan(new)

    assert [f.kind for f in findings] == ["supersedes"]
    assert not answer_memory.get(old.entry_id).stands
    assert answer_memory.get(new.entry_id).stands
    assert not answer_memory.conflicts(), "an ordinary revision is nobody's decision to make"


async def test_two_answers_that_disagree_with_no_ordering_wait_for_a_person(memory_index, confirms, near_neighbour):
    first = answer_memory.adopt_file("a.xlsx", [Pair("Do you run drills?", "Yes, annually.")])[0]
    second = answer_memory.adopt_file("b.xlsx", [Pair("Do you run drills?", "No, not yet.")])[0]

    findings = await answer_memory.scan(second)

    assert [f.kind for f in findings] == ["conflict"]
    raised = answer_memory.conflicts()
    assert len(raised) == 1
    assert {raised[0].entry_id, raised[0].other_id} == {first.entry_id, second.entry_id}
    assert answer_memory.get(first.entry_id).stands, "neither is dropped on a guess"
    assert answer_memory.get(second.entry_id).stands


async def test_the_same_disagreement_is_raised_once(memory_index, confirms, near_neighbour):
    answer_memory.adopt_file("a.xlsx", [Pair("Do you run drills?", "Yes, annually.")])
    second = answer_memory.adopt_file("b.xlsx", [Pair("Do you run drills?", "No.")])[0]

    await answer_memory.scan(second)
    await answer_memory.scan(second)

    assert len(answer_memory.conflicts()) == 1


async def test_a_model_that_writes_its_answer_instead_of_calling_the_tool_means_none(memory_index, monkeypatch):
    """Groq refuses the turn when the model replies with prose. What it replied
    with here was `[]`, which is the answer -- in the one form the API will not
    take. Anything else from that call is still an error."""
    entry = answer_memory.record("Do you run drills?", "Yes.")

    class Refused(Exception):
        body = {"error": {"code": "tool_use_failed", "failed_generation": "[]"}}

    monkeypatch.setattr("src.llm.tool_use_failed", lambda error: isinstance(error, Refused))

    class Boom:
        async def ainvoke(self, messages):
            raise Refused()

    monkeypatch.setattr("src.llm.structured_llm", lambda *a, **k: Boom())
    assert await answer_memory._same_question("Do you run drills?", [entry]) == []

    class Other:
        async def ainvoke(self, messages):
            raise TimeoutError("groq is slow")

    monkeypatch.setattr("src.llm.structured_llm", lambda *a, **k: Other())
    with pytest.raises(TimeoutError):
        await answer_memory._same_question("Do you run drills?", [entry])


async def test_a_neighbouring_control_is_left_alone_when_the_model_says_so(memory_index, near_neighbour, monkeypatch):
    """Similarity proposes; the model disposes. 0.79 and 0.81 do not separate
    an incident-response drill from a business-continuity one."""

    async def different(question, candidates):
        return []

    monkeypatch.setattr(answer_memory, "_same_question", different)
    answer_memory.adopt_file("a.xlsx", [Pair("Do you run continuity drills?", "Yes.")])
    other = answer_memory.adopt_file("b.xlsx", [Pair("Do you run IR drills?", "No.")])[0]

    assert await answer_memory.scan(other) == []
    assert not answer_memory.conflicts()


async def test_two_rows_of_one_questionnaire_are_not_a_contradiction(memory_index, confirms, near_neighbour):
    """One file, filled in by one person on one day. Two rows that look alike
    are two related controls, or the extractor reading one row twice."""
    pairs = answer_memory.adopt_file(
        "vendor.xlsx",
        [
            Pair("Do you run drills?", "Yes, annually."),
            Pair("Do you run drills?", "No."),
        ],
    )

    assert await answer_memory.scan(pairs[1]) == []
    assert not answer_memory.conflicts()


async def test_an_answer_that_arrives_out_of_date_replaces_nothing(memory_index, confirms, near_neighbour):
    """Importing an old questionnaire after a newer one. The old answer is
    marked as replaced, and stops there: an entry that no longer stands has no
    standing to replace or contradict a third."""
    current = answer_memory.record(
        "Are you ISO 27001 certified?",
        "Yes, certified since 2024.",
        origin="approved",
        approved_on="2025-01-01T00:00:00+00:00",
    )
    third = answer_memory.record(
        "Are you certified to ISO 27001?",
        "Yes, and the certificate is current.",
        origin="approved",
        approved_on="2025-06-01T00:00:00+00:00",
    )
    arriving = answer_memory.record(
        "Is the company ISO 27001 certified?",
        "No, not certified.",
        origin="approved",
        approved_on="2023-01-01T00:00:00+00:00",
    )

    findings = await answer_memory.scan(arriving)

    assert [f.kind for f in findings] == ["superseded_by"]
    assert not answer_memory.get(arriving.entry_id).stands
    assert answer_memory.get(current.entry_id).stands
    assert answer_memory.get(third.entry_id).stands


async def test_the_sweep_marks_what_it_has_looked_at(memory_index, confirms, near_neighbour):
    answer_memory.adopt_file(
        "a.xlsx",
        [
            Pair("Do you encrypt backups?", "Yes."),
            Pair("Is MFA enforced?", "Yes."),
        ],
    )
    assert len(answer_memory.pending()) == 2

    await answer_memory.scan_pending()

    assert answer_memory.pending() == []
    assert await answer_memory.scan_pending() == [], "nothing left to look at"


async def test_one_bad_entry_does_not_stop_the_sweep(memory_index, monkeypatch, near_neighbour):
    answer_memory.adopt_file(
        "a.xlsx",
        [
            Pair("Do you encrypt backups?", "Yes."),
            Pair("Is MFA enforced?", "Yes."),
        ],
    )
    calls = []

    async def explode(question, candidates):
        calls.append(question)
        if len(calls) == 1:
            raise RuntimeError("groq is down")
        return []

    monkeypatch.setattr(answer_memory, "_same_question", explode)

    await answer_memory.scan_pending()

    assert len(calls) == 2
    assert len(answer_memory.pending()) == 1, "the one that failed is still waiting"


# --- what a reviewer decides ------------------------------------------------


def test_resolving_a_conflict_keeps_one_and_supersedes_the_other(memory_index):
    first = answer_memory.record("Do you run drills?", "Yes, annually.")
    second = answer_memory.record("Do you run drills?", "No.")
    answer_memory.raise_conflict(first.entry_id, second.entry_id, "they disagree")

    answer_memory.apply_resolution(
        first.entry_id,
        second.entry_id,
        resolution="keep_this",
        by="alice@t2.sa",
    )

    assert answer_memory.get(first.entry_id).stands
    assert not answer_memory.get(second.entry_id).stands
    assert not answer_memory.conflicts(), "closed"
    assert answer_memory.conflicts(open_only=False)[0].resolved_by == "alice@t2.sa"


def test_keeping_both_moves_neither(memory_index):
    first = answer_memory.record("Do you run continuity drills?", "Yes.")
    second = answer_memory.record("Do you run IR drills?", "No.")
    answer_memory.raise_conflict(first.entry_id, second.entry_id, "they disagree")

    answer_memory.apply_resolution(
        first.entry_id,
        second.entry_id,
        resolution="keep_both",
        by="alice@t2.sa",
    )

    assert answer_memory.get(first.entry_id).stands
    assert answer_memory.get(second.entry_id).stands
    assert not answer_memory.conflicts()


# --- approving an answer teaches it -----------------------------------------


def _approve_one(client, tmp_path, answers_yes):
    batch = client.post(
        "/api/forms",
        files={
            "file": (
                "vendor.xlsx",
                shapes.simple(tmp_path / "vendor.xlsx").read_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    ).json()
    batch_id = batch["id"]
    client.post(f"/api/forms/{batch_id}/answer", json={"scope": {}})
    question_id = client.get(f"/api/forms/{batch_id}").json()["questions"][0]["id"]
    return batch_id, question_id


def _write_one(client, batch_id, question_id, text):
    """What a reviewer does when the draft is not quite what we say."""
    return client.post(
        f"/api/forms/{batch_id}/answers",
        json={"question_id": question_id, "text": text},
    )


def test_approving_an_answer_somebody_wrote_teaches_the_memory(client, tmp_path, answers_yes, memory_index):
    batch_id, question_id = _approve_one(client, tmp_path, answers_yes)
    _write_one(client, batch_id, question_id, "Yes. Access reviews run every quarter, owned by the CISO.")

    body = client.post(
        f"/api/forms/{batch_id}/approve",
        json={"question_id": question_id},
    ).json()

    assert body["remembered"]
    entry = answer_memory.get(body["remembered"])
    assert "owned by the CISO" in entry.answer
    assert entry.origin == "approved" and entry.approved_by and entry.approved_on
    assert entry.from_file == "vendor.xlsx"


def test_approving_the_models_own_draft_teaches_it_nothing(client, tmp_path, answers_yes, memory_index):
    """The loop this closes: a drafted answer waved through, remembered, and
    then retrieved as a previous answer to draft the next one from -- at a
    confidence the loop manufactured rather than earned. Nobody wrote anything
    here, so the memory learns nothing."""
    batch_id, question_id = _approve_one(client, tmp_path, answers_yes)

    body = client.post(
        f"/api/forms/{batch_id}/approve",
        json={"question_id": question_id},
    ).json()

    assert body["remembered"] == ""
    assert answer_memory.count() == 0
    assert body["questions"][0]["approved"] is True, "still approved, and still fills the file"
    assert body["questions"][0]["will_be_written"] is True


def test_the_memory_keeps_the_words_that_went_into_the_file(client, tmp_path, answers_yes, memory_index):
    """A questionnaire set to brief is answered with the brief text, and a
    person who shortens one has written *that*.

    Remembering `answer` regardless put the untouched full draft into the
    memory under a reviewer's name — the model's own words, laundered through
    an approval, which is the one thing the gate exists to prevent."""
    batch_id, question_id = _approve_one(client, tmp_path, answers_yes)
    client.post(f"/api/forms/{batch_id}/detail", json={"detail": "brief"})
    client.post(
        f"/api/forms/{batch_id}/answers",
        json={
            "question_id": question_id,
            "text": "Yes, quarterly.",
            "which": "brief",
        },
    )

    body = client.post(
        f"/api/forms/{batch_id}/approve",
        json={"question_id": question_id},
    ).json()

    assert answer_memory.get(body["remembered"]).answer == "Yes, quarterly."


def test_the_card_says_whether_the_memory_learned_anything(client, tmp_path, answers_yes, memory_index):
    """Both halves of the click, on the card, after the message has gone."""
    batch_id, question_id = _approve_one(client, tmp_path, answers_yes)

    agreed = client.post(
        f"/api/forms/{batch_id}/approve",
        json={"question_id": question_id},
    ).json()["questions"][0]
    assert agreed["approved"] is True and agreed["remembered"] is False

    client.post(
        f"/api/forms/{batch_id}/answers",
        json={
            "question_id": question_id,
            "text": "Yes, every quarter, owned by the CISO.",
        },
    )
    written = client.post(
        f"/api/forms/{batch_id}/approve",
        json={"question_id": question_id},
    ).json()["questions"][0]

    assert written["approved"] is True, "approving still marks it approved"
    assert written["remembered"] is True
    assert written["by_hand"] is True


def test_approving_twice_remembers_once(client, tmp_path, answers_yes, memory_index):
    batch_id, question_id = _approve_one(client, tmp_path, answers_yes)
    _write_one(client, batch_id, question_id, "Yes, every quarter.")

    client.post(f"/api/forms/{batch_id}/approve", json={"question_id": question_id})
    client.post(f"/api/forms/{batch_id}/approve", json={"question_id": question_id})

    assert answer_memory.count() == 1, "three near-identical entries is three chances to be wrong"


def test_a_second_approval_still_knows_who_wrote_it(client, tmp_path, answers_yes, memory_index):
    """Approving used to overwrite the mark that said the words were a
    person's, so the second approval of the same answer taught nothing."""
    batch_id, question_id = _approve_one(client, tmp_path, answers_yes)
    _write_one(client, batch_id, question_id, "Yes, every quarter.")
    client.post(f"/api/forms/{batch_id}/approve", json={"question_id": question_id})
    answer_memory.remove(answer_memory.entries()[0].entry_id)

    body = client.post(
        f"/api/forms/{batch_id}/approve",
        json={"question_id": question_id},
    ).json()

    assert body["remembered"], "the words are still hers"


def test_taking_an_approval_back_forgets_it(client, tmp_path, answers_yes, memory_index):
    batch_id, question_id = _approve_one(client, tmp_path, answers_yes)
    _write_one(client, batch_id, question_id, "Yes, every quarter.")
    client.post(f"/api/forms/{batch_id}/approve", json={"question_id": question_id})
    assert answer_memory.count() == 1

    client.post(
        f"/api/forms/{batch_id}/approve",
        json={"question_id": question_id, "approved": False},
    )

    assert answer_memory.count() == 0, "an answer somebody withdrew should not be quoted back"


def test_an_entry_whose_id_has_a_slash_can_still_be_managed(client, memory_index):
    """`approved::<batch>::Cybersecurity Governance/Q1`.

    A question id carries the shape of the questionnaire it came from, and the
    Word forms number theirs `Section/Q1`. The browser sends the slash as
    `%2F`, the server decodes it before routing, and a path parameter never
    spans a slash — so correcting or forgetting one of these answered 404 while
    the page went on showing the card, which is exactly what it looks like when
    nothing happened.
    """
    from urllib.parse import quote

    entry = answer_memory.record(
        "Is there a cybersecurity governance framework?",
        "Yes.",
        entry_id="approved::b6c2fe198fc7::Cybersecurity Governance/Q1",
        origin="approved",
        approved_by="a@t2.sa",
    )
    at = "/api/memory/" + quote(entry.entry_id, safe="!*'()")

    assert client.patch(at, json={"answer": "Yes, reviewed annually."}).status_code == 200
    assert answer_memory.get(entry.entry_id).answer == "Yes, reviewed annually."

    answer_memory.supersede(entry.entry_id, by="mem-something")
    assert client.post(at + "/restore").status_code == 200
    assert answer_memory.get(entry.entry_id).stands

    assert client.delete(at).status_code == 200
    assert answer_memory.get(entry.entry_id) is None


def test_the_routes_that_take_an_id_do_not_swallow_the_ones_that_do_not(client, memory_index):
    """`{entry_id:path}` matches slashes, so the neighbouring routes have to
    stay reachable."""
    assert client.get("/api/memory/conflicts").status_code == 200
    assert client.post(
        "/api/memory/conflicts/resolve",
        json={
            "entry_id": "a",
            "other_id": "b",
            "resolution": "keep_this",
        },
    ).status_code in (200, 404)
    assert client.post("/api/memory/scan").status_code == 200


# --- the page ---------------------------------------------------------------


def test_the_memory_has_a_page_of_its_own(client):
    body = client.get("/memory").text
    assert 'id="entries"' in body
    assert "<title>Answer memory" in body


def test_the_page_lists_adds_edits_and_forgets(client, memory_index):
    added = client.post(
        "/api/memory",
        json={
            "question": "Do you encrypt backups?",
            "answer": "Yes, with AES-256.",
        },
    ).json()
    assert added["origin"] == "manual"

    listed = client.get("/api/memory").json()
    assert [e["entry_id"] for e in listed["entries"]] == [added["entry_id"]]
    assert listed["stats"]["standing"] == 1

    edited = client.patch(
        f"/api/memory/{added['entry_id']}",
        json={"answer": "Yes, AES-256 at rest and in transit."},
    ).json()
    assert "in transit" in edited["answer"]

    assert client.delete(f"/api/memory/{added['entry_id']}").status_code == 200
    assert client.get("/api/memory").json()["entries"] == []


def test_the_page_can_search_and_filter(client, memory_index):
    client.post("/api/memory", json={"question": "Do you encrypt backups?", "answer": "Yes."})
    client.post("/api/memory", json={"question": "Is MFA enforced?", "answer": "Yes."})

    found = client.get("/api/memory", params={"query": "MFA"}).json()
    assert [e["question"] for e in found["entries"]] == ["Is MFA enforced?"]
    assert found["total"] == 1

    assert client.get("/api/memory", params={"origin": "import"}).json()["entries"] == []


def test_the_page_shows_both_sides_of_a_conflict_and_takes_the_decision(client, memory_index):
    first = answer_memory.record("Do you run drills?", "Yes, annually.")
    second = answer_memory.record("Do you run drills?", "No.")
    answer_memory.raise_conflict(first.entry_id, second.entry_id, "they disagree")

    pair = client.get("/api/memory/conflicts").json()["conflicts"][0]
    assert {pair["entry"]["answer"], pair["other"]["answer"]} == {"Yes, annually.", "No."}

    assert (
        client.post(
            "/api/memory/conflicts/resolve",
            json={
                "entry_id": first.entry_id,
                "other_id": second.entry_id,
                "resolution": "keep_this",
            },
        ).status_code
        == 200
    )

    assert client.get("/api/memory/conflicts").json()["conflicts"] == []
    assert not answer_memory.get(second.entry_id).stands


def test_a_superseded_entry_can_be_put_back(client, memory_index):
    old = answer_memory.record("Are you certified?", "No.")
    new = answer_memory.record("Are you certified?", "Yes.")
    answer_memory.supersede(old.entry_id, by=new.entry_id)

    body = client.post(f"/api/memory/{old.entry_id}/restore").json()

    assert body["stands"] is True


def test_editing_something_that_is_not_there_is_a_404(client, memory_index):
    assert client.patch("/api/memory/nope", json={"answer": "x"}).status_code == 404
    assert client.delete("/api/memory/nope").status_code == 404
    assert client.post("/api/memory/nope/restore").status_code == 404


def test_the_sweep_can_be_asked_for_and_says_what_is_left(client, memory_index, monkeypatch):
    """Bounded per press, because a backlog is one model call per entry."""
    asked = []

    async def nothing(limit=200, team_id=None):
        asked.append(limit)
        return []

    monkeypatch.setattr(answer_memory, "scan_pending", nothing)
    answer_memory.adopt_file("vendor.xlsx", [Pair("Do you encrypt backups?", "Yes.")])

    body = client.post("/api/memory/scan").json()

    assert body["scanned"] is True and body["found"] == []
    assert asked == [50], "a press is a batch, not the whole queue"
    assert body["stats"]["unscanned"] == 1, "and it says what is still waiting"


def test_the_memory_is_the_teams_rather_than_one_persons(client, memory_index):
    """Two people on one team see one memory. What the shared record keeps is
    who did what, not a separate copy each."""
    from src import identity

    alice = identity.local_user()
    entry = answer_memory.record(
        "Do you encrypt backups?",
        "Yes.",
        approved_by=alice.email,
        team_id=alice.team_id,
    )

    assert entry.approved_by == alice.email
    assert [e["entry_id"] for e in client.get("/api/memory").json()["entries"]] == [entry.entry_id]


def test_the_tools_id_for_an_approved_answer_is_stable():
    assert tools._memory_id("b1", "q1") == tools._memory_id("b1", "q1")
    assert tools._memory_id("b1", "q1") != tools._memory_id("b1", "q2")


# --- the sweep that runs after an approval ----------------------------------


async def test_approvals_in_a_row_share_one_sweep_rather_than_racing(monkeypatch):
    """Each approval of a written answer schedules the sweep, and each sweep is a
    model call per pending entry. Five approvals clicked through quickly started
    five sweeps over the same five entries -- twenty-five comparisons for five."""
    import asyncio

    from src import api

    started = []
    release = asyncio.Event()

    async def sweep(*, limit=25, concurrency=4):
        started.append(limit)
        if len(started) == 1:
            await release.wait()
        return []

    monkeypatch.setattr(api.answer_memory, "scan_pending", sweep)

    first = asyncio.create_task(api._scan_memory())
    await asyncio.sleep(0)
    await asyncio.gather(*(api._scan_memory() for _ in range(4)))
    assert len(started) == 1, "the others join the sweep already running"

    release.set()
    await first
    assert len(started) == 2, "and one more pass picks up what arrived while it ran"


# --- an entry forgotten while the sweep was still looking at it ----------------


async def test_an_entry_withdrawn_mid_sweep_replaces_nothing(memory_index, near_neighbour, monkeypatch):
    """Approving a written answer starts the sweep; withdrawing it seconds later
    deletes the entry. The sweep, still waiting on the model, then marked an
    imported answer as replaced by an entry that no longer existed -- and a
    replaced answer is never retrieved again."""
    older = answer_memory.adopt_file("old.xlsx", [Pair("Do you have a CISO?", "Yes.")])[0]
    newer = answer_memory.record(
        "Do you have a chief information security officer?",
        "Yes, since 2024.",
        origin="approved",
        entry_id="approved::b::q1",
    )

    async def slow_and_then_withdrawn(question, candidates):
        answer_memory.remove(newer.entry_id)  # the reviewer withdraws meanwhile
        return candidates

    monkeypatch.setattr(answer_memory, "_same_question", slow_and_then_withdrawn)

    await answer_memory.scan(newer)

    assert answer_memory.get(older.entry_id).stands, "replaced by nothing"
    assert older.entry_id not in answer_memory.superseded_ids()
    assert not answer_memory.conflicts()


def test_a_replacement_that_no_longer_exists_does_not_hide_an_answer(memory_index):
    entry = answer_memory.adopt_file("old.xlsx", [Pair("Do you have a CISO?", "Yes.")])[0]
    store.connect().execute(
        "UPDATE memory_entries SET superseded_by = 'approved::gone::q1' WHERE entry_id = ?",
        (entry.entry_id,),
    )
    store.connect().commit()

    assert entry.entry_id not in answer_memory.superseded_ids(), "still retrieved"

    answer_memory.forget_sync()
    answer_memory.stats()  # the first read of the memory repairs it
    assert answer_memory.get(entry.entry_id).stands


def test_a_disagreement_needs_both_answers_to_exist(memory_index):
    kept = answer_memory.record("Do you have a CISO?", "Yes.")
    answer_memory.raise_conflict(kept.entry_id, "approved::gone::q1", "they disagree")
    assert not answer_memory.conflicts()
