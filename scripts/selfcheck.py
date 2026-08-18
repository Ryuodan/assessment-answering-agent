"""Verify that the Step 1-4 edits actually landed.

Unit tests prove the new code is correct. They do not prove it is *connected* —
a chunker that nothing calls passes every test in this repo. This script checks
the wiring: that `add_guideline` really calls `chunk_document`, that the state
reducer is really attached, that `format_sources_block` really receives Evidence.

Run:  python -m scripts.selfcheck
Exit code is 0 only if every required check passes.
"""

from __future__ import annotations

import inspect
import sys
import typing

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))


def check(name: str, required: bool = True):
    """Decorator: run a check, catching import and attribute errors as failures."""

    def wrapper(function):
        try:
            outcome = function()
        except Exception as exc:  # noqa: BLE001 - a broken import is itself the finding
            record(FAIL if required else WARN, name, f"{type(exc).__name__}: {exc}")
            return function
        if outcome is True:
            record(PASS, name)
        else:
            record(FAIL if required else WARN, name, str(outcome))
        return function

    return wrapper


# --- Step 1: chunking ------------------------------------------------------


@check("step 1 - src/chunking.py exists and exports its API")
def _chunking_module():
    from src import chunking

    missing = [
        name
        for name in ("chunk_document", "parse_blocks", "build_units", "parent_clause", "strip_bidi")
        if not hasattr(chunking, name)
    ]
    return True if not missing else f"missing: {missing}"


@check("step 1 - add_guideline calls chunk_document")
def _add_guideline_wired():
    from src.knowledge import KnowledgeStore

    source = inspect.getsource(KnowledgeStore.add_guideline)
    if "chunk_document" not in source:
        return "add_guideline still uses the old splitter - the chunker is not connected"
    return True


@check("step 1 - the old character splitter is gone")
def _splitter_removed():
    from src import knowledge

    source = inspect.getsource(knowledge)
    leftovers = [
        name
        for name in ("RecursiveCharacterTextSplitter", "_SEPARATORS", "def _splitter")
        if name in source
    ]
    return True if not leftovers else f"still present in knowledge.py: {leftovers}"


@check("step 1 - chunk_size raised to at least 1800")
def _chunk_size():
    from src.config import settings

    if settings.chunk_size < 1800:
        return f"chunk_size={settings.chunk_size}; a 12-item series will split unnecessarily"
    return True


@check("step 1 - chunking survives a real series")
def _chunking_behaviour():
    from src.chunking import chunk_document

    doc = (
        "## 7.2 Alerts\n\nThe SOC shall alert on:\n\n"
        + "\n".join(f"7.2.{n} Condition number {n}." for n in range(1, 13))
    )
    chunks = chunk_document(doc, source_name="t.pdf", chunk_size=1800)
    joined = "\n".join(chunk.text for chunk in chunks)
    missing = [f"7.2.{n}" for n in range(1, 13) if f"7.2.{n}" not in joined]
    if missing:
        return f"lost {missing}"
    if not any(chunk.metadata.get("kind") == "series" for chunk in chunks):
        return "series not detected as a structural unit"
    return True


# --- Step 2: Evidence and expansion ---------------------------------------


@check("step 2 - Evidence carries locator metadata")
def _evidence_fields():
    from src.models import Evidence

    required = {
        "doc_id", "clause", "heading", "page", "chunk",
        "kind", "unit_id", "part", "parts",
    }
    missing = required - set(Evidence.model_fields)
    return True if not missing else f"missing fields: {sorted(missing)}"


@check("step 2 - Evidence exposes locator and is_fragment")
def _evidence_properties():
    from src.models import Evidence, SourceType

    item = Evidence(
        source_type=SourceType.GUIDELINE,
        source_name="f.pdf",
        snippet="x",
        doc_id="MDS-CS-STD-003",
        clause="7.2.1",
        parts=3,
    )
    if item.locator != "MDS-CS-STD-003 \u00a77.2.1":
        return f"locator returned {item.locator!r}"
    if item.is_fragment is not True:
        return "is_fragment did not detect a split unit"
    return True


@check("step 2 - KnowledgeStore has the expansion path")
def _expansion_exists():
    from src.knowledge import KnowledgeStore

    missing = [name for name in ("_expand_units", "_evidence") if not hasattr(KnowledgeStore, name)]
    if missing:
        return f"missing methods: {missing}"
    signature = inspect.signature(KnowledgeStore.search)
    if "expand" not in signature.parameters:
        return "search() has no `expand` parameter"
    return True


@check("step 2 - expansion budget is configured")
def _expansion_budget():
    from src.config import settings

    missing = [
        name for name in ("max_expanded_chars", "max_evidence_chunks") if not hasattr(settings, name)
    ]
    return True if not missing else f"missing settings: {missing}"


