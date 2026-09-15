"""The model's connections are closed while the event loop that opened them runs.

Left open, they were collected at interpreter shutdown, after the loop had
closed, and on Windows that crashed the process with an access violation: every
script that talked to the model -- the assistant evaluation included, whose exit
code is its verdict -- ended with exit code 139 whatever it had printed.
"""

from __future__ import annotations

import pytest

from src import llm
from src.config import settings


@pytest.fixture
def fresh_models(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "not-a-real-key")
    llm.chat_llm.cache_clear()
    llm._MADE.clear()
    yield
    llm.chat_llm.cache_clear()
    llm._MADE.clear()


def test_run_closes_every_model_it_made_before_the_loop_ends(fresh_models):
    async def talk():
        return [llm.chat_llm(temperature=0.0), llm.chat_llm(temperature=0.5)]

    models = llm.run(talk())

    assert all(model.async_client._client.is_closed() for model in models)
    assert llm._MADE == []


def test_a_model_asked_for_after_closing_is_a_new_one_with_open_connections(fresh_models):
    async def talk():
        return llm.chat_llm(temperature=0.0)

    closed = llm.run(talk())

    again = llm.chat_llm(temperature=0.0)
    assert again is not closed and not again.async_client._client.is_closed()


def test_the_embeddings_connections_are_closed_too(fresh_models, monkeypatch):
    from src import embeddings

    monkeypatch.setattr(settings, "embedding_api_key", "not-a-real-key")
    embeddings.get_embeddings.cache_clear()

    async def search():
        return embeddings.get_embeddings()

    client = llm.run(search())

    assert client.async_client._client.is_closed()
    assert embeddings.get_embeddings.cache_info().currsize == 0


def test_run_still_closes_when_the_work_fails(fresh_models):
    made = []

    async def fail():
        made.append(llm.chat_llm(temperature=0.0))
        raise RuntimeError("the work failed")

    with pytest.raises(RuntimeError, match="the work failed"):
        llm.run(fail())

    assert made[0].async_client._client.is_closed()


def test_run_returns_what_the_work_returned(fresh_models):
    async def work():
        return 42

    assert llm.run(work()) == 42
