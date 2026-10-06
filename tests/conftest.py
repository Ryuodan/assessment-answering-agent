"""Shared fixtures.

The fakes here exist so the retrieval logic can be tested without Chroma, an
embedding model, or an API key. `FakeVectorStore` implements only the two
methods `KnowledgeStore` actually calls, and it is loaded from real
`chunk_document` output — so a test failure means the chunking/expansion
contract broke, not that a mock drifted from reality.
"""

from __future__ import annotations

import os
from pathlib import Path

from harness.arch import settings_fields

# Settings come from their declared defaults and nothing else (TD-011): no
# `.env`, and no shell variable that names a setting. Done before anything
# imports `src.config`, which builds the settings once, at import. The names are
# read from the syntax tree of `src/config.py`, so nothing of `src` is imported yet.
os.environ["ASSESSMENT_ANSWER_ENV_FILE"] = ""
_SETTING_NAMES = settings_fields(Path(__file__).resolve().parent.parent / "src" / "config.py")
for _name in [name for name in os.environ if name.lower() in _SETTING_NAMES]:
    del os.environ[_name]

# Before `src.config` is imported, which is where tracing is switched on and,
# for Phoenix, where LangChain is patched to emit spans. The fixture below can
# unset LangSmith's variables after the fact because LangChain reads them per
# call; instrumentation happens once, at import, and a developer with
# `PHOENIX_TRACING=true` in their `.env` would otherwise have the whole suite
# exporting fixtures to their collector.
os.environ["PHOENIX_TRACING"] = "false"

import pytest  # noqa: E402

from src import access_codes, answer_memory, credentials, store  # noqa: E402
from src.chunking import chunk_document  # noqa: E402
from src.config import PROJECT_ROOT, settings  # noqa: E402
from src.knowledge import KnowledgeStore  # noqa: E402
from src.models import SourceType  # noqa: E402


