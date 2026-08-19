"""Checks applied to a drafted answer before it is returned.

Two failure modes motivated this module, both observed in evaluation runs:

1. **Unsupported precision.** The drafter writes "\u00a75.5" in prose while the
   evidence it cited spans \u00a75.1-5.4. A wrong answer carrying a precise
   citation is more dangerous than a vague one, because the citation is what a
   reviewer checks first and it makes the answer look verified.

2. **Silent truncation.** A list answer covering 5 of 12 items ships at 0.85
   with `needs_review: false`, because confidence measured how well the sources
   supported what was written, never whether anything was missing.

Both checks are mechanical. They read retrieval metadata rather than asking the
model to grade itself, so they hold even when the model is confidently wrong.
"""

from __future__ import annotations

import re

from src.models import Evidence

# "§7.2.1", "§ 7.2", and the same with an en-dash range: "§5.1–5.6".
_CLAUSE_MENTION = re.compile(r"\u00a7\s*(\d+(?:\.\d+){0,7})(?:\s*[\u2013\u2014-]\s*(\d+(?:\.\d+){0,7}))?")


def mentioned_clauses(answer: str) -> list[str]:
    """Clause identifiers the answer text claims, in order of first appearance."""
    found: list[str] = []
    for match in _CLAUSE_MENTION.finditer(answer):
        for group in match.groups():
            if group and group not in found:
                found.append(group)
    return found


def _appears_in(clause: str, text: str) -> bool:
    """Whether `text` names this exact clause.

    Bounded on both sides so "5.2.1" does not match inside "15.2.1" or
    "5.2.10", while a trailing sentence period still counts.
    """
    return re.search(rf"(?<![\d.]){re.escape(clause)}(?!\.?\d)", text) is not None


def supports_clause(evidence: Evidence, clause: str) -> bool:
    """Whether one retrieved chunk backs a clause the answer names.

    Two ways to back it, and both are needed. The `clause_start`..`clause_end`
    range covers a clause that is one of a numbered run the chunk holds. The
    snippet body covers the far more common case: a chunk labelled "5.1.7 Data
    Deletion" whose bullets are numbered 5.2.1 to 5.2.4. Checking the label
    alone reported every one of those as uncovered, which is how this check
    reached a 95% false-positive rate and pinned confidence to its floor.
    """
    return evidence.covers_clause(clause) or _appears_in(clause, evidence.snippet)


def unsupported_clauses(answer: str, cited: list[Evidence]) -> list[str]:
    """Clauses named in prose that no cited chunk actually covers.

    A non-empty result means the answer points somewhere its own evidence does
    not reach. That is worth flagging even when the answer is otherwise right,
    because the reader cannot tell the two cases apart.
    """
    if not cited:
        return mentioned_clauses(answer)
    return [
        clause
        for clause in mentioned_clauses(answer)
        if not any(supports_clause(item, clause) for item in cited)
    ]


def incomplete_units(cited: list[Evidence], retrieved: list[Evidence] | None = None) -> list[str]:
    """Units the answer relied on without the whole series being available.

    Retrieval splits a long table or clause run into parts that share a
    `unit_id`. Building an answer on part 2 of 4 means the series was
    demonstrably not seen whole, whatever the drafter believed.

    Both arguments matter, and using either alone gets it wrong:

    * Judged on `cited` alone, an answer that read all four parts and
      referenced one is flagged for a gap that was never there.
    * Judged on `retrieved` alone, any partially-retrieved unit anywhere in the
      evidence flags the answer — including units it never used. On a corpus of
      eighty documents that fired on 34 of 42 answers, which is not a review
      queue, it is a permanent warning light.

    So: flag a unit the answer *cited* whose parts are *not all present* in
    what was retrieved.
    """
    available: dict[str, set[int]] = {}
    for item in retrieved if retrieved is not None else cited:
        if item.unit_id:
            available.setdefault(item.unit_id, set()).add(item.part)

    incomplete = set()
    for item in cited:
        if not item.unit_id or item.parts <= 1:
            continue
        if len(available.get(item.unit_id, set())) < item.parts:
            incomplete.add(item.unit_id)
    return sorted(incomplete)


def assess(
    answer: str,
    cited: list[Evidence],
    confidence: float,
    *,
    retrieved: list[Evidence] | None = None,
    grounded: bool,
    review_threshold: float,
    incomplete_cap: float,
) -> tuple[float, bool, list[str]]:
    """Return adjusted confidence, whether review is needed, and the reasons why.

    Completeness combines both views — see `incomplete_units`. A model that
    reads four parts and cites one has seen the full list and is not flagged;
    one that cites a part whose siblings were never retrieved is.
    """
    reasons: list[str] = []

    missing = unsupported_clauses(answer, cited)
    if missing:
        reasons.append("cites clauses not covered by its sources: " + ", ".join(missing))
        confidence = min(confidence, incomplete_cap)

    partial = incomplete_units(cited, retrieved)
    if partial:
        reasons.append("holds only part of a split source; the set may be incomplete")
        confidence = min(confidence, incomplete_cap)

    if not grounded:
        reasons.append("the reviewer did not find the answer grounded")

    needs_review = bool(reasons) or confidence <= review_threshold
    return confidence, needs_review, reasons    