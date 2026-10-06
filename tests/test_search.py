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

from src import knowledge
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

    async def search(self, query, source_type, k, *, expand=True):
        self.searched_types.append(source_type)
        if self.dense_error:
            raise self.dense_error
        self.expand_calls.append(expand)
        return self.dense if source_type is SourceType.GUIDELINE else []

    def text_search(self, query, source_type, k):
        return self.lexical if source_type is SourceType.GUIDELINE else []

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