def paths_inside_project(config: object) -> list[str]:
    """Names of path settings that point at or below the project directory."""
    root = PROJECT_ROOT.resolve()
    return sorted(
        name
        for name, value in vars(config).items()
        if isinstance(value, Path) and (value.resolve() == root or root in value.resolve().parents)
    )


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Point everything the suite writes at a throwaway directory, per test.

    Autouse, and deliberately not opt-in. The database came first: any test
    reaching the API touches it, and one writing to the deployment's
    `data/app.db` would pollute a real history without failing.

    The upload directory was added after this fixture let eleven test fixtures
    -- `vendor.xlsx`, `isra - answered.xlsx` and friends -- accumulate in
    `data/uploads` beside a hundred real policy documents. Nothing failed;
    a later test simply found a file an earlier one had left, and passed for
    the wrong reason.

    The allow-list is pinned empty so the API stays in its local-user mode
    unless a test asks for gating; otherwise a developer's `.env` would decide
    whether the suite gets 200s or 401s.

    The reading strategy is pinned to the rules for the same reason, and it is
    the one that bites hardest. The application's default is `guarded`, which
    runs an agent against a real model -- so every test that opened a
    questionnaire was making a network call: four seconds each, billed, and
    **nondeterministic**, which is the one thing a test may not be. The
    strategies have their own tests, which ask for them by name, and
    `scripts/compare_detection.py` measures them for real.
    """
    monkeypatch.setattr(settings, "db_path", tmp_path / "app.db")
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "filled_dir", tmp_path / "filled")
    # The vector store came last and matters most: the answer memory writes to
    # the index when a reviewer approves an answer, so a test that approves one
    # would otherwise add it to the deployment's real corpus -- and embed it
    # against the real embedding host to do so. Pointed at the throwaway
    # directory, the worst case is an empty collection nobody reads.
    monkeypatch.setattr(settings, "chroma_dir", tmp_path / "chroma")
    monkeypatch.setattr(settings, "extracted_text_dir", tmp_path / "extracted")
    monkeypatch.setattr(settings, "allowed_emails", "")
    monkeypatch.setattr(settings, "admin_email", "")
    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "detection_strategy", "rules")
    # The organisation profile was read from data/organisation.json by every test
    # that drafted an answer or opened the preferences page (TD-023).
    monkeypatch.setattr(settings, "organisation_path", tmp_path / "organisation.json")
    unredirected = paths_inside_project(settings)
    if unredirected:
        pytest.fail(
            f"settings still pointing into the project during a test: {', '.join(unredirected)}\n"
            "  FIX: redirect each to tmp_path in `isolated_storage` (tests/conftest.py); tests never touch real data"
        )
    store.reset_connection()
    answer_memory.forget_sync()
    yield
    store.reset_connection()
    answer_memory.forget_sync()


@pytest.fixture(autouse=True)
def no_console(monkeypatch):
    """Generated access codes reach no real terminal, and none outlives its test (TD-029).

    `identity.bootstrap` runs in many tests; without this each would write a code
    to the developer's console and leave it in memory for the next test.
    """
    shown: list[str] = []
    monkeypatch.setattr(access_codes, "_to_console", lambda text: shown.append(text) or True)
    monkeypatch.setattr(access_codes, "_waiting", {})
    return shown


@pytest.fixture(autouse=True)
def cheap_scrypt(monkeypatch):
    """Hash at a fraction of the production cost, for the suite only.

    scrypt is deliberately slow, and the tests sign in constantly — at the real
    parameters the suite takes over two minutes instead of twenty-five seconds,
    which is a tax on every change to anything. Each hash stores the parameters
    it was made with, so a cheap hash still verifies correctly and the tests
    exercise exactly the same code path.

    The one thing this must not do is hide a change to the real defaults, so
    `test_credentials.py` asserts those separately.
    """
    monkeypatch.setattr(credentials, "SCRYPT_N", 2**8)


@pytest.fixture(autouse=True, scope="session")
def _no_tracing_in_tests():
    """Never emit a trace from the test suite.

    Tracing is configured at import of `src.config`, so a deployment with
    `LANGSMITH_TRACING=true` in its `.env` would have every test that touches a
    chain post runs to the shared project -- polluting it with fixtures, and
    paying a network round trip per test. The live-call tests in `test_live.py`
    are the ones that would actually send, and they are exactly the ones whose
    traces would be least useful.
    """
    saved = {name: os.environ.pop(name, None) for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2")}
    # Phoenix is handled at the top of this file, before `src.config` is
    # imported: by the time a fixture runs, its instrumentation would already
    # have been installed.
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


@pytest.fixture(autouse=True)
def dense_only_retrieval():
    """Pin the lexical pass off, whatever the deployment's .env says.

    `FakeVectorStore` returns whatever a test staged regardless of the query, so
    fusing a real BM25 ranking over it would silently reorder results the test
    is asserting on. Hybrid search has its own tests, which opt back in.
    """
    original = settings.hybrid_search
    settings.hybrid_search = False
    yield
    settings.hybrid_search = original


def bare_store(fake) -> KnowledgeStore:
    """A KnowledgeStore over a fake vector store, without touching Chroma.

    Mirrors `__init__` rather than only setting `_store`, so a new instance
    attribute does not break every test that uses a fake.
    """
    store = object.__new__(KnowledgeStore)
    store._store = fake

    # The store embeds the query itself now, so the fake has to answer for the
    # embedding service too or every retrieval test would need the network.
    store.embedded = []

    async def _embed_query(query: str) -> list[float]:
        store.embedded.append(query)
        return [0.1, 0.2, 0.3]

    store._embed_query = _embed_query
    # The real initialiser's cache setup, so a cache added later cannot quietly
    # break every test that uses a fake.
    store._reset_caches()
    return store


RLM = "\u200f"


class FakeDocument:
    """Duck-typed stand-in for langchain_core.documents.Document."""

    def __init__(self, page_content: str, metadata: dict):
        self.page_content = page_content
        self.metadata = metadata


class FakeVectorStore:
    """In-memory store holding real chunk output.

    `asimilarity_search_with_relevance_scores` returns whichever chunks were
    explicitly staged via `stage()`, so a test can simulate "retrieval found
    only part 3 of 4" precisely.
    """

    def __init__(self, records: list[dict]):
        self.records = records
        self._staged: list[tuple[FakeDocument, float]] = []
        self.get_calls: list[dict] = []
        self.searched_vectors: list[list[float]] = []

    def stage(self, *, chunk_indexes: list[int], score: float = 0.7) -> None:
        by_chunk = {record["metadata"]["chunk"]: record for record in self.records}
        self._staged = [(FakeDocument(by_chunk[i]["text"], by_chunk[i]["metadata"]), score) for i in chunk_indexes]

    async def asimilarity_search_with_relevance_scores(self, query, k, filter=None):
        return self._staged[:k]

    def _select_relevance_score_fn(self):
        """Identity: `stage()` already speaks in relevance, not distance.

        Chroma returns raw distances from the by-vector call and LangChain
        converts them; staging relevance directly and converting by identity
        keeps every test that says `score=0.7` meaning the same thing it did
        before the store started embedding for itself.
        """
        return lambda score: score

    def similarity_search_by_vector_with_relevance_scores(self, embedding, k, filter=None, **kwargs):
        self.searched_vectors.append(list(embedding))
        return self._staged[:k]

    def add_documents(self, documents, ids=None):
        """Chroma's write path, so the ingestion routes can be exercised."""
        for index, document in enumerate(documents):
            self.records.append(
                {
                    "text": document.page_content,
                    "metadata": dict(document.metadata),
                    "id": (ids or [])[index] if ids and index < len(ids) else "",
                }
            )
        return ids or []

    def reset_collection(self):
        self.records = []

    def delete(self, where=None, ids=None):
        """By id or by metadata filter — Chroma accepts either, and both are used.

        The answer memory deletes one entry by its id; everything else deletes a
        whole source by name.
        """
        if ids is not None:
            self.records = [r for r in self.records if r.get("id") not in set(ids)]
            return
        clauses = where.get("$and", [where]) if where else []
        self.records = [
            record
            for record in self.records
            if not all(record["metadata"].get(key) == value for clause in clauses for key, value in clause.items())
        ]

    def get(self, where=None, include=None):
        """Minimal Chroma `where` support: a top-level `$and` of equality clauses."""
        self.get_calls.append(where)
        clauses = where.get("$and", [where]) if where else []
        matched = [
            record
            for record in self.records
            if all(record["metadata"].get(key) == value for clause in clauses for key, value in clause.items())
        ]
        return {
            "ids": [record.get("id", "") for record in matched],
            "documents": [record["text"] for record in matched],
            "metadatas": [record["metadata"] for record in matched],
        }


