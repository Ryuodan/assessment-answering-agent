"""The knowledge search tool.

Separate from answering: this endpoint exists so a person can check what the
corpus actually says, so it returns the chunks that matched rather than an
answer written from them. The properties that matter are that the two retrieval
modes stay distinguishable, that a fused list cannot invent or lose a hit, and
that a search never expands a unit the way the answering path does.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import knowledge, search
from src.api import app
from src.models import Evidence, SourceType


def hit(name: str, chunk: int, score: float = 0.7, lexical: bool = False) -> Evidence:
    return Evidence(
        source_type=SourceType.GUIDELINE,
        source_name=name,
        snippet=f"text {chunk}",
        chunk=chunk,
        score=score,
        is_lexical=lexical,
        clause_start="3.1",
    )


class FakeStore:
    def __init__(self, dense=None, lexical=None, dense_error=None):
        self.dense = dense or []
        self.lexical = lexical or []
        self.dense_error = dense_error
        self.expand_calls = []
        self.searched_types = []

    async def search(self, query, source_type, k, *, expand=True, source_name=""):
        self.searched_types.append(source_type)
        if self.dense_error:
            raise self.dense_error
        self.expand_calls.append(expand)
        found = self.dense if source_type is SourceType.GUIDELINE else []
        return [item for item in found if not source_name or item.source_name == source_name]

    def text_search(self, query, source_type, k, source_name=""):
        found = self.lexical if source_type is SourceType.GUIDELINE else []
        return [item for item in found if not source_name or item.source_name == source_name]

    def counts_by_type(self):
        # Prior answers are empty, as they are on the real corpus.
        return {SourceType.GUIDELINE.value: 120}

    def documents_indexed(self):
        return ["a.pdf", "b.pdf"]


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore(
        dense=[hit("a.pdf", 1, 0.80), hit("a.pdf", 2, 0.70)],
        lexical=[hit("b.pdf", 9, 1.0, lexical=True), hit("a.pdf", 1, 0.5, lexical=True)],
    )
    monkeypatch.setattr(knowledge, "get_store", lambda team_id=None: fake)
    return fake


def get(**params):
    with TestClient(app) as client:
        return client.get("/api/search", params=params)


def test_semantic_mode_uses_only_the_vectors(store):
    body = get(q="retention", mode="semantic").json()
    assert [r["chunk"] for r in body["results"]] == [1, 2]
    assert not any(r["is_lexical"] for r in body["results"])


def test_keyword_mode_uses_only_bm25(store):
    body = get(q="90 days", mode="keyword").json()
    assert [r["chunk"] for r in body["results"]] == [9, 1]
    assert all(r["is_lexical"] for r in body["results"])


def test_hybrid_returns_the_union_without_duplicates(store):
    body = get(q="retention", mode="hybrid").json()
    keys = [(r["source_name"], r["chunk"]) for r in body["results"]]

    assert len(keys) == len(set(keys)), "one chunk must not appear twice"
    assert set(keys) == {("a.pdf", 1), ("a.pdf", 2), ("b.pdf", 9)}


def remembered(entry_id: str, score: float, lexical: bool = False) -> Evidence:
    """A remembered answer as the memory files it: every one is "Answer memory", chunk 0."""
    return Evidence(
        source_type=SourceType.PRIOR_ANSWER,
        source_name="Answer memory",
        snippet=f"Q: {entry_id}?\nA: Yes.",
        chunk=0,
        entry_id=entry_id,
        score=score,
        is_lexical=lexical,
    )


class MemoryStore(FakeStore):
    """Remembered answers only, found by both the vectors and the text."""

    async def search(self, query, source_type, k, *, expand=True, source_name=""):
        return [remembered("mem-a", 0.80), remembered("mem-b", 0.70)] if source_type is SourceType.PRIOR_ANSWER else []

    def text_search(self, query, source_type, k, source_name=""):
        if source_type is not SourceType.PRIOR_ANSWER:
            return []
        return [remembered("mem-b", 1.0, lexical=True), remembered("mem-a", 0.5, lexical=True)]

    def counts_by_type(self):
        return {SourceType.PRIOR_ANSWER.value: 2}


def test_hybrid_returns_each_remembered_answer_once(monkeypatch):
    """Plan 027: fused by name and chunk, two remembered answers were one result."""
    monkeypatch.setattr(knowledge, "get_store", lambda team_id=None: MemoryStore())

    body = get(q="mfa", mode="hybrid").json()

    assert sorted(r["entry_id"] for r in body["results"]) == ["mem-a", "mem-b"]


def test_a_search_does_not_expand_units(store):
    """The answering path completes a split series so the drafter never takes a
    fragment for the whole list. A search result should be what matched."""
    get(q="retention", mode="semantic")
    assert store.expand_calls == [False], "one collection, never expanded"


def test_results_can_be_confined_to_one_document(store):
    body = get(q="retention", mode="hybrid", source="b.pdf").json()
    assert {r["source_name"] for r in body["results"]} == {"b.pdf"}


def test_an_empty_query_returns_nothing_rather_than_everything(store):
    body = get(q="   ", mode="hybrid").json()
    assert body["results"] == []


def test_an_unknown_mode_is_refused(store):
    assert get(q="x", mode="magic").status_code == 422


def test_the_limit_is_capped(store):
    """A person cannot ask for the whole corpus in one response."""
    body = get(q="retention", limit=5000).json()
    assert len(body["results"]) <= 50


def test_the_indexed_documents_are_listed_for_filtering(store):
    body = get(q="retention").json()
    assert body["documents"] == ["a.pdf", "b.pdf"]


def test_a_lexical_hit_is_marked_so_its_score_is_not_read_as_a_cosine(store):
    """A BM25 rank normalised to the best hit and a cosine similarity are
    different things wearing the same units."""
    body = get(q="90 days", mode="keyword").json()
    assert all(r["is_lexical"] is True for r in body["results"])


def test_an_empty_collection_is_not_searched(store):
    """Searching a collection with no chunks still costs an embedding round
    trip, and the prior-answers one is usually empty."""
    get(q="retention", mode="semantic")
    assert SourceType.PRIOR_ANSWER not in store.searched_types


def test_a_slow_embedding_host_falls_back_to_text(monkeypatch):
    """The embedding service is remote and occasionally slow. A person at a
    search box should get the literal matches, not a spinner or a stack trace."""
    fake = FakeStore(
        lexical=[hit("b.pdf", 9, 1.0, lexical=True)],
        dense_error=TimeoutError("embedding host did not answer"),
    )
    monkeypatch.setattr(knowledge, "get_store", lambda team_id=None: fake)

    body = get(q="retention", mode="semantic").json()

    assert body["degraded"] is True, "the interface must be able to say so"
    assert [r["chunk"] for r in body["results"]] == [9]


def test_a_healthy_search_is_not_marked_degraded(store):
    assert get(q="retention", mode="hybrid").json()["degraded"] is False


# --- a product's documents and the shared policies (plan 031) -------------------------


class Passages(FakeStore):
    """A knowledge base whose one file the vectors find `n` times, best first, `k` at most.

    As Chroma does: the nearest `k` come back however far they are, so a
    knowledge base with `k` passages fills its whole list for any query.
    """

    def __init__(self, name: str, n: int):
        super().__init__(dense=[hit(name, chunk, 0.9 - chunk / 100) for chunk in range(n)])
        self.name = name

    async def search(self, query, source_type, k, *, expand=True, source_name=""):
        return (self.dense if source_type is SourceType.GUIDELINE else [])[:k]

    def documents_indexed(self):
        return [self.name]


def knowledge_bases(monkeypatch, shared: int, own: int) -> None:
    stores = {"": Passages("Shared policy.pdf", shared), "availo": Passages("Availo policy.pdf", own)}
    monkeypatch.setattr(knowledge, "get_store", lambda team_id=None, *, product_id="": stores[product_id])


async def found(limit: int, **scope) -> list[str]:
    body = await search.search_knowledge("backups", mode="semantic", limit=limit, **scope)
    return [r["source_name"] for r in body["results"]]


@pytest.mark.asyncio
async def test_a_products_search_keeps_the_shared_policies_in_it(monkeypatch):
    """The product's hits came first and the list was cut at the limit after them, so a
    product with as many passages as the limit filled it alone: searching "Availo and
    shared policies" never showed a shared policy, and nor did the assistant's search in
    an Availo chat. The limit is shared between the two now, the product's first."""
    knowledge_bases(monkeypatch, shared=30, own=30)

    assert await found(20, product_id="availo") == ["Availo policy.pdf"] * 10 + ["Shared policy.pdf"] * 10
    assert await found(8, product_id="availo") == ["Availo policy.pdf"] * 4 + ["Shared policy.pdf"] * 4


