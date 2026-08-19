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

from src.config import settings
from src.embeddings import get_embeddings
from src.lexical import LexicalIndex, reciprocal_rank_fusion
from src.models import Evidence, ExtractedQAPair, SourceType
from src.chunking import chunk_document

logger = logging.getLogger(__name__)



class KnowledgeStore:
    """Persistent store of guidelines and prior answers."""

    def __init__(self) -> None:
        settings.ensure_directories()
        self._lexical_cache: dict = {}
        self._store = Chroma(
            collection_name=settings.collection_name,
            embedding_function=get_embeddings(),
            persist_directory=str(settings.chroma_dir),
        )

    # -- writing ------------------------------------------------------------

    def add_guideline(self, source_name: str, text: str, content_hash: str = "") -> int:
        """Chunk and index a guideline document. Replaces any earlier upload of the same name."""
        chunks = chunk_document(text, source_name=source_name, chunk_size=settings.chunk_size)
        documents = [
            Document(
                page_content=chunk.text,
                metadata={
                    "source_type": SourceType.GUIDELINE.value,
                    "source_name": source_name,
                    "content_hash": content_hash,
                    **chunk.metadata,
                },
            )
            for chunk in chunks
        ]
        return self._replace_source(source_name, documents)

    def add_prior_answers(self, source_name: str, pairs: list[ExtractedQAPair], content_hash: str = "") -> int:
        """Index question/answer pairs from a completed assessment."""
        documents = [
            Document(
                page_content=f"Q: {pair.question}\nA: {pair.answer}",
                metadata={
                    "source_type": SourceType.PRIOR_ANSWER.value,
                    "source_name": source_name,
                    "content_hash": content_hash,
                    "chunk": index,
                    "question": pair.question,
                    "answer": pair.answer,
                    "section": pair.section,
                },
            )
            for index, pair in enumerate(pairs)
        ]
        return self._replace_source(source_name, documents)

    def source_with_hash(self, content_hash: str, *, excluding: str = "") -> str | None:
        """Name of an already-indexed file with identical content, if any.

        Policy corpora arrive with the same document under two names — "Policy
        .pdf" and "Policy(1).pdf" — and indexing both doubles every hit from
        that document, which the evaluator flagged as avoidable retrieval
        ambiguity.
        """
        if not content_hash:
            return None

        records = self._store.get(where={"content_hash": content_hash}, include=["metadatas"])
        for metadata in records.get("metadatas") or []:
            name = metadata.get("source_name", "")
            if name and name != excluding:
                return name
        return None

    def _replace_source(self, source_name: str, documents: list[Document]) -> int:
        """Index `documents`, first removing anything previously stored under this name.

        Re-uploading a corrected version of a policy is routine, and without this
        the old text stays in the index and keeps being retrieved alongside the new.
        """
        self.delete_source(source_name)
        self._lexical_cache.clear()
        if not documents:
            return 0

        # Deterministic ids keep a retried upload idempotent even if it fails midway.
        ids = [f"{source_name}::{index}" for index in range(len(documents))]
        self._store.add_documents(documents, ids=ids)
        logger.info("Indexed %d chunks for '%s'", len(documents), source_name)
        return len(documents)

    def delete_source(self, source_name: str) -> None:
        """Remove every chunk belonging to one uploaded file."""
        self._lexical_cache.clear()
        self._store.delete(where={"source_name": source_name})

    def reset(self) -> None:
        """Drop the whole collection. Used by the UI's 'clear knowledge base' action."""
        self._lexical_cache.clear()
        self._store.reset_collection()
        logger.warning("Knowledge base cleared")

    # -- reading ------------------------------------------------------------

    def _evidence(self, document: Document, score: float, source_type: SourceType) -> Evidence:
        meta = document.metadata
        return Evidence(
            source_type=source_type,
            source_name=meta.get("source_name", "unknown"),
            snippet=document.page_content,
            score=round(score, 4),
            doc_id=meta.get("doc_id", ""),
            clause=meta.get("clause", ""),
            clause_start=meta.get("clause_start", "") or meta.get("clause", ""),
            clause_end=meta.get("clause_end", ""),
            section_clause=meta.get("section_clause", ""),
            item_count=int(meta.get("item_count", 0)),
            heading=meta.get("heading", ""),
            page=int(meta.get("page", -1)),
            chunk=int(meta.get("chunk", -1)),
            kind=meta.get("kind", "prose"),
            unit_id=meta.get("unit_id", ""),
            part=int(meta.get("part", 1)),
            parts=int(meta.get("parts", 1)),
            questionnaire=meta.get("questionnaire", ""),
            answered_date=meta.get("answered_date", ""),
        )

    async def search(
        self, query: str, source_type: SourceType, k: int, *, expand: bool = True
    ) -> list[Evidence]:
        """Return the `k` closest chunks of one type, best first.

        A hit inside a split table or clause series is expanded to the whole unit
        before returning. Retrieval ranks fragments, but the drafter must see the
        complete series or it will present a fragment as the whole set.
        """
        if k <= 0 or not query.strip():
            return []

        # Over-fetch when a lexical pass will re-rank: fusion can only promote a
        # chunk that one of the two lists actually returned.
        dense_k = k * 3 if settings.hybrid_search else k
        hits = await self._store.asimilarity_search_with_relevance_scores(
            query, k=dense_k, filter={"source_type": source_type.value}
        )
        evidence = [self._evidence(document, score, source_type) for document, score in hits]

        if settings.hybrid_search:
            evidence = self._fuse_with_lexical(query, evidence, source_type, k)
        evidence = evidence[:k]

        return self._expand_units(evidence) if expand else evidence

    def _fuse_with_lexical(
        self, query: str, dense: list[Evidence], source_type: SourceType, k: int
    ) -> list[Evidence]:
        """Re-rank dense hits against a BM25 pass over the same collection."""
        index, documents = self._lexical(source_type)
        if not len(index):
            return dense

        by_key = {(item.source_name, item.chunk): item for item in dense}
        # A lexical hit the dense pass never returned still has to become
        # Evidence, and the text and metadata for that come from the index.
        for key in index.search(query, k):
            if key not in by_key and key in documents:
                text, metadata = documents[key]
                by_key[key] = self._evidence(Document(page_content=text, metadata=metadata), 0.0, source_type)

        dense_ranking = [(item.source_name, item.chunk) for item in dense]
        lexical_ranking = [key for key in index.search(query, k) if key in by_key]
        fused = reciprocal_rank_fusion(
            [dense_ranking, lexical_ranking], weights=[1.0, settings.lexical_weight]
        )
        return [by_key[key] for key in fused if key in by_key]

    def _lexical(self, source_type: SourceType) -> tuple[LexicalIndex, dict]:
        """The BM25 index for one collection, built once per process.

        Invalidated by `_replace_source` and `reset`, which are the only ways
        the collection's contents change.
        """
        cached = self._lexical_cache.get(source_type)
        if cached is not None:
            return cached

        records = self._store.get(
            where={"source_type": source_type.value}, include=["documents", "metadatas"]
        )
        texts = records.get("documents") or []
        metadatas = records.get("metadatas") or []

        keys = [(meta.get("source_name", ""), int(meta.get("chunk", -1))) for meta in metadatas]
        documents = {key: (text, meta) for key, text, meta in zip(keys, texts, metadatas)}

        built = (LexicalIndex(keys, texts), documents)
        self._lexical_cache[source_type] = built
        logger.debug("Built lexical index for %s over %d chunks", source_type.value, len(keys))
        return built

    def _expand_units(self, evidence: list[Evidence]) -> list[Evidence]:
        """Pull in the sibling parts of any split unit a hit landed in."""
        seen = {(item.source_name, item.chunk) for item in evidence}
        expanded: list[Evidence] = []

        for item in evidence:
            expanded.append(item)
            if not item.unit_id or item.parts <= 1:
                continue

            records = self._store.get(
                where={
                    "$and": [
                        {"source_name": item.source_name},
                        {"unit_id": item.unit_id},
                    ]
                },
                include=["documents", "metadatas"],
            )
            siblings = sorted(
                zip(records.get("documents") or [], records.get("metadatas") or []),
                key=lambda pair: int(pair[1].get("part", 1)),
            )

            budget = settings.max_expanded_chars
            for text, meta in siblings:
                key = (meta.get("source_name"), int(meta.get("chunk", -1)))
                if key in seen:
                    continue
                if budget - len(text) < 0:
                    logger.debug("Expansion budget exhausted for unit %s", item.unit_id)
                    break
                budget -= len(text)
                seen.add(key)
                sibling = self._evidence(
                    Document(page_content=text, metadata=meta),
                    # Inherit the triggering hit's score so the completed unit
                    # ranks together rather than sinking to the bottom.
                    item.score,
                    item.source_type,
                )
                expanded.append(sibling)

        return expanded

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
