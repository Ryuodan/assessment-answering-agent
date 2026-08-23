"""Measuring retrieval on its own, separately from the answer written from it.

The judge in `eval/judge.py` reads the answer text and nothing else, so a low
score is unattributable: "the retriever never found the clause" and "the
drafter was given the clause and ignored it" produce the same number. That
blindness is not hypothetical. A change that dropped the guideline count in the
drafting prompt to zero on retried questions — a total retrieval failure —
moved the graded accuracy by less than one point, well inside the noise.

This module scores the retrieval instead, against `eval/retrieval_targets.json`:
the documents and clauses a human-verified reference says the answer comes
from. It runs the real nodes — the same planning, retrieval, reranking and
selection the graph performs — and asks two questions of each stage:

* did the material reach the *retriever*, and
* did it survive into the *prompt*?

The gap between those two is selection loss, and it is the failure mode the
generation eval hides most completely.

No LLM grades anything here except the query planner the pipeline itself uses,
so a pass is fast, cheap and deterministic enough to run on every change.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from src.config import PROJECT_ROOT, settings
from src.graph import nodes
from src.graph.state import merge_evidence
from src.models import Evidence, Question

logger = logging.getLogger(__name__)

DEFAULT_TARGETS = PROJECT_ROOT / "eval" / "retrieval_targets.json"


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    """What a correct retrieval for one question would have to find.

    `kind` decides whether recall means anything:

    * `sourced` — the answer comes from documents in the corpus. Scored.
    * `absence` — the expected answer is that nothing documents this. There is
      nothing to retrieve, so recall is undefined and the case is excluded
      rather than counted as a miss.
    * `hybrid`  — some material exists *and* something is documented as absent.
      The documents that do exist are scored; the absence is generation's
      problem, not retrieval's.
    """

    test_id: str
    category: str
    kind: str
    question: str
    documents: dict[str, list[str]] = field(default_factory=dict)

    @property
    def scorable(self) -> bool:
        return self.kind in ("sourced", "hybrid") and bool(self.documents)

    @property
    def clauses(self) -> list[tuple[str, str]]:
        return [(doc, clause) for doc, clauses in self.documents.items() for clause in clauses]


def load_targets(path: Path | str = DEFAULT_TARGETS, golden: list | None = None) -> list[Target]:
    """Read the target file, pairing each entry with its golden question."""
    from eval.dataset import load_golden_set

    cases = {case.test_id: case for case in (golden or load_golden_set())}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))

    targets = []
    for entry in payload:
        case = cases.get(entry["test_id"])
        if case is None:
            continue
        targets.append(Target(
            test_id=entry["test_id"],
            category=entry.get("category", case.category),
            kind=entry.get("kind", "sourced"),
            question=case.question,
            # `clauses_indexed` rather than `clauses`: a clause the corpus does
            # not contain cannot be retrieved, and asking for it would score a
            # perfect retriever as a failure.
            documents={
                doc["document"]: list(doc.get("clauses_indexed") or [])
                for doc in entry.get("documents", [])
            },
        ))
    return targets


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def finds_document(evidence: list[Evidence], document: str) -> int | None:
    """1-based rank of the first chunk from `document`, or None."""
    for rank, item in enumerate(evidence, start=1):
        if item.source_name == document:
            return rank
    return None


def finds_clause(evidence: list[Evidence], document: str, clause: str) -> bool:
    """Whether any chunk of `document` covers `clause`.

    Uses the same span arithmetic the citation checker does, so "retrieved the
    clause" means here exactly what it means everywhere else in the system.
    """
    return any(
        item.source_name == document and item.covers_clause(clause)
        for item in evidence
    )


# ---------------------------------------------------------------------------
# One question
# ---------------------------------------------------------------------------


@dataclass
class CaseResult:
    """How retrieval did on one question, at both stages."""

    test_id: str
    category: str
    kind: str
    scorable: bool

    queries: int = 0
    retrieved: int = 0
    prompt: int = 0

    documents_expected: int = 0
    documents_retrieved: int = 0
    documents_in_prompt: int = 0

    clauses_expected: int = 0
    clauses_retrieved: int = 0
    clauses_in_prompt: int = 0

    first_rank: int | None = None
    lost_documents: list[str] = field(default_factory=list)
    missed_documents: list[str] = field(default_factory=list)

    @property
    def document_recall(self) -> float | None:
        if not self.documents_expected:
            return None
        return self.documents_in_prompt / self.documents_expected

    @property
    def clause_recall(self) -> float | None:
        if not self.clauses_expected:
            return None
        return self.clauses_in_prompt / self.clauses_expected


async def measure_case(target: Target, plans: dict[str, list[str]] | None = None) -> CaseResult:
    """Run the real retrieval path for one question and score both stages.

    `plans` pins the expanded queries instead of asking the planner for them.
    The planner is an LLM, so it writes slightly different searches each run,
    and that alone moved document recall by several points between two passes
    of an unchanged system — enough to swamp the effect of whatever setting was
    being tested. Reusing one set of plans makes a comparison a comparison.
    """
    question = Question(id=target.test_id, text=target.question,
                        language="ar" if any("؀" <= c <= "ۿ" for c in target.question) else "en")

    state: dict = {"question": question, "language": question.language}
    cached = (plans or {}).get(target.test_id)
    if cached:
        state["search_queries"] = list(cached)
    else:
        state.update(await nodes.plan(state))
    retrieved = await nodes.retrieve(state)
    state["evidence"] = merge_evidence([], retrieved["evidence"])
    state["ranked"] = (await nodes.rerank_evidence(state))["ranked"]
    prompt = nodes._sources(state)

    result = CaseResult(
        test_id=target.test_id,
        category=target.category,
        kind=target.kind,
        scorable=target.scorable,
        queries=len(state.get("search_queries") or []),
        retrieved=len(state["evidence"]),
        prompt=len(prompt),
    )
    if not target.scorable:
        return result

    ranks = []
    for document, clauses in target.documents.items():
        result.documents_expected += 1
        rank = finds_document(prompt, document)
        if finds_document(state["evidence"], document) is not None:
            result.documents_retrieved += 1
            if rank is None:
                result.lost_documents.append(document)
        else:
            result.missed_documents.append(document)
        if rank is not None:
            result.documents_in_prompt += 1
            ranks.append(rank)

        for clause in clauses:
            result.clauses_expected += 1
            if finds_clause(state["evidence"], document, clause):
                result.clauses_retrieved += 1
            if finds_clause(prompt, document, clause):
                result.clauses_in_prompt += 1

    result.first_rank = min(ranks) if ranks else None
    return result


async def measure_all(
    targets: list[Target], concurrency: int = 4, plans: dict[str, list[str]] | None = None
) -> list[CaseResult]:
    """Score every question, bounded so the planner does not trip a rate limit."""
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def run(target: Target) -> CaseResult:
        async with semaphore:
            try:
                return await measure_case(target, plans)
            except Exception:  # noqa: BLE001 - one bad case must not lose the pass
                logger.exception("Retrieval measurement failed for %s", target.test_id)
                return CaseResult(target.test_id, target.category, target.kind, False)

    return list(await asyncio.gather(*(run(target) for target in targets)))


async def build_plans(targets: list[Target], concurrency: int = 4) -> dict[str, list[str]]:
    """Expand every question once, so a sweep can hold the queries constant."""
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def one(target: Target) -> tuple[str, list[str]]:
        question = Question(
            id=target.test_id, text=target.question,
            language="ar" if any("؀" <= c <= "ۿ" for c in target.question) else "en",
        )
        async with semaphore:
            try:
                planned = await nodes.plan({"question": question, "language": question.language})
                return target.test_id, list(planned.get("search_queries") or [target.question])
            except Exception:  # noqa: BLE001
                logger.exception("Planning failed for %s", target.test_id)
                return target.test_id, [target.question]

    return dict(await asyncio.gather(*(one(target) for target in targets)))


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def summarise(results: list[CaseResult]) -> dict:
    scored = [r for r in results if r.scorable]

    def ratio(hit: int, total: int) -> float:
        return round(100 * hit / total, 1) if total else 0.0

    documents_expected = sum(r.documents_expected for r in scored)
    documents_retrieved = sum(r.documents_retrieved for r in scored)
    documents_in_prompt = sum(r.documents_in_prompt for r in scored)
    clauses_expected = sum(r.clauses_expected for r in scored)
    clauses_retrieved = sum(r.clauses_retrieved for r in scored)
    clauses_in_prompt = sum(r.clauses_in_prompt for r in scored)

    ranked = [r.first_rank for r in scored if r.first_rank]
    perfect = sum(1 for r in scored if r.document_recall == 1.0)

    return {
        "cases": len(results),
        "scored": len(scored),
        "excluded_absence": sum(1 for r in results if not r.scorable),
        "document_recall_pct": ratio(documents_in_prompt, documents_expected),
        "document_recall_retrieved_pct": ratio(documents_retrieved, documents_expected),
        "clause_recall_pct": ratio(clauses_in_prompt, clauses_expected),
        "clause_recall_retrieved_pct": ratio(clauses_retrieved, clauses_expected),
        "selection_loss_documents": documents_retrieved - documents_in_prompt,
        "never_retrieved_documents": documents_expected - documents_retrieved,
        "documents_expected": documents_expected,
        "clauses_expected": clauses_expected,
        "cases_fully_covered": perfect,
        "cases_fully_covered_pct": ratio(perfect, len(scored)),
        "mean_first_rank": round(sum(ranked) / len(ranked), 2) if ranked else None,
        "mrr": round(sum(1 / r for r in ranked) / len(scored), 3) if scored else 0.0,
        "mean_retrieved": round(sum(r.retrieved for r in scored) / len(scored), 1) if scored else 0,
        "mean_in_prompt": round(sum(r.prompt for r in scored) / len(scored), 1) if scored else 0,
    }


def by_category(results: list[CaseResult]) -> dict[str, dict]:
    groups: dict[str, list[CaseResult]] = {}
    for result in results:
        if result.scorable:
            groups.setdefault(result.category, []).append(result)
    return {name: summarise(group) for name, group in sorted(groups.items())}


def format_report(summary: dict, categories: dict, results: list[CaseResult]) -> str:
    lines = [
        "",
        "RETRIEVAL",
        "=" * 78,
        f"  {summary['scored']} of {summary['cases']} cases scored "
        f"({summary['excluded_absence']} excluded: the expected answer is that nothing documents it)",
        "",
        f"  document recall, in the prompt : {summary['document_recall_pct']:5.1f}%   "
        f"({summary['documents_expected']} expected)",
        f"  document recall, retrieved     : {summary['document_recall_retrieved_pct']:5.1f}%",
        f"  clause recall,   in the prompt : {summary['clause_recall_pct']:5.1f}%   "
        f"({summary['clauses_expected']} expected)",
        f"  clause recall,   retrieved     : {summary['clause_recall_retrieved_pct']:5.1f}%",
        "",
        f"  cases with every source present: {summary['cases_fully_covered']}/{summary['scored']} "
        f"({summary['cases_fully_covered_pct']}%)",
        f"  mean rank of the first hit     : {summary['mean_first_rank']}",
        f"  MRR                            : {summary['mrr']}",
        f"  chunks retrieved / in prompt   : {summary['mean_retrieved']} / {summary['mean_in_prompt']}",
        "",
        "  where the expected documents ended up",
        "  " + "-" * 60,
        f"    reached the drafting prompt  : {summary['documents_expected'] - summary['selection_loss_documents'] - summary['never_retrieved_documents']:3d}",
        f"    retrieved, then cut          : {summary['selection_loss_documents']:3d}   <- selection loss",
        f"    never retrieved              : {summary['never_retrieved_documents']:3d}   <- retriever miss",
        "",
        "  by category",
        "  " + "-" * 60,
    ]
    for name, stats in categories.items():
        lines.append(
            f"    {name:26s} doc {stats['document_recall_pct']:5.1f}%   "
            f"clause {stats['clause_recall_pct']:5.1f}%   ({stats['scored']} cases)"
        )

    failures = [r for r in results if r.scorable and (r.lost_documents or r.missed_documents)]
    if failures:
        lines += ["", "  cases with a missing source", "  " + "-" * 60]
        for result in failures:
            for document in result.lost_documents:
                lines.append(f"    {result.test_id:8s} CUT       {document[:52]}")
            for document in result.missed_documents:
                lines.append(f"    {result.test_id:8s} NOT FOUND {document[:52]}")

    lines.append("")
    return "\n".join(lines)


def as_dict(label: str, results: list[CaseResult]) -> dict:
    """The whole pass, in a shape that can be written to a file and diffed."""
    return {
        "label": label,
        "configuration": {
            "top_k_guidelines": settings.top_k_guidelines,
            "top_k_prior_answers": settings.top_k_prior_answers,
            "query_expansion": settings.query_expansion,
            "max_search_queries": settings.max_search_queries,
            "hybrid_search": settings.hybrid_search,
            "reranker_enabled": settings.reranker_enabled,
            "max_evidence_chunks": settings.max_evidence_chunks,
            "max_prior_answer_chunks": settings.max_prior_answer_chunks,
            "query_agreement_weight": getattr(settings, "query_agreement_weight", None),
        },
        "summary": summarise(results),
        "categories": by_category(results),
        "cases": [
            {
                "test_id": r.test_id,
                "category": r.category,
                "kind": r.kind,
                "scorable": r.scorable,
                "queries": r.queries,
                "retrieved": r.retrieved,
                "prompt": r.prompt,
                "document_recall": r.document_recall,
                "clause_recall": r.clause_recall,
                "first_rank": r.first_rank,
                "lost_documents": r.lost_documents,
                "missed_documents": r.missed_documents,
            }
            for r in results
        ],
    }
