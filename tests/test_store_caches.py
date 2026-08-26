"""The store's derived caches, and the writes that must invalidate them.

Caching the catalog took a search from 423 ms of bookkeeping to none, and took
a 16-way concurrent burst from 30.8 s to 7.8 s. The risk it introduces is
staleness: an upload that does not appear, or a deleted file that still does.
Every write path is exercised here for that reason.
"""

from __future__ import annotations

import pytest

from src.models import SourceType
from tests.conftest import FakeVectorStore, bare_store


@pytest.fixture
def store():
    """An empty store over a writable fake, so writes and reads share state."""
    return bare_store(FakeVectorStore([]))


def test_a_new_document_appears_immediately(store):
    store.add_guideline("first.pdf", "## 1 Scope\n\nRetention is 90 days.")
    assert store.documents_indexed() == ["first.pdf"]

    store.add_guideline("second.pdf", "## 1 Scope\n\nBackups run nightly.")
    assert store.documents_indexed() == ["first.pdf", "second.pdf"]


def test_counts_follow_a_new_document(store):
    before = store.counts_by_type().get(SourceType.GUIDELINE.value, 0)
    store.add_guideline("policy.pdf", "## 1 Scope\n\n" + "Detail. " * 200)
    after = store.counts_by_type().get(SourceType.GUIDELINE.value, 0)
    assert after > before


def test_a_deleted_document_disappears_immediately(store):
    store.add_guideline("gone.pdf", "## 1 Scope\n\nSomething.")
    assert "gone.pdf" in store.documents_indexed()

    store.delete_source("gone.pdf")
    assert "gone.pdf" not in store.documents_indexed()
    assert "gone.pdf" not in {s["name"] for s in store.stats()["sources"]}


def test_reset_empties_every_derived_view(store):
    store.add_guideline("policy.pdf", "## 1 Scope\n\nSomething.")
    store.stats()                      # warm every cache
    store.documents_indexed()
    store.text_search("something", SourceType.GUIDELINE, 5)

    store.reset()

    assert store.documents_indexed() == []
    assert store.stats()["total_chunks"] == 0
    assert store.text_search("something", SourceType.GUIDELINE, 5) == []


def test_re_uploading_replaces_rather_than_duplicates(store):
    """The whole point of `_replace_source`: a corrected policy must not be
    retrieved alongside the version it corrects."""
    store.add_guideline("policy.pdf", "## 1 Scope\n\nRetention is 30 days.")
    store.add_guideline("policy.pdf", "## 1 Scope\n\nRetention is 90 days.")

    hits = store.text_search("retention", SourceType.GUIDELINE, 20)
    joined = " ".join(hit.snippet for hit in hits)

    assert store.documents_indexed() == ["policy.pdf"]
    assert "90 days" in joined
    assert "30 days" not in joined, "the superseded text is still being retrieved"


def test_the_literal_matcher_sees_a_document_added_after_it_ran(store):
    """The chunk map is cached; a write after the first search must reach it."""
    store.add_guideline("one.pdf", "## 1 Scope\n\nFirewalls are reviewed.")
    assert store.text_search("firewall", SourceType.GUIDELINE, 5)
    assert not store.text_search("intrusion", SourceType.GUIDELINE, 5)

    store.add_guideline("two.pdf", "## 1 Scope\n\nIntrusion detection is enabled.")
    assert store.text_search("intrusion", SourceType.GUIDELINE, 5)


def test_caches_are_built_once_under_concurrency(store, monkeypatch):
    """Several threads arriving together must not each rebuild the collection."""
    import concurrent.futures as cf

    store.add_guideline("policy.pdf", "## 1 Scope\n\n" + "Access control. " * 50)
    store._reset_caches()

    builds = []
    original = store._store.get

    def counting(*args, **kwargs):
        builds.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(store._store, "get", counting)

    with cf.ThreadPoolExecutor(8) as pool:
        results = list(pool.map(
            lambda _: len(store.text_search("access", SourceType.GUIDELINE, 5)), range(8)))

    assert len(set(results)) == 1, "every thread must see the same corpus"
    assert len(builds) <= 2, f"the chunk map was fetched {len(builds)} times"