@pytest.mark.asyncio
async def test_what_one_knowledge_base_leaves_the_other_takes(monkeypatch):
    knowledge_bases(monkeypatch, shared=30, own=3)
    assert await found(20, product_id="availo") == ["Availo policy.pdf"] * 3 + ["Shared policy.pdf"] * 17

    knowledge_bases(monkeypatch, shared=2, own=30)
    assert await found(20, product_id="availo") == ["Availo policy.pdf"] * 18 + ["Shared policy.pdf"] * 2


@pytest.mark.asyncio
async def test_the_shared_policies_alone_are_searched_as_before(monkeypatch):
    knowledge_bases(monkeypatch, shared=30, own=30)
    assert await found(20) == ["Shared policy.pdf"] * 20


# --- the team's earlier answers, and one file's passages (TD-074) -------------------------


class Both(FakeStore):
    """A knowledge base of `guidelines` passages and `answers` remembered answers, `k` at most each."""

    def __init__(self, guidelines: int, answers: int):
        super().__init__()
        self.guidelines = [hit("Policy.pdf", chunk, 0.9 - chunk / 100) for chunk in range(guidelines)]
        self.answers = [remembered(f"mem-{n}", 0.8 - n / 100) for n in range(answers)]

    async def search(self, query, source_type, k, *, expand=True, source_name=""):
        return (self.guidelines if source_type is SourceType.GUIDELINE else self.answers)[:k]

    def counts_by_type(self):
        return {SourceType.GUIDELINE.value: len(self.guidelines), SourceType.PRIOR_ANSWER.value: len(self.answers)}


