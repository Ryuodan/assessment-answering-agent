"""Each remembered answer reaches the drafter as its own evidence (plan 027).

The memory files every answer it indexes itself under one name, "Answer memory",
at chunk 0 (`answer_memory._document`). Retrieval de-duplicated by name and
chunk, so of all the remembered answers a question found only one reached the
drafter, and a shared answer scoring higher hid the product's own. These tests
go through the real retrieval node and the real scoped store; only Chroma and
the embedding call are stood in for.
"""

from __future__ import annotations

import pytest

from src import answer_memory, knowledge
from src.config import settings
from src.graph import nodes
from src.graph.state import merge_evidence
from src.memory import Entry
from src.models import Evidence, Question, SourceType
from src.prompts import format_sources_block
from tests.conftest import FakeDocument, FakeVectorStore, bare_store

TEAM = settings.default_team
PRODUCT = "prod-availo"
QUERIES = ["Do you enforce MFA?", "multi-factor authentication for administrators"]


class Collection(FakeVectorStore):
    """One Chroma collection: its vector search honours the source-type filter, as Chroma's does.

    Each record says which of `QUERIES` find it and how well, so a test can say
    that one search found one answer and the other found another.
    """

    def __init__(self) -> None:
        super().__init__([])
        self.found: dict[str, dict[int, float]] = {}

    def similarity_search_by_vector_with_relevance_scores(self, embedding, k, filter=None, **kwargs):
        query = int(embedding[0])
        kind = (filter or {}).get("source_type")
        hits = [
            (FakeDocument(record["text"], record["metadata"]), self.found[record["id"]][query])
            for record in self.records
            if record["metadata"]["source_type"] == kind and query in self.found.get(record["id"], {})
        ]
        return sorted(hits, key=lambda hit: -hit[1])[:k]


@pytest.fixture
def collections(monkeypatch) -> dict[str, knowledge.KnowledgeStore]:
    """The shared knowledge base and one product's, however the code asks for them."""
    made: dict[str, knowledge.KnowledgeStore] = {}

    def get_store(team_id=None, *, product_id=""):
        if product_id not in made:
            store = bare_store(Collection())
            store.team_id, store.product_id = team_id or TEAM, product_id

            async def embed(query: str) -> list[float]:
                return [float(QUERIES.index(query))]

            store._embed_query = embed
            made[product_id] = store
        return made[product_id]

    monkeypatch.setattr("src.knowledge.get_store", get_store)
    return made


def remembered(entry_id: str, score: float, *, product_id: str = "", found_by: tuple[int, ...] = (0, 1)) -> str:
    """Index one answer exactly as the memory files it, found by the given searches."""
    entry = Entry(
        entry_id=entry_id,
        question=f"Question {entry_id}?",
        answer=f"Answer {entry_id}.",
        origin="approved",
        approved_by="reviewer@example.test",
        approved_on="2026-10-01",
        team_id=TEAM,
        product_id=product_id,
    )
    store = knowledge.get_store(TEAM, product_id=product_id)
    store.add_entry(entry_id, answer_memory._document(entry))
    store._store.found[entry_id] = {query: score for query in found_by}
    return entry_id


async def retrieved(product_id: str = "", earlier: list[Evidence] | None = None) -> list[Evidence]:
    """One retrieval round over both queries, merged into `earlier` as the graph merges it."""
    state = {
        "question": Question(id="q1", text=QUERIES[0]),
        "team_id": TEAM,
        "product_id": product_id,
        "search_queries": QUERIES,
    }
    found = await nodes.retrieve(state)
    return merge_evidence(earlier or [], found["evidence"])


@pytest.mark.asyncio
async def test_a_shared_answer_no_longer_hides_the_products_own(collections) -> None:
    """The reported case: the shared answer scored higher, and the product's was dropped."""
    own = remembered("mem-own", 0.71, product_id=PRODUCT)
    shared = remembered("mem-shared", 0.83)

    sources = nodes._sources({"evidence": await retrieved(PRODUCT)})

    assert {item.entry_id: item.product_id for item in sources} == {own: PRODUCT, shared: ""}
    block = format_sources_block(sources)
    assert block.count("PREVIOUS ANSWER, FOR THIS PRODUCT —") == 1
    assert block.count("PREVIOUS ANSWER —") == 1, "the shared one carries no mark"


@pytest.mark.asyncio
async def test_every_remembered_answer_found_reaches_the_drafter(collections) -> None:
    for entry_id, score in (("mem-a", 0.83), ("mem-b", 0.80), ("mem-c", 0.78)):
        remembered(entry_id, score)

    sources = nodes._sources({"evidence": await retrieved()})

    assert [item.entry_id for item in sources] == ["mem-a", "mem-b", "mem-c"], "each in its own place, best first"


@pytest.mark.asyncio
async def test_no_answer_is_credited_with_the_searches_that_found_another(collections) -> None:
    """Agreement counts the searches that returned *this* answer, not any remembered one."""
    remembered("mem-a", 0.80, found_by=(0,))
    remembered("mem-b", 0.75, found_by=(1,))
    remembered("mem-c", 0.70, found_by=(0, 1))

    evidence = await retrieved()

    assert {item.entry_id: item.query_hits for item in evidence} == {"mem-a": 1, "mem-b": 1, "mem-c": 2}


@pytest.mark.asyncio
async def test_the_same_answer_found_in_two_rounds_is_still_one_source(collections) -> None:
    remembered("mem-a", 0.80)

    again = await retrieved(earlier=await retrieved())

    assert [(item.entry_id, item.source_type, item.query_hits) for item in again] == [
        ("mem-a", SourceType.PRIOR_ANSWER, 4)
    ], "two searches in each of two rounds"
