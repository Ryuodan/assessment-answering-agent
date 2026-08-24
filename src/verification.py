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


def unsupported_clauses(
    answer: str, cited: list[Evidence], retrieved: list[Evidence] | None = None
) -> list[str]:
    """Clauses named in prose that nothing the drafter read actually covers.

    Support is judged against everything retrieved, not only what the drafter
    listed as used. Those are different things, and conflating them produced
    false alarms on correct answers: asked how often penetration testing runs,
    the drafter read both halves of a split policy section, wrote a correct
    sentence citing §3.1.20 from the second half, and listed only the first
    half in its sources. §3.1.20 exists and was on screen — the answer was
    right and the flag was wrong.

    What remains flagged is the case worth flagging: a clause identifier that
    appears in no retrieved chunk at all, which the drafter can only have
    invented. `evidence_for` then attaches the chunk that does support a
    clause, so the reader can check it rather than take the citation on trust.
    """
    universe = list(cited) + list(retrieved or [])
    if not universe:
        return mentioned_clauses(answer)
    return [
        clause
        for clause in mentioned_clauses(answer)
        if not any(supports_clause(item, clause) for item in universe)
    ]


def evidence_for(answer: str, cited: list[Evidence], retrieved: list[Evidence]) -> list[Evidence]:
    """`cited`, plus what else the answer demonstrably leaned on.

    A drafter under-reports its sources: it cites the chunk it started from and
    omits the sibling part it finished with. The reader then sees "1 supporting
    source" beneath an answer built on two. Both are recovered here — the other
    parts of a split unit the answer cited, and any retrieved chunk carrying a
    clause the prose names — so the evidence shown is the evidence used.
    """
    chosen = list(cited)
    keys = {(item.source_name, item.chunk) for item in chosen}

    def take(item: Evidence) -> None:
        key = (item.source_name, item.chunk)
        if key not in keys:
            keys.add(key)
            chosen.append(item)

    cited_units = {item.unit_id for item in cited if item.unit_id and item.parts > 1}
    for item in retrieved:
        if item.unit_id and item.unit_id in cited_units:
            take(item)

    for clause in mentioned_clauses(answer):
        if any(supports_clause(item, clause) for item in chosen):
            continue
        for item in retrieved:
            if supports_clause(item, clause):
                take(item)
                break

    return chosen


def incomplete_units(
    cited: list[Evidence],
    retrieved: list[Evidence] | None = None,
    *,
    completable_parts: int | None = None,
) -> list[str]:
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

    `completable_parts` mirrors the retriever's own expansion limit, and
    without it this check contradicts the retriever. Units past that limit are
    chapters rather than series and are deliberately never completed, so a
    partial view of one is the intended behaviour rather than a defect. Left
    unset the check flagged 13 of 42 answers for a gap the system had chosen —
    capping their confidence at the incomplete-list ceiling and pushing them
    into the review queue for nothing.
    """
    available: dict[str, set[int]] = {}
    for item in retrieved if retrieved is not None else cited:
        if item.unit_id:
            available.setdefault(item.unit_id, set()).add(item.part)

    incomplete = set()
    for item in cited:
        if not item.unit_id or item.parts <= 1:
            continue
        if completable_parts is not None and item.parts > completable_parts:
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
    completable_parts: int | None = None,
) -> tuple[float, bool, list[str]]:
    """Return adjusted confidence, whether review is needed, and the reasons why.

    Completeness combines both views — see `incomplete_units`. A model that
    reads four parts and cites one has seen the full list and is not flagged;
    one that cites a part whose siblings were never retrieved is.
    """
    reasons: list[str] = []

    missing = unsupported_clauses(answer, cited, retrieved)
    if missing:
        reasons.append("cites clauses not covered by its sources: " + ", ".join(missing))
        confidence = min(confidence, incomplete_cap)

    partial = incomplete_units(cited, retrieved, completable_parts=completable_parts)
    if partial:
        reasons.append("holds only part of a split source; the set may be incomplete")
        confidence = min(confidence, incomplete_cap)

    if not grounded:
        reasons.append("the reviewer did not find the answer grounded")

    needs_review = bool(reasons) or confidence <= review_threshold
    return confidence, needs_review, reasons


# ---------------------------------------------------------------------------
# Why the score came out where it did
# ---------------------------------------------------------------------------

# The checks above answer "is something demonstrably wrong with this answer".
# They say nothing when the answer is merely weak, which is the common case: a
# question flagged purely for landing under the threshold arrived with an empty
# reason list, so the interface showed a "needs review" chip and no explanation
# at all. A reviewer cannot act on a number. What they need is the cause in a
# sentence — was nothing found, was it found but not trusted, or was it pieced
# together from clauses that only touch the subject.


def explain_confidence(
    confidence: float,
    cited: list[Evidence],
    *,
    grounded: bool,
    review_threshold: float,
    verdict_reason: str = "",
) -> str:
    """One plain sentence on why the confidence is what it is, or "" when high.

    Written for the person filling in the questionnaire, not for whoever wrote
    the retriever: no thresholds, no clause arithmetic, no talk of chunks. It
    ends with the thing that reviewer should actually go and do.
    """
    if confidence > review_threshold and grounded:
        return ""

    sources = len(cited)
    detail = verdict_reason.strip().rstrip(".")

    if not sources:
        return (
            "Nothing in the knowledge base matched this question, so the answer is not "
            "backed by any of your documents. Treat it as unanswered and check with the "
            "team that owns this control."
        )

    if not grounded:
        because = f" The reviewer's note: {detail}." if detail else ""
        return (
            "A second model read the answer against the sources and could not trace every "
            f"statement in it back to them.{because} Verify each claim against the "
            f"{sources} cited source{'s' if sources > 1 else ''} before submitting."
        )

    if confidence <= 0.3:
        return (
            "The sources touch on this subject but none of them answers the question "
            "directly, so the answer is built from the closest material available. It may "
            "be that your documents genuinely do not cover this."
        )

    return (
        "No single clause states this outright, so the answer was inferred by combining "
        f"related material from {sources} source{'s' if sources > 1 else ''}. The reasoning "
        "is sound but worth a second pair of eyes."
    )