# --- Step 3: accumulation --------------------------------------------------


@check("step 3 - QuestionState.evidence has an accumulating reducer")
def _reducer_attached():
    from src.graph.state import QuestionState

    hints = typing.get_type_hints(QuestionState, include_extras=True)
    annotation = hints.get("evidence")
    metadata = getattr(annotation, "__metadata__", ())
    if not metadata:
        return "evidence is not Annotated - a retry will still discard round 1"
    names = [getattr(item, "__name__", repr(item)) for item in metadata]
    if not any("merge" in name for name in names):
        return f"unexpected reducer: {names}"
    return True


@check("step 3 - merge_evidence unions and de-duplicates")
def _reducer_behaviour():
    from src.graph.state import merge_evidence
    from src.models import Evidence, SourceType

    def make(chunk, score=0.5):
        return Evidence(
            source_type=SourceType.GUIDELINE,
            source_name="std.pdf",
            snippet=f"c{chunk}",
            chunk=chunk,
            score=score,
        )

    if len(merge_evidence([make(1)], [make(2)])) != 2:
        return "two distinct rounds did not union"
    if len(merge_evidence([make(1)], [make(1)])) != 1:
        return "duplicate chunk was not collapsed"
    if merge_evidence([make(1, 0.2)], [make(1, 0.9)])[0].score != 0.9:
        return "higher score did not win on a duplicate"
    return True


@check("step 3 - retrieve() no longer discards prior rounds")
def _retrieve_returns_delta():
    from src.graph import nodes

    source = inspect.getsource(nodes.retrieve)
    if "attempt" not in source:
        return "retrieve() does not track `attempt`; check the Step 3 edit landed"
    return True


@check("step 3 - max_answer_attempts raised to 3", required=False)
def _attempts():
    from src.config import settings

    value = getattr(settings, "max_answer_attempts", None)
    if value is None:
        return "setting not found"
    if value < 3:
        return f"max_answer_attempts={value}; accumulation makes a third attempt additive"
    return True


# --- Step 4: citations -----------------------------------------------------


@check("step 4 - format_sources_block renders locators")
def _sources_block():
    from src.models import Evidence, SourceType
    from src.prompts import format_sources_block

    block = format_sources_block(
        [
            Evidence(
                source_type=SourceType.GUIDELINE,
                source_name="f.pdf",
                snippet="body",
                doc_id="MDS-CS-STD-003",
                clause="7.2.1",
                part=2,
                parts=4,
            )
        ]
    )
    if "\u00a77.2.1" not in block:
        return "clause locator missing from the sources block"
    if "part 2 of 4" not in block:
        return "fragment marker missing; coverage-aware confidence will have no signal"
    return True


@check("step 4 - nodes passes Evidence objects to the prompt")
def _nodes_pass_evidence():
    from src.graph import nodes

    source = inspect.getsource(nodes)
    if "source_type.value" in source and "format_sources_block" in source:
        return "nodes still unpacks Evidence into tuples before formatting"
    return True


@check("step 4 - AnsweredQuestion carries citations")
def _citations_field():
    from src.models import AnsweredQuestion

    if "citations" not in AnsweredQuestion.model_fields:
        return "no citations field; clause locators will not reach the caller"
    return True


@check("step 4 - finalize populates citations")
def _finalize_citations():
    from src.graph import nodes

    source = inspect.getsource(nodes.finalize)
    if "citations" not in source:
        return "finalize() does not set citations"
    return True


# --- adjacent: DOCX and rate limits ----------------------------------------


@check("docx loader emits Markdown headings", required=False)
def _docx_loader():
    from src import documents

    source = inspect.getsource(documents._load_docx)
    if "Heading" not in source or "#" not in source:
        return "still emits bare paragraphs; DOCX will chunk without structure"
    return True


@check("step 0 - rate limits are retryable", required=False)
def _rate_limit_retry():
    from src import llm

    names = [getattr(item, "__name__", "") for item in llm._RETRYABLE]
    if not any("RateLimit" in name for name in names):
        return "RateLimitError not in _RETRYABLE; a 429 becomes an empty answer"
    return True


# --- report ----------------------------------------------------------------


def main() -> int:
    width = max(len(name) for _, name, _ in results)
    for status, name, detail in results:
        line = f"{status:4}  {name.ljust(width)}"
        if detail:
            line += f"  -> {detail}"
        print(line)

    failed = sum(1 for status, _, _ in results if status == FAIL)
    warned = sum(1 for status, _, _ in results if status == WARN)
    passed = len(results) - failed - warned
    print(f"\n{passed} passed, {failed} failed, {warned} warnings")
    if failed:
        print("\nA FAIL means the code is present but not connected, or an edit did not land.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())