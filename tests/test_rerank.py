"""Cross-encoder reranking.

The model itself is exercised by the opt-in live tests; these cover the parts
that must hold whether or not it loads — above all that a missing or broken
reranker costs ranking quality and never the answer.
"""

from __future__ import annotations

import pytest

from src import rerank as rerank_module
from src.config import settings
from src.graph import nodes
from src.models import Evidence, Question, SourceType


def _evidence(chunk: int, snippet: str) -> Evidence:
    return Evidence(
        source_type=SourceType.GUIDELINE,
        source_name="policy.pdf",
        snippet=snippet,
        score=0.33,
        chunk=chunk,
    )


CANDIDATES = [
    _evidence(0, "Cryptographic keys are rotated annually."),
    _evidence(1, "Data breaches are reported within 72 hours as mandated by PDPL."),
    _evidence(2, "Desks must be cleared at the end of each working day."),
]


@pytest.fixture
def reranking_on(monkeypatch):
    monkeypatch.setattr(settings, "reranker_enabled", True)


def _stub_scores(monkeypatch, scores):
    class _Model:
        def predict(self, pairs, **kwargs):
            assert len(pairs) == len(scores)
            return scores

    monkeypatch.setattr(rerank_module, "_model", lambda: _Model())


# --- the ranking itself ----------------------------------------------------


def test_reranking_reorders_by_the_cross_encoder_score(monkeypatch):
    _stub_scores(monkeypatch, [0.01, 0.98, 0.02])

    ranked = rerank_module.rerank("breach reporting deadline", CANDIDATES)

    assert [item.chunk for item in ranked] == [1, 2, 0]


def test_the_new_score_is_written_onto_the_evidence(monkeypatch):
    """Everything downstream reads .score, so it must reflect the ranking used."""
    _stub_scores(monkeypatch, [0.01, 0.98, 0.02])

    ranked = rerank_module.rerank("breach reporting deadline", CANDIDATES)

    assert ranked[0].score == 0.98


def test_reranking_does_not_mutate_the_input(monkeypatch):
    _stub_scores(monkeypatch, [0.01, 0.98, 0.02])

    rerank_module.rerank("anything", CANDIDATES)

    assert [item.score for item in CANDIDATES] == [0.33, 0.33, 0.33]


def test_reranking_truncates_to_top_n(monkeypatch):
    _stub_scores(monkeypatch, [0.01, 0.98, 0.02])

    assert len(rerank_module.rerank("q", CANDIDATES, top_n=2)) == 2


def test_a_broken_reranker_keeps_the_retrieval_order(monkeypatch):
    """A missing model costs ranking quality, never the answer."""

    def explode():
        raise RuntimeError("model weights are missing")

    monkeypatch.setattr(rerank_module, "_model", explode)

    ranked = rerank_module.rerank("q", CANDIDATES)

    assert [item.chunk for item in ranked] == [0, 1, 2]


@pytest.mark.parametrize(("query", "evidence"), [("", CANDIDATES), ("   ", CANDIDATES), ("q", [])])
def test_nothing_to_rank_is_not_an_error(query, evidence):
    assert rerank_module.rerank(query, evidence) == evidence[: settings.max_evidence_chunks]


# --- the graph node --------------------------------------------------------


def _state(**overrides):
    return {
        "question": Question(id="1", text="How quickly are breaches reported?", language="en"),
        "language": "en",
        "evidence": list(CANDIDATES),
        **overrides,
    }


async def test_the_node_is_a_no_op_when_reranking_is_off(monkeypatch):
    monkeypatch.setattr(settings, "reranker_enabled", False)

    result = await nodes.rerank_evidence(_state())

    assert [item.chunk for item in result["ranked"]] == [0, 1, 2]


async def test_the_node_ranks_against_the_question_not_the_search_queries(monkeypatch, reranking_on):
    seen: list[str] = []

    def fake(query, evidence, top_n=None):
        seen.append(query)
        return list(reversed(evidence))

    monkeypatch.setattr(nodes, "rerank", fake)

    result = await nodes.rerank_evidence(_state(search_queries=["breach notification duty"]))

    assert seen == ["How quickly are breaches reported?"]
    assert [item.chunk for item in result["ranked"]] == [2, 1, 0]


async def test_the_node_handles_an_empty_evidence_list(reranking_on):
    assert (await nodes.rerank_evidence(_state(evidence=[])))["ranked"] == []


# --- what the drafter reads ------------------------------------------------


def test_the_prompt_reads_the_ranked_order_when_present():
    state = _state(ranked=[CANDIDATES[1], CANDIDATES[0]])
    assert [item.chunk for item in nodes._sources(state)] == [1, 0]


def test_the_prompt_falls_back_to_the_retrieval_order():
    assert [item.chunk for item in nodes._sources(_state())] == [0, 1, 2]


def test_the_prompt_is_capped_at_the_evidence_limit(monkeypatch):
    monkeypatch.setattr(settings, "max_evidence_chunks", 2)
    assert len(nodes._sources(_state())) == 2


# --- one model, however many threads ---------------------------------------


def test_the_model_is_built_once_under_concurrent_first_use(monkeypatch):
    """Four questions reranking at once built four copies of a 2.3 GB model.

    The threads are released together, so they reach the lock at the same
    moment — the race an unguarded `lru_cache` loses. Construction is slowed
    deliberately to widen the window a second thread could slip through.
    """
    import sys
    import threading as _threading
    import time

    from src import rerank as module

    builds = []
    start_together = _threading.Barrier(4)

    class _Model:
        def predict(self, pairs, **kwargs):
            return [0.5] * len(pairs)

    def build(name, max_length=None):
        time.sleep(0.05)
        builds.append(name)
        return _Model()

    class _FakeSentenceTransformers:
        CrossEncoder = staticmethod(build)

    monkeypatch.setattr(module, "_MODEL", None)
    monkeypatch.setattr(module, "_MODEL_LOCK", _threading.Lock())
    monkeypatch.setitem(sys.modules, "sentence_transformers", _FakeSentenceTransformers)

    seen = []

    def worker():
        start_together.wait(timeout=5)
        seen.append(module._model())

    threads = [_threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(builds) == 1, f"model built {len(builds)} times"
    # And every caller got the same instance, not a per-thread copy.
    assert len(seen) == 4 and len({id(model) for model in seen}) == 1
