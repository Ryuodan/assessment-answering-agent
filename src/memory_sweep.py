"""The disagreement sweep: what the arrival of a remembered answer means for the others.

Moved out of `src/answer_memory.py` unchanged (plan 022), which keeps `scan` and
`scan_pending` as thin wrappers, so every caller still goes through it.
"""

from __future__ import annotations

import asyncio

from src import answer_memory, memory
from src.memory import Entry, Finding
from src.logs import get_logger
from src.models import SourceType

logger = get_logger(__name__)


async def _same_question(question: str, candidates: list[Entry]) -> list[Entry]:
    """Which candidates ask the same thing. The model decides, not the number.

    Similarity gets these as far as "worth asking about" and no further: two
    questions about annual drills embed at 0.79 and are different controls, two
    about sub-processor DPAs embed at 0.81 and are one question. Nothing in the
    figure separates those.
    """
    if not candidates:
        return []
    from src.llm import structured_llm, tool_use_failed
    from src.schemas import SameQuestions
    from src.prompts import SAME_QUESTION_SYSTEM, SAME_QUESTION_USER

    listed = "\n".join(f"{n}. {candidate.question}" for n, candidate in enumerate(candidates, start=1))
    try:
        verdict = await structured_llm(SameQuestions, temperature=0.0).ainvoke(
            [
                ("system", SAME_QUESTION_SYSTEM),
                ("user", SAME_QUESTION_USER.format(question=question, candidates=listed)),
            ]
        )
    except Exception as error:  # noqa: BLE001 - re-raised unless it is the empty answer
        if not tool_use_failed(error):
            raise
        # The model wrote its answer instead of calling the tool, and the answer
        # it wrote was "[]". Treating that as "none of them" is not a guess: the
        # empty verdict is the common one here, since these candidates were
        # chosen for looking alike rather than for being alike.
        logger.warning("memory.same_question_unparsed", read_as="none")
        return []
    return [candidates[n - 1] for n in dict.fromkeys(verdict.same) if 1 <= n <= len(candidates)]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    length = (sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5)
    return dot / length if length else 0.0


async def _close_questions(question: str, candidates: list[Entry]) -> list[Entry]:
    """Candidates whose *question* embeds within `PROPOSE` of this one.

    Retrieval proposes the candidates and this re-scores them, because the two
    numbers are on different scales and only one of them is the one the
    threshold was measured on. The index embeds "Q: … A: …" as a single
    document, so a hit's score is a question-and-answer similarity: two
    identical questions with different answers come back at 0.76, and 0.80
    against that scale would mean almost nothing survives. `PROPOSE` was
    calibrated question against question, and that is what this compares.
    """
    if not candidates:
        return []
    from src.embeddings import get_embeddings

    vectors = await get_embeddings().aembed_documents(
        [question[:900]] + [candidate.question[:900] for candidate in candidates]
    )
    mine, theirs = vectors[0], vectors[1:]
    return [candidate for candidate, vector in zip(candidates, theirs) if _cosine(mine, vector) >= memory.PROPOSE]


async def scan(entry: Entry, *, k: int = 8) -> list[Finding]:
    """What the arrival of `entry` means for what we already remember.

    Three filters, cheapest first: the index proposes the neighbourhood, the
    embedding of the questions alone decides which are worth asking about, and a
    model says which of those are actually the same question.

    Applies what it finds: a supersession is marked, because the ordering is not
    a judgement call and asking a person to confirm every ordinary revision is
    how a queue becomes something nobody reads. A contradiction is raised
    instead, because nothing here can decide it.
    """
    from src.scoped_knowledge import own_store

    team = answer_memory._team(entry.team_id)
    # Its own memory only (plan 022): a product's answer that differs from a
    # shared one is that product's answer, not a disagreement.
    hits = await own_store(team, entry.product_id).search(entry.question, SourceType.PRIOR_ANSWER, k, expand=False)
    seen: dict[str, Entry] = {}
    for hit in hits:
        other = answer_memory.get(hit.entry_id, team)
        if other is None or other.entry_id == entry.entry_id or other.entry_id in seen:
            continue
        if not other.stands:
            continue  # already replaced; it is history, not a second opinion
        if entry.origin == "import" == other.origin and entry.from_file and entry.from_file == other.from_file:
            # One questionnaire, filled in by one person on one day. Two rows in
            # it that look alike are two related controls, or the extractor
            # reading one row twice -- not the organisation contradicting
            # itself, which is the only thing this is looking for.
            continue
        seen[other.entry_id] = other

    close = await _close_questions(entry.question, list(seen.values()))

    findings: list[Finding] = []
    for other in await _same_question(entry.question, close):
        finding = memory.compare(entry, other, same_question=True)
        if finding is None:
            continue
        findings.append(finding)
        if finding.kind == "supersedes":
            answer_memory.supersede(other.entry_id, by=entry.entry_id, because=finding.because, team_id=team)
        elif finding.kind == "superseded_by":
            answer_memory.supersede(entry.entry_id, by=other.entry_id, because=finding.because, team_id=team)
            # It arrived already out of date, which happens when an older
            # questionnaire is imported after a newer one. Stop: an entry that
            # no longer stands has no standing to replace or contradict a third.
            break
        else:
            answer_memory.raise_conflict(entry.entry_id, other.entry_id, finding.because, team_id=team)
    return findings


async def scan_pending(
    *,
    limit: int = 25,
    concurrency: int = 4,
    team_id: str | None = None,
) -> list[Finding]:
    """Compare everything that has arrived since the last scan.

    Runs after an import and after an approval rather than at answer time. By
    the time a questionnaire is being answered it is too late to be useful --
    whichever entry retrieval ranked first has already gone into a customer's
    file -- and the person filling in the form is not the person who can say
    which of two answers is our position.
    """
    waiting = answer_memory.pending(limit=limit, team_id=team_id)
    if not waiting:
        return []

    gate = asyncio.Semaphore(concurrency)

    async def one(entry: Entry) -> list[Finding]:
        async with gate:
            try:
                found = await scan(entry)
            except Exception:  # noqa: BLE001 - one bad entry must not stop the sweep
                logger.exception("memory.scan_failed", entry=entry.entry_id)
                return []
            answer_memory.mark_scanned(entry.entry_id, entry.team_id)
            return found

    found = await asyncio.gather(*(one(entry) for entry in waiting))
    return [finding for group in found for finding in group]
