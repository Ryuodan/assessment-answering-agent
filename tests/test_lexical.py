"""BM25 retrieval and rank fusion.

The case that motivated this module: a compliance question asks for an exact
figure, and the figure lives in one bullet of a clause about something else.
Dense retrieval ranks that chunk eleventh out of a bunched field; BM25 ranks it
first, because the numeral is a rare token.
"""

from __future__ import annotations

import pytest

from src.config import settings
from src.lexical import LexicalIndex, reciprocal_rank_fusion, tokenize
from src.models import SourceType
from tests.conftest import FakeVectorStore, bare_store


# --- tokenising ------------------------------------------------------------


def test_tokenize_keeps_numerals_and_folds_case():
    assert tokenize("Report within 72 Hours") == ["report", "within", "72", "hours"]


def test_tokenize_splits_hyphenated_identifiers():
    """AES-256 becomes two tokens; "256" is still the rare one that matches."""
    assert tokenize("AES-256 encryption") == ["aes", "256", "encryption"]


def test_tokenize_keeps_arabic_words_whole():
    assert tokenize("الإبلاغ خلال 72 ساعة") == ["الإبلاغ", "خلال", "72", "ساعة"]


def test_tokenize_ignores_punctuation_only_input():
    assert tokenize("—  ,  §") == []


# --- BM25 ------------------------------------------------------------------


BULLETS = [
    "3.4.5 Data Security Measures: encryption in transit and at rest, regular "
    "vulnerability assessments, access control and multi-factor authentication, "
    "security awareness training, and an incident response plan to manage and "
    "report any data breaches within 72 hours, as mandated by PDPL.",
    "3.4.6 Data Breach Management: notify the relevant authority and affected "
    "data subjects within the legally required timeframe, mitigate the impact, "
    "and document all breaches and corrective measures taken.",
    "3.1 Cryptographic keys must be rotated annually and stored in a hardware "
    "security module. Key length requirements are reviewed each year.",
]


def test_bm25_finds_the_chunk_holding_the_figure():
    """The 72-hour duty is in a clause about security measures generally."""
    index = LexicalIndex(keys=["a", "b", "c"], documents=BULLETS)
    assert index.search("breach reporting within 72 hours PDPL", k=2)[0] == "a"


def test_bm25_returns_nothing_when_no_query_term_appears():
    """Zero-score documents are dropped, so fusion is not handed noise."""
    index = LexicalIndex(keys=["a", "b", "c"], documents=BULLETS)
    assert index.search("wireless telemetry procurement", k=3) == []


def test_bm25_handles_an_empty_index():
    index = LexicalIndex(keys=[], documents=[])
    assert len(index) == 0
    assert index.search("anything", k=5) == []


def test_bm25_ignores_a_query_with_no_usable_tokens():
    index = LexicalIndex(keys=["a"], documents=["some policy text"])
    assert index.search("§ — ,", k=5) == []


# --- fusion ----------------------------------------------------------------


def test_fusion_promotes_a_chunk_both_systems_rank_moderately():
    """Agreement beats a single system's confident first place."""
    dense = ["x", "agreed", "y"]
    lexical = ["z", "agreed", "w"]
    assert reciprocal_rank_fusion([dense, lexical])[0] == "agreed"


def test_fusion_keeps_a_chunk_only_one_system_found():
    fused = reciprocal_rank_fusion([["a", "b"], ["c"]])
    assert set(fused) == {"a", "b", "c"}


def test_fusion_of_one_ranking_preserves_its_order():
    assert reciprocal_rank_fusion([["a", "b", "c"]]) == ["a", "b", "c"]


def test_fusion_of_nothing_is_empty():
    assert reciprocal_rank_fusion([]) == []


# --- the store's hybrid path ----------------------------------------------


@pytest.fixture
def hybrid():
    original = settings.hybrid_search
    settings.hybrid_search = True
    yield
    settings.hybrid_search = original


def _store():
    records = [
        {
            "text": text,
            "metadata": {
                "source_type": SourceType.GUIDELINE.value,
                "source_name": "privacy.pdf",
                "chunk": index,
                "clause": "",
                "unit_id": f"u{index}",
                "part": 1,
                "parts": 1,
            },
        }
        for index, text in enumerate(BULLETS)
    ]
    fake = FakeVectorStore(records)
    return bare_store(fake), fake


async def test_hybrid_recovers_a_chunk_the_dense_pass_ranked_last(hybrid):
    """Dense puts the cryptography chunk first; the query names the figure.

    "72 hours" and "PDPL" appear only in the security-measures clause, so the
    lexical pass is unambiguous — which is the situation this is for. Where both
    chunks share the query's words, weighting deliberately leaves dense in
    charge.
    """
    store, fake = _store()
    fake.stage(chunk_indexes=[2, 1, 0], score=0.33)

    hits = await store.search("72 hours PDPL", SourceType.GUIDELINE, 3, expand=False)

    assert "72 hours" in hits[0].snippet


async def test_hybrid_is_a_no_op_when_nothing_matches_lexically(hybrid):
    store, fake = _store()
    fake.stage(chunk_indexes=[1, 0], score=0.5)

    hits = await store.search("zzzz nonexistent terminology", SourceType.GUIDELINE, 2, expand=False)

    assert [hit.chunk for hit in hits] == [1, 0]


def test_weighting_stops_a_lexical_only_hit_from_outranking_dense():
    """A keyword-only match may fill the tail; it may not displace a dense hit."""
    dense = ["d1", "d2", "d3"]
    lexical = ["only-bm25"]

    fused = reciprocal_rank_fusion([dense, lexical], weights=[1.0, 0.4])

    assert fused[:3] == dense
    assert fused[-1] == "only-bm25"


def test_weighting_still_promotes_a_chunk_both_systems_found():
    """The measured win: dense ranked it 11th, BM25 first. It should lead."""
    dense = [f"d{n}" for n in range(1, 11)] + ["buried"]
    lexical = ["buried"]

    fused = reciprocal_rank_fusion([dense, lexical], weights=[1.0, 0.4])

    assert fused[0] == "buried"
