"""Embeddings client.

Vectors come from a self-hosted BGE-M3 service (multilingual, 1024-d) that
speaks the OpenAI embeddings protocol, so `OpenAIEmbeddings` is pointed at it
rather than a bespoke client being written.

Three non-obvious flags matter:

* `check_embedding_ctx_length=False` — stops the client from tokenising and
  splitting text locally with tiktoken. BGE-M3 takes up to 8192 tokens and
  truncates server-side, and tiktoken's cl100k vocabulary badly overestimates
  Arabic token counts, which would shred Arabic passages into fragments.
* `tiktoken_enabled=False` — sends plain strings instead of token-id arrays,
  which is what the BGE-M3 service expects.
* `encoding_format="float"` — the client defaults to `base64`, which the BGE-M3
  service rejects outright with a 422 validation error. It is passed through
  `model_kwargs` because it is not a declared field on `OpenAIEmbeddings`.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings
from pydantic import SecretStr

from src.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_embeddings() -> Embeddings:
    """Return the shared embeddings client."""
    logger.debug(
        "Creating embeddings client model=%s base_url=%s",
        settings.embedding_model,
        settings.embedding_base_url,
    )
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        base_url=settings.embedding_base_url,
        api_key=SecretStr(settings.embedding_api_key),
        request_timeout=settings.embedding_timeout,  # the client's own default is no timeout at all (TD-034)
        check_embedding_ctx_length=False,
        tiktoken_enabled=False,
        chunk_size=64,  # To fit API max http chunk size (no affect on RAG)
        model_kwargs={"encoding_format": "float"},
    )
