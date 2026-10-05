"""The knowledge base: guidelines and previously answered assessments.

**One per team.** Each team's policies and remembered answers are a Chroma
collection of their own, and every search, upload and removal names the team it
is for. It was one collection for the whole organisation, so a team answering a
questionnaire was quoting another team's policies and another team's answers.
The collection that existed before the split keeps its name and belongs to the
default team, so nothing was re-embedded.

Both kinds of material live in a team's persistent Chroma collection,
distinguished by a `source_type` metadata field. One collection rather than two
means one client, one embedding function and one search path; the retriever
simply issues a filtered query per type and asks for the mix it wants.

Previous answers are indexed one Q/A pair per document, with the question and
answer in the embedded text. Embedding the pair together means a new question
matches on the question wording, and the answer travels with it — which is the
whole point of keeping the history.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import threading
from contextlib import contextmanager

from langchain_chroma import Chroma
from langchain_core.documents import Document

from src import answer_memory
from src.config import settings
from src.embeddings import get_embeddings
from src.lexical import LexicalIndex, parse_search_query, reciprocal_rank_fusion
from src.models import Evidence, ExtractedQAPair, SourceType
from src.chunking import chunk_document, fold_digits

logger = logging.getLogger(__name__)

_SQRT2 = 2.0**0.5


def cosine_from_relevance(relevance: float, space: str) -> float:
    """Recover the cosine similarity from LangChain's relevance figure.

    The number LangChain hands back is not the similarity it appears to be,
    and the discrepancy is large enough to mislead a reader badly. Chroma's
    `l2` space returns the *squared* euclidean distance, while LangChain's
    `_euclidean_relevance_score_fn` computes `1 - distance / sqrt(2)` on the
    assumption that the distance is an unsquared norm. For the unit-length
    vectors BGE-M3 produces, the squared distance is `2 - 2 * cos`, so what
    comes out is

        reported = 1 - (2 - 2 cos) / sqrt(2) = sqrt(2) * cos - (sqrt(2) - 1)

    — an affine squash of the cosine. Ranking is unaffected, because the
    transform is strictly increasing, and no code in this project ever
    compared a score against a fixed threshold. What it did affect was every
    human reading the number: a chunk matching at cosine 0.72 was displayed as
    0.60, which reads like a poor match rather than a good one. It also dips
    below zero past cosine 0.293, and `order_evidence` seeds its group maximum
    at 0.0, so a negative score would silently collapse into a tie.

    Only the `l2` case needs undoing. A collection created with `cosine` or
    `ip` is already reported as a similarity, and converting again would be a
    second bug on top of the first — hence the space is passed in rather than
    assumed.
    """
    if space != "l2":
        return relevance
    return 1.0 - (1.0 - relevance) * _SQRT2 / 2.0


def collection_for(team_id: str) -> str:
    """The Chroma collection a team's knowledge lives in.

    The default team keeps the collection that existed before teams had their
    own, so the corpus already indexed is still its corpus. Any other team gets
    a name derived from its id: readable where the id allows, and always within
    Chroma's rules (3-63 characters, letters, digits, dot, dash and underscore,
    starting and ending with a letter or digit), with a hash so two ids that
    tidy to the same letters cannot share a collection.
    """
    if team_id == settings.default_team:
        return settings.collection_name
    slug = re.sub(r"[^a-z0-9]+", "-", team_id.lower()).strip("-")[:24] or "team"
    digest = hashlib.sha256(team_id.encode("utf-8")).hexdigest()[:10]
    return f"{settings.collection_name[:20].rstrip('-_.')}-{slug}-{digest}"


class KnowledgeStore:
    """One team's persistent store of guidelines and prior answers."""

    # Declared on the class, not just assigned in `__init__`, so a store built
    # around a stubbed collection still resolves the metric instead of raising.
    _space: str | None = None
    team_id: str | None = None
    """Whose store this is. None, for a store a test built by hand, means the default team."""

    def __init__(self, team_id: str | None = None) -> None:
        settings.ensure_directories()
        self._reset_caches()
        self.team_id = team_id or settings.default_team
        self._store = Chroma(
            collection_name=collection_for(self.team_id),
            embedding_function=get_embeddings(),
            persist_directory=str(settings.chroma_dir),
        )

    def _reset_caches(self) -> None:
        """Everything derived from the collection's current contents.

        One method rather than four assignments in `__init__`, because tests
        build a store around a fake vector store without calling `__init__`,
        and every cache added here used to break them until it was copied into
        the fixture by hand.
        """
        self._lexical_cache: dict = {}
        self._chunk_cache: dict = {}
        self._catalog_cache: tuple[dict[str, int], dict[str, dict]] | None = None
        self._build_lock = threading.Lock()

    @contextmanager
    def _writing(self):
        """Clear the derived caches around a write -- before it, and after it too.

        Only before, a read that arrived while the write was in flight rebuilt
        the catalog from the collection as it was, and that stale copy was then
        kept. Embedding a long policy takes seconds, so anybody opening the
        knowledge base during an upload left the new document missing from it
        until the next upload or delete.
        """
        self._reset_caches()
        try:
            yield
        finally:
            self._reset_caches()

    # -- writing ------------------------------------------------------------

    def add_guideline(
        self,
        source_name: str,
        text: str,
        content_hash: str = "",
        authority: str = "ours",
    ) -> int:
        """Chunk and index a guideline document. Replaces any earlier upload of the same name.

        `authority` says whether this is something the organisation wrote and is
        bound by ("ours") or a law, regulation or external framework it is
        subject to ("external"). The drafter is told, because the two support
        different claims: our policy says what we do, and a regulation says what
        we are required to do -- which is not the same answer when we have not
        done it.
        """
        chunks = chunk_document(text, source_name=source_name, chunk_size=settings.chunk_size)
        documents = [
            Document(
                page_content=chunk.text,
                metadata={
                    "source_type": SourceType.GUIDELINE.value,
                    "source_name": source_name,
                    "content_hash": content_hash,
                    "authority": authority if authority in ("ours", "external") else "ours",
                    **chunk.metadata,
                },
            )
            for chunk in chunks
        ]
        return self._replace_source(source_name, documents)

    def add_prior_answers(self, source_name: str, pairs: list[ExtractedQAPair], content_hash: str = "") -> int:
        """Index question/answer pairs from a completed assessment.

        Each pair carries the id it is known by in the answer memory, which is
        built from the file name and the pair's position — the same string the
        Chroma document gets — so that a retrieved answer can be traced back to
        the row recording who approved it and what it replaced.
        """
        documents = [
            Document(
                page_content=f"Q: {pair.question}\nA: {pair.answer}",
                metadata={
                    "source_type": SourceType.PRIOR_ANSWER.value,
                    "source_name": source_name,
                    "content_hash": content_hash,
                    "chunk": index,
                    "entry_id": f"{source_name}::{index}",
                    "question": pair.question,
                    "answer": pair.answer,
                    "section": pair.section,
                },
            )
            for index, pair in enumerate(pairs)
        ]
        return self._replace_source(source_name, documents)

    def add_entry(self, entry_id: str, document: Document) -> None:
        """Index one answer-memory entry under its own id.

        Separate from `add_prior_answers` because that one replaces a whole
        file: an approved answer arrives alone and must not clear the source it
        joins.
        """
        with self._writing():
            self._store.add_documents([document], ids=[entry_id])

    def remove_entry(self, entry_id: str) -> None:
        """Take one entry back out of the index.

        By id *and* by metadata, because for most of the corpus those are not
        the same string. An entry this module indexed is stored under its own
        id; the six hundred and ninety-eight adopted from the bulk import are
        stored under `<source>::<chunk>` and carry the entry id in their
        metadata. Deleting only by id left those retrievable after somebody had
        forgotten them -- and re-adopted, row and all, the next time the process
        started and read the index.
        """
        with self._writing():
            self._store.delete(ids=[entry_id])
            self._store.delete(where={"entry_id": entry_id})

    def prior_answer_metadata(self) -> list[dict]:
        """The metadata of every indexed prior answer.

        For adopting answers indexed before the memory kept rows of its own;
        everything those rows need is already here.
        """
        found = self._store.get(where={"source_type": SourceType.PRIOR_ANSWER.value}, include=["metadatas"])
        return list(found.get("metadatas") or [])

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
        if not documents:
            return 0

        # Deterministic ids keep a retried upload idempotent even if it fails midway.
        ids = [f"{source_name}::{index}" for index in range(len(documents))]
        with self._writing():
            self._store.add_documents(documents, ids=ids)
        logger.info("Indexed %d chunks for '%s'", len(documents), source_name)
        return len(documents)

    def set_authority(self, source_names: list[str], authority: str) -> int:
        """Re-mark indexed documents as ours or external. Returns chunks changed.

        Metadata only: the text has not changed, so the vectors have not either,
        and re-embedding eighty documents to correct a label would cost an hour
        and several thousand remote calls for nothing.
        """
        if authority not in ("ours", "external"):
            raise ValueError("authority must be 'ours' or 'external'")
        if not source_names:
            return 0

        collection = self._store._collection  # noqa: SLF001 - langchain exposes no update
        changed = 0
        for name in source_names:
            found = collection.get(where={"source_name": name}, include=["metadatas"])
            ids = found.get("ids") or []
            if not ids:
                continue
            collection.update(
                ids=ids,
                metadatas=[{**meta, "authority": authority} for meta in found["metadatas"]],
            )
            changed += len(ids)
        self._reset_caches()
        return changed

    def delete_source(self, source_name: str) -> None:
        """Remove every chunk belonging to one uploaded file."""
        with self._writing():
            self._store.delete(where={"source_name": source_name})

    def delete_type(self, source_type: SourceType) -> None:
        """Remove every chunk of one kind, and nothing of the other."""
        with self._writing():
            self._store.delete(where={"source_type": source_type.value})

    def reset(self) -> None:
        """Drop the whole collection. Used by the UI's 'clear knowledge base' action."""
        with self._writing():
            self._store.reset_collection()
        logger.warning("Knowledge base cleared")

    # -- reading ------------------------------------------------------------

    @property
    def _distance_space(self) -> str:
        """The metric the persisted collection was created with.

        Read from the collection rather than assumed, so that re-creating it
        with `cosine` later changes the conversion instead of breaking it.
        """
        if self._space is None:
            try:
                configuration = self._store._collection.configuration or {}
                hnsw = configuration.get("hnsw") or configuration.get("spann") or {}
                self._space = hnsw.get("space", "l2")
            except Exception:  # noqa: BLE001 - an unreadable config must not fail a search
                logger.warning("Could not read the collection's distance metric; assuming l2")
                self._space = "l2"
            logger.debug("Collection distance metric: %s", self._space)
        return self._space

    def _evidence(
        self,
        document: Document,
        score: float,
        source_type: SourceType,
        *,
        similarity: float | None = None,
        query_hits: int = 1,
    ) -> Evidence:
        """Build one Evidence, converting the store's relevance figure to cosine.

        `score` is what the vector store reported. `similarity` overrides the
        conversion for chunks that no vector search scored — an expanded
        sibling inheriting its unit's score, or a lexical-only hit — because
        converting an already-converted number would compound the error the
        conversion exists to undo.
        """
        meta = document.metadata
        cosine = cosine_from_relevance(score, self._distance_space) if similarity is None else similarity
        return Evidence(
            source_type=source_type,
            source_name=meta.get("source_name", "unknown"),
            snippet=document.page_content,
            score=round(cosine, 4),
            raw_score=round(score, 4),
            query_hits=query_hits,
            authority=meta.get("authority", "ours"),
            doc_id=meta.get("doc_id", ""),
            clause=meta.get("clause", ""),
            clause_start=meta.get("clause_start", "") or meta.get("clause", ""),
            clause_end=meta.get("clause_end", ""),
            section_clause=meta.get("section_clause", ""),
            item_count=int(meta.get("item_count", 0)),
            heading=meta.get("heading", ""),
            page=int(meta.get("page", -1)),
            # Falls back to `page` so a chunk indexed before page ranges
            # existed reports a single page rather than an empty range.
            page_end=int(meta.get("page_end", meta.get("page", -1))),
            chunk=int(meta.get("chunk", -1)),
            kind=meta.get("kind", "prose"),
            unit_id=meta.get("unit_id", ""),
            part=int(meta.get("part", 1)),
            parts=int(meta.get("parts", 1)),
            questionnaire=meta.get("questionnaire", ""),
            answered_date=meta.get("answered_date", ""),
            entry_id=(answer_memory.entry_id_of(meta) if source_type is SourceType.PRIOR_ANSWER else ""),
        )

    def _still_standing(self, evidence: list[Evidence]) -> list[Evidence]:
        """Drop prior answers a later one has replaced.

        Only on the answering path. A person searching the corpus should still
        find a superseded answer -- "what did we tell them in 2023" is a real
        question, and the memory page is built to show exactly that -- but no
        answer being written today should be built on a position we have since
        changed.

        The vector stays in the index rather than being deleted, so this filter
        is the whole mechanism: cheap, reversible, and undone by restoring the
        entry rather than by re-embedding it.
        """
        try:
            replaced = answer_memory.superseded_ids(self.team_id)
        except Exception:  # noqa: BLE001 - retrieval must not fail on bookkeeping
            logger.exception("Could not read which memory entries were superseded")
            return evidence
        if not replaced:
            return evidence
        return [item for item in evidence if item.entry_id not in replaced]

    async def search(self, query: str, source_type: SourceType, k: int, *, expand: bool = True) -> list[Evidence]:
        """Return the `k` closest chunks of one type, best first.

        A hit inside a split table or clause series is expanded to the whole unit
        before returning. Retrieval ranks fragments, but the drafter must see the
        complete series or it will present a fragment as the whole set.
        """
        found = await self.search_types(query, [(source_type, k)], expand=expand)
        return found.get(source_type, [])

    async def _embed_query(self, query: str) -> list[float]:
        """The query as a vector, embedded once per call to `search_types`.

        A method rather than an inline call so a test can hold this seam: the
        fake vector store used throughout the suite intercepts Chroma, and
        moving the embedding out of Chroma and into this class would otherwise
        have made every retrieval test reach the network to run.
        """
        return await get_embeddings().aembed_query(query)

    async def search_types(
        self,
        query: str,
        wanted: list[tuple[SourceType, int]],
        *,
        expand: bool = True,
    ) -> dict[SourceType, list[Evidence]]:
        """Search several source types against a single embedding of `query`.

        Guidelines and prior answers live in one collection, told apart by a
        `source_type` filter, so asking for both used to send the same text to
        the embedding service twice and get the same 1024 numbers back. With
        query expansion that was two round trips per query and 50% of the
        embedding work in a run -- against the slowest, least reliable
        dependency in the system.

        The text is embedded once here and each source type becomes a local
        Chroma query against that vector. One query per type rather than one
        overall, because the types have different budgets (`TOP_K_GUIDELINES`
        against `TOP_K_PRIOR_ANSWERS`): a single unfiltered search would return
        the best `k` regardless of kind, which on a corpus that is almost all
        guidelines means prior answers never appear at all.
        """
        wanted = [(source_type, k) for source_type, k in wanted if k > 0]
        if not wanted or not query.strip():
            return {}

        vector = await self._embed_query(query)
        # The by-vector call returns raw distances -- lower is nearer -- while
        # the by-string call LangChain would otherwise use converts them to
        # relevance, higher is nearer. Applying the same conversion here keeps
        # the number `_evidence` receives identical to what it received before,
        # and `cosine_from_relevance` is calibrated against exactly that scale.
        to_relevance = self._store._select_relevance_score_fn()

        async def one(source_type: SourceType, k: int) -> list[Evidence]:
            # Over-fetch when a lexical pass will re-rank: fusion can only
            # promote a chunk that one of the two lists actually returned.
            dense_k = k * 3 if settings.hybrid_search else k
            hits = await asyncio.to_thread(
                self._store.similarity_search_by_vector_with_relevance_scores,
                vector,
                dense_k,
                {"source_type": source_type.value},
            )
            evidence = [self._evidence(document, to_relevance(distance), source_type) for document, distance in hits]
            if source_type is SourceType.PRIOR_ANSWER:
                evidence = self._still_standing(evidence)
            if settings.hybrid_search:
                evidence = self._fuse_with_lexical(query, evidence, source_type, k)
            evidence = evidence[:k]
            return self._expand_units(evidence) if expand else evidence

        found = await asyncio.gather(*(one(source_type, k) for source_type, k in wanted))
        return {source_type: hits for (source_type, _), hits in zip(wanted, found)}

    def lexical_search(self, query: str, source_type: SourceType, k: int) -> list[Evidence]:
        """Keyword (BM25) hits, best first — no embedding involved.

        Exposed for the search tool, where the two retrieval modes are offered
        side by side: a person checking whether a policy says "90 days" wants
        the literal string, and an embedding is the wrong instrument for that.
        Scored on the same 0-1 scale as a cosine so one result list can mix
        both, but the figure is a BM25 rank normalised to the best hit, not a
        similarity — `is_lexical` says which it is.
        """
        if k <= 0 or not query.strip():
            return []

        index, documents = self._lexical(source_type)
        if not len(index):
            return []

        keys = index.search(query, k)
        found: list[Evidence] = []
        for rank, key in enumerate(keys):
            record = documents.get(key)
            if record is None:
                continue
            text, metadata = record
            item = self._evidence(
                Document(page_content=text, metadata=metadata),
                0.0,
                source_type,
                similarity=round(1.0 - rank / max(len(keys), 1), 4),
            )
            item.is_lexical = True
            found.append(item)
        return found

    def text_search(self, query: str, source_type: SourceType, k: int) -> list[Evidence]:
        """Literal text search over one collection, with search-box notation.

        BM25 matches whole words, which is wrong for a person at a search box:
        typing "net" and being told the corpus says nothing about networks is
        an answer about the tokeniser, not about the policies. This matches
        substrings instead, and understands the notation people already expect:

            network access     every term must appear somewhere in the chunk
            "least privilege"  the quoted run must appear exactly, in order
            backup -cloud      the minus sign excludes

        Scored by how many times the terms occur, normalised to the best hit,
        so the figure is comparable within one result list and is never a
        similarity — `is_lexical` marks it as such.
        """
        if k <= 0:
            return []

        phrases, terms, excluded = parse_search_query(query)
        if not phrases and not terms:
            return []

        documents = self._chunks(source_type)
        scored: list[tuple[float, tuple, str, dict]] = []

        for key, (text, metadata) in documents.items():
            haystack = fold_digits(text).casefold()
            if any(bad in haystack for bad in excluded):
                continue
            wanted = phrases + terms
            if not all(term in haystack for term in wanted):
                continue
            hits = sum(haystack.count(term) for term in wanted)
            # A phrase is a stronger signal than a loose substring, and a hit in
            # a short chunk is worth more than one in a long one.
            score = (hits + 2 * sum(haystack.count(p) for p in phrases)) / (1 + len(haystack) / 4000)
            scored.append((score, key, text, metadata))

        scored.sort(key=lambda row: -row[0])
        best = scored[0][0] if scored else 1.0
        found = []
        for score, _key, text, metadata in scored[:k]:
            item = self._evidence(
                Document(page_content=text, metadata=metadata),
                0.0,
                source_type,
                similarity=round(score / best, 4) if best else 0.0,
            )
            item.is_lexical = True
            found.append(item)
        return found

    def _catalog(self) -> tuple[dict[str, int], dict[str, dict]]:
        """(chunks per source type, indexed file names), read once and cached.

        Both are wanted on every search -- one to skip an empty collection, one
        to fill the file filter -- and each was its own full scan of the
        collection's metadata. Measured on 2,698 chunks that was 216 ms and 207
        ms against a search that itself takes 45 ms, so nine tenths of a search
        was bookkeeping, and under concurrent load it dominated completely.
        """
        if self._catalog_cache is None:
            with self._build_lock:
                if self._catalog_cache is None:
                    records = self._store.get(include=["metadatas"])
                    counts: dict[str, int] = {}
                    sources: dict[str, dict] = {}
                    for metadata in records.get("metadatas") or []:
                        metadata = metadata or {}
                        key = metadata.get("source_type", "")
                        counts[key] = counts.get(key, 0) + 1
                        name = metadata.get("source_name") or "unknown"
                        entry = sources.setdefault(
                            name,
                            {
                                "name": name,
                                "source_type": key,
                                "chunks": 0,
                                # A document is one or the other; the first chunk
                                # settles it. Defaults to "ours" for anything
                                # indexed before the distinction existed.
                                "authority": metadata.get("authority", "ours"),
                            },
                        )
                        entry["chunks"] += 1
                    self._catalog_cache = (counts, sources)
        return self._catalog_cache

    def counts_by_type(self) -> dict[str, int]:
        """Chunks per source type, so a search can skip an empty collection."""
        return dict(self._catalog()[0])

    def documents_indexed(self) -> list[str]:
        """Every distinct file name in the store, sorted — for the search filter."""
        return sorted(name for name in self._catalog()[1] if name != "unknown")

    def _fuse_with_lexical(self, query: str, dense: list[Evidence], source_type: SourceType, k: int) -> list[Evidence]:
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
                by_key[key] = self._evidence(
                    Document(page_content=text, metadata=metadata),
                    0.0,
                    source_type,
                    similarity=0.0,  # never vector-scored; fusion ranks it by position
                )

        dense_ranking = [(item.source_name, item.chunk) for item in dense]
        lexical_ranking = [key for key in index.search(query, k) if key in by_key]
        fused = reciprocal_rank_fusion([dense_ranking, lexical_ranking], weights=[1.0, settings.lexical_weight])
        return [by_key[key] for key in fused if key in by_key]

    def _chunks(self, source_type: SourceType) -> dict:
        """Every chunk of one collection as key -> (text, metadata), cached.

        Split out from the BM25 index because the search tool's literal matcher
        needs only this map. Building a BM25 index to answer a substring query
        cost 511 ms per process and was never consulted.
        """
        cached = self._chunk_cache.get(source_type)
        if cached is not None:
            return cached

        with self._build_lock:
            cached = self._chunk_cache.get(source_type)
            if cached is not None:
                return cached
            records = self._store.get(where={"source_type": source_type.value}, include=["documents", "metadatas"])
            texts = records.get("documents") or []
            metadatas = records.get("metadatas") or []
            documents = {
                (meta.get("source_name", ""), int(meta.get("chunk", -1))): (text, meta)
                for text, meta in zip(texts, metadatas)
            }
            self._chunk_cache[source_type] = documents
            return documents

    def _lexical(self, source_type: SourceType) -> tuple[LexicalIndex, dict]:
        """The BM25 index for one collection, built once per process.

        Invalidated by `_replace_source` and `reset`, which are the only ways
        the collection's contents change. Built under a lock: several threads
        arriving together would each tokenise the whole collection, which is
        where a concurrent burst of searches spent its worst latency.
        """
        cached = self._lexical_cache.get(source_type)
        if cached is not None:
            return cached

        documents = self._chunks(source_type)
        with self._build_lock:
            cached = self._lexical_cache.get(source_type)
            if cached is not None:
                return cached
            keys = list(documents)
            built = (LexicalIndex(keys, [documents[key][0] for key in keys]), documents)
            self._lexical_cache[source_type] = built
            logger.debug("Built lexical index for %s over %d chunks", source_type.value, len(keys))
            return built

    def _expand_units(self, evidence: list[Evidence]) -> list[Evidence]:
        """Pull in the sibling parts of any split unit a hit landed in.

        Two limits, both learned from this corpus. Units past
        `max_expanded_parts` are left alone — see the setting for why. And the
        character budget is shared across the whole call rather than reset for
        each hit, because two hits inside the same unit used to authorise two
        full budgets and between them could return more text than either was
        allowed.
        """
        seen = {(item.source_name, item.chunk) for item in evidence}
        expanded: list[Evidence] = []
        budget = settings.max_expanded_chars

        for item in evidence:
            expanded.append(item)
            if not item.unit_id or item.parts <= 1:
                continue
            if item.parts > settings.max_expanded_parts:
                logger.debug(
                    "Not expanding %s unit %s: %d parts is a chapter, not a series",
                    item.source_name,
                    item.unit_id,
                    item.parts,
                )
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

            for text, meta in siblings:
                key = (meta.get("source_name"), int(meta.get("chunk", -1)))
                if key in seen:
                    continue
                if budget - len(text) < 0:
                    logger.debug("Expansion budget exhausted at unit %s", item.unit_id)
                    break
                budget -= len(text)
                seen.add(key)
                sibling = self._evidence(
                    Document(page_content=text, metadata=meta),
                    # Inherit the triggering hit's score so the completed unit
                    # ranks together rather than sinking to the bottom. The
                    # cosine is inherited directly: it has already been
                    # converted, and running it through again would deflate it
                    # a second time.
                    item.raw_score,
                    item.source_type,
                    similarity=item.score,
                    query_hits=item.query_hits,
                )
                expanded.append(sibling)

        return expanded

    def guideline_names(self) -> list[str]:
        """The indexed guideline file names, cheapest form, sorted.

        Used to tell the query planner what the corpus actually holds. It
        cannot ask for a policy it does not know exists, and on this corpus
        that is the dominant retrieval failure: a question about offboarding
        needs the third-party policy, the planner never writes a query naming
        third parties, and a document that ranks first at cosine 0.76 when
        asked for directly is never asked for at all.
        """
        records = self._store.get(where={"source_type": SourceType.GUIDELINE.value}, include=["metadatas"])
        return sorted(
            {
                metadata.get("source_name", "")
                for metadata in (records.get("metadatas") or [])
                if metadata.get("source_name")
            }
        )

    def stats(self) -> dict:
        """Counts per source type and the list of indexed file names, for the UI.

        Reads the cached catalog rather than scanning the collection again: the
        interface asks for this on every page load, and the scan measured 221 ms
        against 2,698 chunks.
        """
        counts, sources = self._catalog()
        return {
            "total_chunks": sum(counts.values()),
            "guideline_chunks": counts.get(SourceType.GUIDELINE.value, 0),
            "prior_answer_chunks": counts.get(SourceType.PRIOR_ANSWER.value, 0),
            # Documents only. Previous answers are part of the answer memory,
            # managed one answer at a time on a page of their own; listed here
            # they were a single row reading "Answer memory (698)" with a
            # remove button beside it that would have deleted every vector and
            # left 698 rows on the memory page pointing at nothing.
            "sources": sorted(
                (source for source in sources.values() if source["source_type"] != SourceType.PRIOR_ANSWER.value),
                key=lambda source: source["name"],
            ),
        }

    def source_type_of(self, source_name: str) -> str:
        """Which kind of source a name is indexed as, or "" when it is not indexed."""
        _counts, sources = self._catalog()
        return (sources.get(source_name) or {}).get("source_type", "")


_store_lock = threading.Lock()
_stores: dict[str, KnowledgeStore] = {}


def get_store(team_id: str | None = None) -> KnowledgeStore:
    """A team's store, built exactly once per team.

    Built under a lock. Construction is not safe to race: Chroma's process-wide
    client registry is not reentrant, and two threads constructing at once died
    with a bare `KeyError` on the persist directory. FastAPI runs sync endpoints
    in a threadpool, and the interface opens with two independent calls that
    both want the store, so this is the ordinary path rather than a rare one.

    `team_id` left out means the default team -- for scripts and the command
    line, which act for the team the system was set up for. Everything a person
    does through the interface names their own team.
    """
    team = team_id or settings.default_team
    with _store_lock:
        store = _stores.get(team)
        if store is None:
            store = _stores[team] = KnowledgeStore(team)
        return store


def _forget_stores() -> None:
    with _store_lock:
        _stores.clear()


# Callers reset the store between tests; keep the name they already use.
get_store.cache_clear = _forget_stores
