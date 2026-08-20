"""Cross-encoder reranking of retrieved evidence.

Dense retrieval scores a query and a chunk separately and compares the two
vectors, so it can only ever measure how similar they look in the abstract. On
this corpus that produces bunched scores — every candidate between 0.32 and
0.36 — and the ordering inside that band carries little information.

A cross-encoder reads the query and the chunk *together* and scores the pair
directly. It is far too slow to rank a whole collection, which is why it runs
second: dense retrieval proposes a few dozen candidates, the cross-encoder puts
them in order.

It is applied once per question, over the evidence accumulated from every search
query, rather than inside each individual search. Reranking eight searches
separately would cost eight times as much and still leave the merged list
ordered by the scores it was trying to replace.
"""

from __future__ import annotations

import logging
import threading

from src.config import settings
from src.models import Evidence

logger = logging.getLogger(__name__)


_MODEL_LOCK = threading.Lock()
_MODEL = None


def _model():
    """The cross-encoder, loaded once per process.

    Imported lazily: the model is a few gigabytes and most deployments run with
    reranking off, so importing at module scope would make every process — the
    CLI, the tests, the API — pay for a feature it may not use.

    Guarded by a lock rather than `lru_cache`, because the cache does not make
    construction atomic. Questions are answered concurrently and each reranks
    on its own thread, so with four in flight all four missed the empty cache
    together and built their own copy of a 2.3 GB model — four loads, four
    times the memory, and on a GPU host four allocations that need not exist.
    """
    global _MODEL
    if _MODEL is None:
        with _MODEL_LOCK:
            if _MODEL is None:  # another thread may have won the race
                from sentence_transformers import CrossEncoder

                logger.info("Loading reranker %s", settings.reranker_model)
                _MODEL = CrossEncoder(settings.reranker_model, max_length=settings.reranker_max_length)
    return _MODEL


def rerank(query: str, evidence: list[Evidence], top_n: int | None = None) -> list[Evidence]:
    """Return `evidence` in cross-encoder order, best first.

    Falls back to the original order if the model cannot be loaded or scored:
    a missing reranker should cost ranking quality, never the answer.
    """
    top_n = top_n if top_n is not None else settings.max_evidence_chunks
    if not evidence or not query.strip():
        return evidence[:top_n]

    try:
        scores = _model().predict(
            [(query, item.snippet) for item in evidence],
            batch_size=settings.reranker_batch_size,
            show_progress_bar=False,
        )
    except Exception:  # noqa: BLE001 - ranking is an optimisation, not a requirement
        logger.exception("Reranking failed; keeping the retrieval order")
        return evidence[:top_n]

    ordered = sorted(zip(evidence, scores), key=lambda pair: float(pair[1]), reverse=True)

    # The score is rewritten so everything downstream — ordering, the sources
    # block, the exported evidence — reflects the ranking actually used.
    ranked = []
    for item, score in ordered[:top_n]:
        ranked.append(item.model_copy(update={"score": round(float(score), 4)}))
    return ranked
