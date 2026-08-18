"""Shared fixtures.

The fakes here exist so the retrieval logic can be tested without Chroma, an
embedding model, or an API key. `FakeVectorStore` implements only the two
methods `KnowledgeStore` actually calls, and it is loaded from real
`chunk_document` output — so a test failure means the chunking/expansion
contract broke, not that a mock drifted from reality.
"""

from __future__ import annotations

import pytest

from src.chunking import chunk_document
from src.knowledge import KnowledgeStore
from src.models import SourceType

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

    def stage(self, *, chunk_indexes: list[int], score: float = 0.7) -> None:
        by_chunk = {record["metadata"]["chunk"]: record for record in self.records}
        self._staged = [
            (FakeDocument(by_chunk[i]["text"], by_chunk[i]["metadata"]), score) for i in chunk_indexes
        ]

    async def asimilarity_search_with_relevance_scores(self, query, k, filter=None):
        return self._staged[:k]

    def get(self, where=None, include=None):
        """Minimal Chroma `where` support: a top-level `$and` of equality clauses."""
        self.get_calls.append(where)
        clauses = where.get("$and", [where]) if where else []
        matched = [
            record
            for record in self.records
            if all(
                record["metadata"].get(key) == value
                for clause in clauses
                for key, value in clause.items()
            )
        ]
        return {
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
    store = object.__new__(KnowledgeStore)
    store._store = fake
    return store, fake


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