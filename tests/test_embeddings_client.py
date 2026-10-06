"""The embedding client's limits (plan 017, TD-034). Builds the client; sends nothing."""

from __future__ import annotations

import pytest

from src import embeddings
from src.config import settings


@pytest.fixture
def fresh_client():
    embeddings.get_embeddings.cache_clear()
    yield
    embeddings.get_embeddings.cache_clear()


def test_every_embedding_request_has_a_timeout(fresh_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """Left to its default, the client waited for ever, and a stalled host held a run for 53 minutes."""
    monkeypatch.setattr(settings, "embedding_timeout", 42.0)
    client = embeddings.get_embeddings()
    assert client.request_timeout == 42.0
    assert client.client._client.timeout == 42.0
    assert client.async_client._client.timeout == 42.0
    assert client.max_retries == 2


def test_the_default_timeout_is_set() -> None:
    assert type(settings).model_fields["embedding_timeout"].default == 300.0


def test_a_host_that_never_answers_fails_the_request_instead_of_holding_it(
    fresh_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A local server that accepts the connection and never replies, as the embedding
    host did for 53 minutes during plan 014. With the timeout the request fails after
    its retries; before, it waited for ever."""
    import socket
    import threading
    import time

    import openai

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    held: list[socket.socket] = []
    stop = threading.Event()

    def accept_and_say_nothing() -> None:
        listener.settimeout(0.2)
        while not stop.is_set():
            try:
                held.append(listener.accept()[0])
            except OSError:
                continue

    threading.Thread(target=accept_and_say_nothing, daemon=True).start()
    monkeypatch.setattr(settings, "embedding_base_url", f"http://127.0.0.1:{listener.getsockname()[1]}/v1")
    monkeypatch.setattr(settings, "embedding_timeout", 0.5)
    try:
        started = time.monotonic()
        with pytest.raises(openai.APITimeoutError):
            embeddings.get_embeddings().embed_query("Is data encrypted at rest?")
        assert time.monotonic() - started < 15, "three attempts of half a second each, and the client's back-off"
        assert len(held) == 3, "the first attempt and two retries"
    finally:
        stop.set()
        for connection in held:
            connection.close()
        listener.close()
