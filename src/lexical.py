"""Lexical (BM25) retrieval, fused with the dense search.

Dense embeddings are the right default for policy text: they match "how quickly
is access revoked" to "access rights are cancelled on the last working day"
without sharing a word. What they are bad at is the thing compliance questions
ask for most — an exact figure.

The measured case: the PDPL 72-hour breach-reporting duty sits in one bullet of
a clause about data security measures generally, so its embedding is dominated
by encryption, testing and awareness training. A query naming 72 hours ranked
it eleventh, in a field where every score sat between 0.32 and 0.36. BM25 puts
it first, because "72" is a rare token and the chunk contains it.

Fusion is Reciprocal Rank Fusion: each list contributes 1/(k + rank), summed.
RRF uses only the ranks, so the two systems' incomparable score scales never
have to be normalised against each other — which is what makes it stable when
dense scores are bunched, exactly the case that motivated this module.
"""

from __future__ import annotations

import logging
import re

from rank_bm25 import BM25Okapi

from src.chunking import fold_digits

logger = logging.getLogger(__name__)

# Splits on anything that is not a letter or digit, which keeps Arabic words,
# Latin words and bare numerals as tokens. Arabic morphology is left alone: the
# dense side already handles meaning, and what BM25 is here for is the literal
# "72", "90 days", "AES-256" that embeddings blur.
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)

# The standard RRF constant. Large enough that the top few ranks of either list
# stay close together, so one system's confident first place does not
# automatically beat the other's.
_RRF_K = 60


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.casefold())


def parse_search_query(query: str) -> tuple[list[str], list[str], list[str]]:
    """Split a search box query into (phrases, terms, exclusions), case-folded.

    The notation people already expect from a search box, and nothing more:

        network access     both terms must appear
        "least privilege"  the quoted run must appear exactly, in order
        backup -cloud      the minus sign excludes

    Case folding rather than lowercasing, because `str.lower()` leaves some
    non-ASCII pairs unequal; digits are folded so an Arabic-Indic numeral in the
    query finds an ASCII one in the document.
    """
    phrases: list[str] = []
    terms: list[str] = []
    excluded: list[str] = []

    for quoted, bare in re.findall(r'"([^"]*)"|(\S+)', query or ""):
        if quoted:
            text = fold_digits(quoted).casefold().strip()
            if text:
                phrases.append(text)
            continue
        token = bare.strip()
        if token in ("-", '"'):
            continue
        if token.startswith("-") and len(token) > 1:
            excluded.append(fold_digits(token[1:]).casefold())
        else:
            terms.append(fold_digits(token).casefold())

    return phrases, terms, excluded


class LexicalIndex:
    """An in-memory BM25 index over one collection's chunks.

    Rebuilt from the vector store rather than persisted: a few hundred policy
    chunks tokenise in well under a second, and a stale lexical index that
    disagrees with the vectors would be a genuinely confusing bug.
    """

    def __init__(self, keys: list, documents: list[str]):
        self.keys = keys
        self._bm25 = BM25Okapi([tokenize(document) for document in documents]) if documents else None

    def __len__(self) -> int:
        return len(self.keys)

    def search(self, query: str, k: int) -> list:
        """The keys of the `k` best-matching documents, best first."""
        tokens = tokenize(query)
        if self._bm25 is None or not tokens:
            return []

        scores = self._bm25.get_scores(tokens)
        ranked = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)
        return [self.keys[index] for index in ranked[:k] if scores[index] > 0]


def reciprocal_rank_fusion(rankings: list[list], k: int = _RRF_K, weights: list[float] | None = None) -> list:
    """Fuse several ranked key lists into one, best first.

    `weights` scales each list's contribution. Equal weights measured worse than
    dense retrieval alone: BM25 confidently ranks a chunk that merely shares a
    rare word, and at equal weight that chunk displaces a semantically better
    one. Weighting the lexical list below the dense one changes what it can do —
    it can still *promote* a chunk dense also found and ranked poorly, which is
    the case worth having, but a chunk only BM25 liked can no longer outrank
    anything dense returned. It fills the tail instead.
    """
    scales = weights or [1.0] * len(rankings)
    totals: dict = {}
    for ranking, weight in zip(rankings, scales):
        for rank, key in enumerate(ranking, start=1):
            totals[key] = totals.get(key, 0.0) + weight / (k + rank)

    # Ties broken by best rank achieved anywhere, so the ordering is total and
    # does not depend on dict insertion accidents.
    best_rank = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking, start=1):
            best_rank[key] = min(best_rank.get(key, rank), rank)

    return sorted(totals, key=lambda key: (-totals[key], best_rank[key]))