def kinds_of(body: dict) -> list[str]:
    return [r["source_type"] for r in body["results"]]


@pytest.mark.asyncio
async def test_a_persons_search_gives_the_teams_earlier_answers_a_share(monkeypatch):
    """TD-074: remembered answers were listed after every guideline and cut, so on a real
    corpus the Workbench's search never showed one. They take what the policies leave too."""
    monkeypatch.setattr(knowledge, "get_store", lambda team_id=None: Both(guidelines=30, answers=30))
    body = await search.search_knowledge("backups", mode="semantic", limit=20, earlier_answers=True)
    assert kinds_of(body) == ["guideline"] * 10 + ["prior_answer"] * 10

    monkeypatch.setattr(knowledge, "get_store", lambda team_id=None: Both(guidelines=30, answers=4))
    body = await search.search_knowledge("backups", mode="semantic", limit=20, earlier_answers=True)
    assert kinds_of(body) == ["guideline"] * 16 + ["prior_answer"] * 4


@pytest.mark.asyncio
async def test_the_assistants_lookups_read_what_they_read_before(monkeypatch):
    """`search_policies` looks up what the documents say: without the share, guidelines fill it."""
    monkeypatch.setattr(knowledge, "get_store", lambda team_id=None: Both(guidelines=30, answers=30))
    body = await search.search_knowledge("backups", mode="semantic", limit=8)
    assert kinds_of(body) == ["guideline"] * 8


def test_the_workbench_search_asks_for_the_earlier_answers(monkeypatch):
    monkeypatch.setattr(knowledge, "get_store", lambda team_id=None: Both(guidelines=30, answers=30))
    body = get(q="backups", mode="semantic").json()
    assert kinds_of(body).count("prior_answer") == 10


def test_one_files_passages_are_found_however_others_rank():
    """TD-074: the file filter ran after each store's cut, so a file whose passages ranked
    below the best `limit` elsewhere read as "nothing matched" though it held the words."""
    from tests.conftest import FakeVectorStore, bare_store

    store = bare_store(FakeVectorStore([]))
    for n in range(6):
        store.add_guideline(f"Retention {n}.pdf", "## 1 Scope\n\nRetention retention retention is 90 days.")
    store.add_guideline("Backups.pdf", "## 1 Scope\n\nBackups follow the retention schedule.")

    assert all(hit.source_name != "Backups.pdf" for hit in store.text_search("retention", SourceType.GUIDELINE, 3))
    found = store.text_search("retention", SourceType.GUIDELINE, 3, "Backups.pdf")
    assert [hit.source_name for hit in found] == ["Backups.pdf"]


@pytest.mark.asyncio
async def test_the_vectors_are_asked_for_one_files_passages(monkeypatch):
    """The filter goes to Chroma with the kind, so one file's nearest come back, not the corpus's."""
    from tests.conftest import FakeVectorStore, bare_store

    store = bare_store(FakeVectorStore([]))
    asked: list = []
    real = store._store.similarity_search_by_vector_with_relevance_scores

    def recorded(vector, k, where=None, **kwargs):
        asked.append(where)
        return real(vector, k, where, **kwargs)

    store._store.similarity_search_by_vector_with_relevance_scores = recorded
    monkeypatch.setattr(store, "_embed_query", lambda query: _vector())
    await store.search("retention", SourceType.GUIDELINE, 5, expand=False, source_name="Backups.pdf")
    await store.search("retention", SourceType.GUIDELINE, 5, expand=False)

    assert asked == [
        {"$and": [{"source_type": "guideline"}, {"source_name": "Backups.pdf"}]},
        {"source_type": "guideline"},
    ]


async def _vector() -> list[float]:
    return [0.0] * 8
