"""The knowledge base: guidelines and previously answered assessments.

Both kinds of material live in a single persistent Chroma collection,
distinguished by a `source_type` metadata field. One collection rather than two
means one client, one embedding function and one search path; the retriever
simply issues a filtered query per type and asks for the mix it wants.

Previous answers are indexed one Q/A pair per document, with the question and
answer in the embedded text. Embedding the pair together means a new question
matches on the question wording, and the answer travels with it — which is the
whole point of keeping the history.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.config import settings
from src.embeddings import get_embeddings
from src.models import Evidence, ExtractedQAPair, SourceType

logger = logging.getLogger(__name__)

# Arabic uses the same paragraph and sentence structure as the defaults, plus
# the Arabic comma and full stop, which the default separators do not cover.
_SEPARATORS = ["\n\n", "\n", "۔", "。", ". ", "، ", ", ", " ", ""]


@lru_cache(maxsize=1)
def _splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=_SEPARATORS,
        keep_separator=True,
    )


class KnowledgeStore:
    """Persistent store of guidelines and prior answers."""

    def __init__(self) -> None:
        settings.ensure_directories()
        self._store = Chroma(
            collection_name=settings.collection_name,
            embedding_function=get_embeddings(),
            persist_directory=str(settings.chroma_dir),
        )

    # -- writing ------------------------------------------------------------

    def add_guideline(self, source_name: str, text: str) -> int:
        """Chunk and index a guideline document. Replaces any earlier upload of the same name."""
        chunks = _splitter().split_text(text)
        documents = [
            Document(
                page_content=chunk,
                metadata={
                    "source_type": SourceType.GUIDELINE.value,
                    "source_name": source_name,
                    "chunk": index,
                },
            )
            for index, chunk in enumerate(chunks)
        ]
        return self._replace_source(source_name, documents)

    def add_prior_answers(self, source_name: str, pairs: list[ExtractedQAPair]) -> int:
        """Index question/answer pairs from a completed assessment."""
        documents = [
            Document(
                page_content=f"Q: {pair.question}\nA: {pair.answer}",
                metadata={
                    "source_type": SourceType.PRIOR_ANSWER.value,
                    "source_name": source_name,
                    "chunk": index,
                    "question": pair.question,
                    "answer": pair.answer,
                    "section": pair.section,
                },
            )
            for index, pair in enumerate(pairs)
        ]
        return self._replace_source(source_name, documents)

    def _replace_source(self, source_name: str, documents: list[Document]) -> int:
        """Index `documents`, first removing anything previously stored under this name.

        Re-uploading a corrected version of a policy is routine, and without this
        the old text stays in the index and keeps being retrieved alongside the new.
        """
        self.delete_source(source_name)
        if not documents:
            return 0

        # Deterministic ids keep a retried upload idempotent even if it fails midway.
        ids = [f"{source_name}::{index}" for index in range(len(documents))]
        self._store.add_documents(documents, ids=ids)
        logger.info("Indexed %d chunks for '%s'", len(documents), source_name)
        return len(documents)

    def delete_source(self, source_name: str) -> None:
        """Remove every chunk belonging to one uploaded file."""
        self._store.delete(where={"source_name": source_name})

    def reset(self) -> None:
        """Drop the whole collection. Used by the UI's 'clear knowledge base' action."""
        self._store.reset_collection()
        logger.warning("Knowledge base cleared")

    # -- reading ------------------------------------------------------------

    async def search(self, query: str, source_type: SourceType, k: int) -> list[Evidence]:
        """Return the `k` closest chunks of one type, best first."""
        if k <= 0 or not query.strip():
            return []

        hits = await self._store.asimilarity_search_with_relevance_scores(
            query, k=k, filter={"source_type": source_type.value}
        )
        return [
            Evidence(
                source_type=source_type,
                source_name=document.metadata.get("source_name", "unknown"),
                snippet=document.page_content,
                score=round(score, 4),
            )
            for document, score in hits
        ]

    def stats(self) -> dict:
        """Counts per source type and the list of indexed file names, for the UI."""
        records = self._store.get(include=["metadatas"])
        metadatas = records.get("metadatas") or []

        sources: dict[str, dict] = {}
        counts = {SourceType.GUIDELINE.value: 0, SourceType.PRIOR_ANSWER.value: 0}

        for metadata in metadatas:
            source_type = metadata.get("source_type", "")
            source_name = metadata.get("source_name", "unknown")
            counts[source_type] = counts.get(source_type, 0) + 1
            entry = sources.setdefault(source_name, {"name": source_name, "source_type": source_type, "chunks": 0})
            entry["chunks"] += 1

        return {
            "total_chunks": len(metadatas),
            "guideline_chunks": counts.get(SourceType.GUIDELINE.value, 0),
            "prior_answer_chunks": counts.get(SourceType.PRIOR_ANSWER.value, 0),
            "sources": sorted(sources.values(), key=lambda source: source["name"]),
        }


@lru_cache(maxsize=1)
def get_store() -> KnowledgeStore:
    """Return the shared store. Chroma clients are expensive and not meant to be per-request."""
    return KnowledgeStore()