def build_store(text: str, *, source_name: str, chunk_size: int) -> tuple[KnowledgeStore, FakeVectorStore]:
    """Chunk `text` for real, load it into a fake vector store, and wrap it."""
    records = [
        {
            "text": chunk.text,
            "metadata": {
                "source_type": SourceType.GUIDELINE.value,
                "source_name": source_name,
                **chunk.metadata,
            },
        }
        for chunk in chunk_document(text, source_name=source_name, chunk_size=chunk_size)
    ]
    fake = FakeVectorStore(records)
    return bare_store(fake), fake


SERIES_DOC = """# MDS-CS-STD-003 Secure Configuration and Hardening Standard

## 7 Monitoring

### 7.2 SOC alert conditions

The Security Operations Centre shall generate alerts for the following conditions:

7.2.1 Failed authentication attempts exceeding five within fifteen minutes for any single account.
7.2.2 Successful authentication from a geography not previously observed within ninety days.
7.2.3 Privileged account creation, modification or deletion outside an approved change window.
7.2.4 Disabling or reconfiguration of endpoint protection agents on any managed asset.
7.2.5 Egress of more than two hundred data subject records to an external destination.
7.2.6 Modification of audit logging configuration on any in-scope system.
7.2.7 Execution of a script or binary not present in the approved software inventory.
7.2.8 Access to the cardholder data environment from an unmanaged endpoint.
7.2.9 Any change to firewall rules affecting internet-facing services.
7.2.10 Detection of a credential matching a known-compromised credential set.
7.2.11 Backup job failure on a Tier 1 system for two consecutive scheduled runs.
7.2.12 Certificate expiry within fourteen days for any public-facing service.

### 7.4 Remediation windows

| Severity | Internet-facing | Internal | Emergency change |
| --- | --- | --- | --- |
| Critical | 24 hours | 72 hours | Permitted with CISO approval |
| High | 7 days | 14 days | Permitted with CISO approval |
| Medium | 30 days | 60 days | Not permitted |
| Low | 90 days | 180 days | Not permitted |

## 8 Cryptography

Keys shall be generated using approved algorithms. The RSA modulus floor is 3072 bits.
"""


ARABIC_DOC = f"""# MDS-CS-STD-003 معيار التهيئة الآمنة والتحصين

## ٧ المراقبة

### ٧٫٢ شروط التنبيه في مركز العمليات

يجب على مركز عمليات الأمن السيبراني إنشاء تنبيهات للشروط التالية:

{RLM}٧.٢.١ محاولات مصادقة فاشلة تتجاوز خمس محاولات خلال خمس عشرة دقيقة لأي حساب.
{RLM}٧.٢.٢ مصادقة ناجحة من موقع جغرافي لم يُلاحظ سابقًا لذلك الحساب خلال تسعين يومًا.
{RLM}٧.٢.٣ إنشاء أو تعديل أو حذف حساب ذي امتيازات خارج نافذة تغيير معتمدة.
{RLM}٧.٢.٤ تعطيل أو إعادة تهيئة وكلاء حماية الأجهزة الطرفية.
{RLM}٧.٢.٥ تصدير أكثر من مئتي سجل لأصحاب البيانات إلى وجهة خارجية.
"""


@pytest.fixture
def series_doc() -> str:
    return SERIES_DOC


@pytest.fixture
def arabic_doc() -> str:
    return ARABIC_DOC


@pytest.fixture
def expansion_uncapped(monkeypatch):
    """Lift the parts cap for tests that exercise expansion itself.

    The series fixture splits into seven parts at `chunk_size=400` — a 2.8 KB
    unit, which is nothing like the 100-part chapters the production cap
    exists to stop. Capping is covered by its own tests.
    """
    from src.config import settings

    monkeypatch.setattr(settings, "max_expanded_parts", 99)


@pytest.fixture
def memory_index(monkeypatch):
    """An answer memory whose index is a fake, for the tests that write to it.

    Approving an answer indexes it, and indexing means embedding: without this
    the write is silently swallowed by `index_entry` and the test proves the
    row was written and nothing about the vector beside it.
    """
    fake = FakeVectorStore([])
    index = bare_store(fake)
    monkeypatch.setattr("src.knowledge.get_store", lambda team_id=None: index)
    return fake
