"""The answer memory as something a person can manage.

`src.memory` decides what two remembered answers mean to each other. This keeps
them: the row with an owner, a date and a history, the vector that makes one
retrievable, and the operations a reviewer needs -- add, correct, remove,
supersede, and resolve a disagreement between two of them.

Three things feed it, and they are the same shape once they arrive:

* **Import.** A previously answered questionnaire, indexed as question/answer
  pairs. Undated, because the files record no date, and unattributed.
* **Approval.** A reviewer read an answer this system drafted, put their name to
  it, and it went into a customer's file. That is the strongest thing we know
  about what we say, and it is where the memory grows from here.
* **By hand.** Somebody types in what we say about something, because they know
  it and no questionnaire in the corpus happens to ask.

**Every team has its own.** An entry belongs to the team that imported,
approved or wrote it, is retrieved only for that team's questionnaires, and can
be read, corrected or forgotten only by that team -- the same boundary as the
knowledge base it is indexed beside. It used to be one memory for the whole
organisation, so one team's answers were quoted in another team's files.

Two stores, deliberately. Chroma holds the text and its vector and answers
"what did we say about encryption"; SQLite holds who approved it, when, what it
replaced and what it disagrees with. Neither is the other's index: the entry id
is the same string in both, so a row and its vector are one thing addressed two
ways, and a delete that touched only one of them would leave an answer that is
either unretrievable or unaccountable.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass

from langchain_core.documents import Document

from src import memory, store
from src.config import settings
from src.memory import Entry, Finding
from src.models import SourceType

logger = logging.getLogger(__name__)

ORIGINS = ("import", "approved", "manual")

MEMORY_SOURCE = "Answer memory"
"""The name every entry this module indexes is filed under.

One bucket rather than one per questionnaire, and it is the *index's* name for
them, not their provenance -- which questionnaire an answer was given in stays
on the entry, in `from_file`, and is what the memory page shows.

The distinction earns its keep the first time somebody corrects an imported
answer. Re-indexing it under the questionnaire it came from would put a new
one-chunk "source" into the knowledge base's file list for a file nobody
uploaded, and a `remove` there would quietly delete a memory entry. Under one
name the list stays a list of files, plus this.
"""

_synced: set[tuple[str, str]] = set()


def _team(team_id: str | None) -> str:
    """The team an operation is for. Scripts and tests may leave it to the default."""
    return team_id or settings.default_team


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def _entry(row) -> Entry:
    return Entry(
        entry_id=row["entry_id"],
        question=row["question"],
        answer=row["answer"],
        approved_by=row["approved_by"],
        approved_on=row["approved_on"],
        from_file=row["from_file"],
        section=row["section"],
        origin=row["origin"],
        superseded_by=row["superseded_by"],
        team_id=row["team_id"],
    )


@dataclass(frozen=True)
class Conflict:
    """Two remembered answers that disagree, and nobody has said which is right."""

    entry_id: str
    other_id: str
    because: str
    raised_at: str
    resolved_at: str = ""
    resolved_by: str = ""
    resolution: str = ""

    @property
    def open(self) -> bool:
        return not self.resolved_at


def _conflict(row) -> Conflict:
    return Conflict(
        entry_id=row["entry_id"], other_id=row["other_id"], because=row["because"],
        raised_at=row["raised_at"], resolved_at=row["resolved_at"],
        resolved_by=row["resolved_by"], resolution=row["resolution"],
    )


def new_id() -> str:
    return f"mem-{uuid.uuid4().hex[:12]}"


def entry_id_of(metadata: dict) -> str:
    """The entry id of an indexed prior answer, including the older ones.

    Entries indexed before this module existed carry no `entry_id`, but they do
    carry the two fields their Chroma id was built from, so the id is
    recoverable rather than lost. Without this the 698 imported answers would
    all have to be re-embedded to become manageable.
    """
    stated = str(metadata.get("entry_id") or "")
    if stated:
        return stated
    name = metadata.get("source_name", "")
    chunk = metadata.get("chunk", -1)
    return f"{name}::{chunk}" if name else ""


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def get(entry_id: str, team_id: str | None = None) -> Entry | None:
    row = store.connect().execute(
        "SELECT * FROM memory_entries WHERE team_id = ? AND entry_id = ?",
        (_team(team_id), entry_id),
    ).fetchone()
    return _entry(row) if row else None


def _matching(query: str, standing: bool | None, origin: str, team_id: str) -> tuple[str, list]:
    """The WHERE clause the list and its total both have to agree on."""
    where, params = ["team_id = ?"], [team_id]
    if query.strip():
        where.append("(question LIKE ? OR answer LIKE ?)")
        params += [f"%{query.strip()}%"] * 2
    if standing is True:
        where.append("superseded_by = ''")
    elif standing is False:
        where.append("superseded_by != ''")
    if origin:
        where.append("origin = ?")
        params.append(origin)
    return " AND ".join(where), params


def entries(
    *,
    query: str = "",
    standing: bool | None = None,
    origin: str = "",
    limit: int = 100,
    offset: int = 0,
    team_id: str | None = None,
) -> list[Entry]:
    """One team's remembered answers, newest first.

    `standing` filters out the superseded ones — the default is everything,
    because the page that lists these is exactly where somebody goes to see what
    replaced what.
    """
    team = _team(team_id)
    ensure_synced(team)
    clause, params = _matching(query, standing, origin, team)
    rows = store.connect().execute(
        f"SELECT * FROM memory_entries WHERE {clause} "
        "ORDER BY updated_at DESC, rowid DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return [_entry(row) for row in rows]


def count(
    *, query: str = "", standing: bool | None = None, origin: str = "", team_id: str | None = None,
) -> int:
    """How many entries match, for a page that has to say "showing 100 of 812"."""
    team = _team(team_id)
    ensure_synced(team)
    clause, params = _matching(query, standing, origin, team)
    return store.connect().execute(
        f"SELECT COUNT(*) FROM memory_entries WHERE {clause}", params
    ).fetchone()[0]


def ids_from_batch(batch_id: str, team_id: str | None = None) -> set[str]:
    """Which of a questionnaire's answers are in the memory, in one query.

    The interface asks this per batch rather than per question: a card that
    cannot say whether approving it taught anything is a button whose second
    effect is invisible, and a hundred and eighty-three lookups to find out is
    not a page load.
    """
    prefix = f"approved::{batch_id}::"
    rows = store.connect().execute(
        # Every approved entry, filtered here rather than by a LIKE pattern: an
        # id is built from a question id, which is the questionnaire's own text
        # and can hold anything, including the two characters LIKE treats as
        # wildcards.
        "SELECT entry_id FROM memory_entries WHERE team_id = ? AND origin = 'approved'",
        (_team(team_id),),
    ).fetchall()
    return {row["entry_id"] for row in rows if row["entry_id"].startswith(prefix)}


def superseded_ids(team_id: str | None = None) -> set[str]:
    """Entries that must not be retrieved. Usually empty, and cheap when it is.

    Only those whose replacement still exists. An answer replaced by nothing is
    an answer that stopped being retrieved for no reason anybody could see.
    """
    team = _team(team_id)
    rows = store.connect().execute(
        "SELECT entry_id FROM memory_entries WHERE team_id = ? AND superseded_by != '' "
        "AND superseded_by IN (SELECT entry_id FROM memory_entries WHERE team_id = ?)",
        (team, team),
    ).fetchall()
    return {row["entry_id"] for row in rows}


def conflicts(*, open_only: bool = True, team_id: str | None = None) -> list[Conflict]:
    clause = " AND resolved_at = ''" if open_only else ""
    rows = store.connect().execute(
        f"SELECT * FROM memory_conflicts WHERE team_id = ?{clause} ORDER BY raised_at DESC",
        (_team(team_id),),
    ).fetchall()
    return [_conflict(row) for row in rows]


def stats(team_id: str | None = None) -> dict:
    team = _team(team_id)
    ensure_synced(team)
    conn = store.connect()
    total = conn.execute(
        "SELECT COUNT(*) FROM memory_entries WHERE team_id = ?", (team,)
    ).fetchone()[0]
    superseded = conn.execute(
        "SELECT COUNT(*) FROM memory_entries WHERE team_id = ? AND superseded_by != ''", (team,)
    ).fetchone()[0]
    by_origin = {
        row["origin"]: row["n"]
        for row in conn.execute(
            "SELECT origin, COUNT(*) AS n FROM memory_entries WHERE team_id = ? GROUP BY origin",
            (team,),
        ).fetchall()
    }
    return {
        "entries": total,
        "standing": total - superseded,
        "superseded": superseded,
        "by_origin": by_origin,
        "open_conflicts": conn.execute(
            "SELECT COUNT(*) FROM memory_conflicts WHERE team_id = ? AND resolved_at = ''", (team,)
        ).fetchone()[0],
        "unscanned": conn.execute(
            "SELECT COUNT(*) FROM memory_entries WHERE team_id = ? AND scanned_at = ''", (team,)
        ).fetchone()[0],
    }


def pending(*, limit: int = 25, team_id: str | None = None) -> list[Entry]:
    """Entries not yet compared against what their team already remembers.

    Every team's by default, oldest first: the background sweep is one process
    for everyone, and each entry it takes is compared only within its own team.
    A person pressing the button asks for their own team's, and is shown only
    those -- the findings name the other entry's question.
    """
    if team_id:
        rows = store.connect().execute(
            "SELECT * FROM memory_entries WHERE team_id = ? AND scanned_at = '' "
            "ORDER BY created_at LIMIT ?",
            (team_id, limit),
        ).fetchall()
    else:
        rows = store.connect().execute(
            "SELECT * FROM memory_entries WHERE scanned_at = '' "
            "ORDER BY created_at LIMIT ?",
            (limit,),
        ).fetchall()
    return [_entry(row) for row in rows]


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def record(
    question: str,
    answer: str,
    *,
    entry_id: str = "",
    section: str = "",
    from_file: str = "",
    origin: str = "manual",
    approved_by: str = "",
    approved_on: str = "",
    team_id: str = "",
    index: bool = True,
    scanned: bool = False,
) -> Entry:
    """Remember one answer. Writes the row, then indexes it for retrieval.

    `scanned` marks it as already compared with everything else, which the
    import path uses for the file it is importing: the pairs in one completed
    questionnaire were written together by one person and are not each other's
    contradictions.
    """
    question, answer = question.strip(), answer.strip()
    if not question or not answer:
        raise ValueError("A remembered answer needs both a question and an answer.")
    if origin not in ORIGINS:
        raise ValueError(f"origin must be one of {ORIGINS}")

    entry_id = entry_id or new_id()
    team = _team(team_id)
    now = store.utcnow()
    if origin != "import" and not approved_on:
        approved_on = now

    store.connect().execute(
        "INSERT OR REPLACE INTO memory_entries "
        "(entry_id, team_id, question, answer, section, from_file, origin, "
        " approved_by, approved_on, created_at, updated_at, scanned_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (entry_id, team, question, answer, section, from_file, origin,
         approved_by, approved_on, now, now, now if scanned else ""),
    )
    store.connect().commit()

    if index:
        index_entry(get(entry_id, team))
    return get(entry_id, team)


def adopt_file(source_name: str, pairs, *, team_id: str = "") -> list[Entry]:
    """Give every pair just indexed from one questionnaire a row here.

    The pairs are already in the index — `add_prior_answers` put them there
    under exactly these ids — so nothing is embedded again. Re-uploading a
    corrected version of a file replaces the index's copy of it, and this
    replaces the rows to match, dropping any that the new version no longer has.

    They arrive unscanned, which is what puts them in front of the sweep that
    looks for what they contradict.
    """
    team = _team(team_id)
    conn = store.connect()
    keep = set()
    now = store.utcnow()
    for index, pair in enumerate(pairs):
        question = (pair.question or "").strip()
        answer = (pair.answer or "").strip()
        if not question or not answer:
            continue
        entry_id = f"{source_name}::{index}"
        keep.add(entry_id)
        conn.execute(
            "INSERT OR REPLACE INTO memory_entries "
            "(entry_id, team_id, question, answer, section, from_file, origin, "
            " created_at, updated_at, scanned_at) "
            "VALUES (?,?,?,?,?,?,'import',?,?,'')",
            (entry_id, team, question, answer, getattr(pair, "section", "") or "",
             source_name, now, now),
        )
    placeholders = ",".join("?" for _ in keep) or "''"
    conn.execute(
        f"DELETE FROM memory_entries WHERE team_id = ? AND from_file = ? AND origin = 'import' "
        f"AND entry_id NOT IN ({placeholders})",
        (team, source_name, *keep),
    )
    conn.commit()
    return [entry for entry in (get(entry_id, team) for entry_id in sorted(keep)) if entry]


def update(
    entry_id: str, *, question: str | None = None, answer: str | None = None,
    team_id: str | None = None,
) -> Entry | None:
    """Correct a remembered answer in place, and re-index it.

    A correction is not a supersession: nobody changed their mind, the entry was
    simply wrong or badly worded, and there is no earlier position worth keeping.
    """
    team = _team(team_id)
    entry = get(entry_id, team)
    if entry is None:
        return None
    question = entry.question if question is None else question.strip()
    answer = entry.answer if answer is None else answer.strip()
    if not question or not answer:
        raise ValueError("A remembered answer needs both a question and an answer.")

    changed = question != entry.question or answer != entry.answer
    store.connect().execute(
        "UPDATE memory_entries SET question = ?, answer = ?, updated_at = ?, "
        "scanned_at = CASE WHEN ? THEN '' ELSE scanned_at END WHERE team_id = ? AND entry_id = ?",
        (question, answer, store.utcnow(), 1 if changed else 0, team, entry_id),
    )
    store.connect().commit()
    updated = get(entry_id, team)
    if changed:
        index_entry(updated)
    return updated


def remove(entry_id: str, team_id: str | None = None) -> bool:
    """Forget an entry entirely: the row, its vector, and the conflicts it raised.

    The one operation here that loses history, and it exists because the other
    two do not cover "this should never have been in here" -- a draft answer
    approved by mistake, or a pair the extractor invented out of a table.
    """
    team = _team(team_id)
    conn = store.connect()
    deleted = conn.execute(
        "DELETE FROM memory_entries WHERE team_id = ? AND entry_id = ?", (team, entry_id)
    ).rowcount
    conn.execute(
        "DELETE FROM memory_conflicts WHERE team_id = ? AND (entry_id = ? OR other_id = ?)",
        (team, entry_id, entry_id),
    )
    # An entry that pointed at this one as its replacement stands again: the
    # thing that displaced it is gone, so the alternative is an entry that is
    # neither retrievable nor replaced by anything.
    conn.execute(
        "UPDATE memory_entries SET superseded_by = '', superseded_on = '', because = '' "
        "WHERE team_id = ? AND superseded_by = ?",
        (team, entry_id),
    )
    conn.commit()
    if deleted:
        unindex_entry(entry_id, team)
    return bool(deleted)


def supersede(entry_id: str, *, by: str, because: str = "", team_id: str | None = None) -> None:
    """Mark `entry_id` replaced by `by`. Kept, not deleted; simply not retrieved."""
    if entry_id == by:
        return
    # Only while the replacement still exists, checked in the same statement.
    # The sweep decides this after a model call, and an approval withdrawn in
    # those seconds deletes the replacement: marked anyway, an imported answer
    # was replaced by nothing and never retrieved again.
    store.connect().execute(
        "UPDATE memory_entries SET superseded_by = ?, superseded_on = ?, because = ? "
        "WHERE team_id = ? AND entry_id = ? "
        "AND EXISTS (SELECT 1 FROM memory_entries WHERE team_id = ? AND entry_id = ?)",
        (by, store.utcnow(), because, _team(team_id), entry_id, _team(team_id), by),
    )
    store.connect().commit()


def restore(entry_id: str, team_id: str | None = None) -> None:
    """Undo a supersession. For when the newer answer was the wrong one."""
    store.connect().execute(
        "UPDATE memory_entries SET superseded_by = '', superseded_on = '', because = '' "
        "WHERE team_id = ? AND entry_id = ?",
        (_team(team_id), entry_id),
    )
    store.connect().commit()


def reopen_for_scan(*, origin: str = "", team_id: str | None = None) -> int:
    """Put entries back in the sweep's queue. Returns how many.

    The adopted import is marked scanned as it arrives, because a person opening
    the memory page for the first time should not trigger seven hundred model
    calls to see a list. Running that sweep is a decision, and this is how it is
    taken -- once, deliberately, from `scripts/build_answer_memory.py`.
    """
    clause = " AND origin = ?" if origin else ""
    cursor = store.connect().execute(
        f"UPDATE memory_entries SET scanned_at = '' WHERE team_id = ?{clause}",
        (_team(team_id), origin) if origin else (_team(team_id),),
    )
    store.connect().commit()
    return cursor.rowcount


def mark_scanned(entry_id: str, team_id: str | None = None) -> None:
    store.connect().execute(
        "UPDATE memory_entries SET scanned_at = ? WHERE team_id = ? AND entry_id = ?",
        (store.utcnow(), _team(team_id), entry_id),
    )
    store.connect().commit()


def raise_conflict(entry_id: str, other_id: str, because: str, team_id: str | None = None) -> None:
    """Record a disagreement for a person. Idempotent, and unordered.

    The pair is stored one way round only. Which of the two arrived first is an
    accident of upload order and says nothing about which is right, so raising
    it twice -- once from each side -- would put the same question in front of a
    reviewer twice.
    """
    first, second = sorted((entry_id, other_id))
    # Both must still exist -- the same race as `supersede`, and a disagreement
    # with an answer nobody can open is not one a person can settle.
    team = _team(team_id)
    store.connect().execute(
        "INSERT OR IGNORE INTO memory_conflicts (team_id, entry_id, other_id, because, raised_at) "
        "SELECT ?, ?, ?, ?, ? WHERE "
        "(SELECT COUNT(*) FROM memory_entries WHERE team_id = ? AND entry_id IN (?, ?)) = 2",
        (team, first, second, because, store.utcnow(), team, first, second),
    )
    store.connect().commit()


RESOLUTIONS = ("keep_this", "keep_other", "keep_both")


def apply_resolution(
    entry_id: str, other_id: str, *, resolution: str, by: str, team_id: str | None = None,
) -> None:
    """Do what the reviewer decided, and close the disagreement.

    Keeping one of the two supersedes the other -- which is the same mark an
    ordinary revision leaves, because that is what this turns out to be once
    somebody says which answer is current. Keeping both means the pair was
    never the same question, so neither moves and the only thing recorded is
    that a person looked.
    """
    if resolution not in RESOLUTIONS:
        raise ValueError(f"resolution must be one of {RESOLUTIONS}")
    because = "a reviewer chose the other answer"
    if resolution == "keep_this":
        supersede(other_id, by=entry_id, because=because, team_id=team_id)
    elif resolution == "keep_other":
        supersede(entry_id, by=other_id, because=because, team_id=team_id)
    resolve_conflict(entry_id, other_id, by=by, resolution=resolution, team_id=team_id)


def resolve_conflict(
    entry_id: str, other_id: str, *, by: str, resolution: str, team_id: str | None = None,
) -> None:
    """Close a disagreement.

    `resolution` is one of `keep_this`, `keep_other`, `keep_both` — and it is
    recorded rather than acted on here, because the action differs: keeping one
    supersedes the other, keeping both means the model was wrong about them
    being the same question and neither should move.
    """
    first, second = sorted((entry_id, other_id))
    store.connect().execute(
        "UPDATE memory_conflicts SET resolved_at = ?, resolved_by = ?, resolution = ? "
        "WHERE team_id = ? AND entry_id = ? AND other_id = ?",
        (store.utcnow(), by, resolution, _team(team_id), first, second),
    )
    store.connect().commit()


# ---------------------------------------------------------------------------
# The vector side
# ---------------------------------------------------------------------------


def _document(entry: Entry) -> Document:
    return Document(
        page_content=f"Q: {entry.question}\nA: {entry.answer}",
        metadata={
            "source_type": SourceType.PRIOR_ANSWER.value,
            "source_name": MEMORY_SOURCE,
            "from_file": entry.from_file,
            "content_hash": "",
            "chunk": 0,
            "entry_id": entry.entry_id,
            "question": entry.question,
            "answer": entry.answer,
            "section": entry.section,
            "answered_date": entry.approved_on,
            # So an entry adopted back out of the index keeps what it is. Without
            # these, rebuilding the record from the vectors would file every
            # approved answer as an import: undated, unattributed, and unable to
            # supersede anything.
            "origin": entry.origin,
            "approved_by": entry.approved_by,
        },
    )


def index_entry(entry: Entry | None) -> None:
    """Put one entry in the retrieval index, replacing any earlier version of it.

    Failures are logged and swallowed. The row is the record; an entry that is
    stored but not yet retrievable is a gap in recall, while an exception here
    would fail the approval that produced it — and losing the reviewer's
    decision to keep the index tidy is the wrong trade.
    """
    if entry is None:
        return
    try:
        from src.knowledge import get_store

        index = get_store(_team(entry.team_id))
        index.remove_entry(entry.entry_id)
        index.add_entry(entry.entry_id, _document(entry))
    except Exception:  # noqa: BLE001 - never fail the write that produced this
        logger.exception("Could not index memory entry %s", entry.entry_id)


def unindex_entry(entry_id: str, team_id: str | None = None) -> None:
    try:
        from src.knowledge import get_store

        get_store(_team(team_id)).remove_entry(entry_id)
    except Exception:  # noqa: BLE001
        logger.exception("Could not remove memory entry %s from the index", entry_id)


def ensure_synced(team_id: str | None = None) -> None:
    """Give every prior answer in a team's index a row here, once per database and team.

    The 698 imported answers were indexed before this record existed. They are
    the memory, so they have to be manageable, and re-uploading eleven
    questionnaires to get them back is not an answer. Reading them out of the
    index is: every field this table needs is already in their metadata.
    """
    team = _team(team_id)
    key = (str(store.settings.db_path), team)
    if key in _synced:
        return
    _synced.add(key)  # first, so a failure does not retry on every request

    # Put back anything marked replaced by an entry that no longer exists --
    # left by a sweep that finished after its entry was withdrawn, before
    # `supersede` checked. Once per process, like the adoption below.
    repaired = store.connect().execute(
        "UPDATE memory_entries SET superseded_by = '', superseded_on = '', because = '' "
        "WHERE team_id = ? AND superseded_by != '' "
        "AND superseded_by NOT IN (SELECT entry_id FROM memory_entries WHERE team_id = ?)",
        (team, team),
    ).rowcount
    store.connect().commit()
    if repaired:
        logger.warning("Answer memory: %d answer(s) were replaced by nothing; restored", repaired)

    try:
        from src.knowledge import get_store

        found = get_store(team).prior_answer_metadata()
    except Exception:  # noqa: BLE001 - an unreachable index must not break the page
        logger.exception("Could not read the index to sync the answer memory")
        return

    conn = store.connect()
    known = {row["entry_id"] for row in conn.execute(
        "SELECT entry_id FROM memory_entries WHERE team_id = ?", (team,)
    )}
    now = store.utcnow()
    added = 0
    for metadata in found:
        entry_id = entry_id_of(metadata)
        question = str(metadata.get("question") or "").strip()
        answer = str(metadata.get("answer") or "").strip()
        if not entry_id or entry_id in known or not question or not answer:
            continue
        known.add(entry_id)
        origin = str(metadata.get("origin") or "import")
        conn.execute(
            "INSERT OR IGNORE INTO memory_entries "
            "(entry_id, team_id, question, answer, section, from_file, origin, approved_by, "
            " approved_on, created_at, updated_at, scanned_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (entry_id, team, question, answer, str(metadata.get("section") or ""),
             # The questionnaire this answer was actually given in, which is not
             # always the name it was indexed under: the bulk import filed 698
             # answers from eleven different questionnaires under one synthetic
             # source, and it is the real one that says whether two answers are
             # two customers being told different things or one form's own rows.
             str(metadata.get("from_file") or metadata.get("source_name") or ""),
             origin if origin in ORIGINS else "import",
             str(metadata.get("approved_by") or ""),
             str(metadata.get("answered_date") or metadata.get("answered_on") or ""),
             now, now, now),
        )
        added += 1
    conn.commit()
    if added:
        logger.info("Answer memory: adopted %d already-indexed answers", added)


def forget_sync() -> None:
    """For tests, which point the database at a fresh file between cases."""
    _synced.clear()


# ---------------------------------------------------------------------------
# Finding what an arrival means
# ---------------------------------------------------------------------------


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
    from src.models import SameQuestions
    from src.prompts import SAME_QUESTION_SYSTEM, SAME_QUESTION_USER

    listed = "\n".join(
        f"{n}. {candidate.question}" for n, candidate in enumerate(candidates, start=1)
    )
    try:
        verdict = await structured_llm(SameQuestions, temperature=0.0).ainvoke([
            ("system", SAME_QUESTION_SYSTEM),
            ("user", SAME_QUESTION_USER.format(question=question, candidates=listed)),
        ])
    except Exception as error:  # noqa: BLE001 - re-raised unless it is the empty answer
        if not tool_use_failed(error):
            raise
        # The model wrote its answer instead of calling the tool, and the answer
        # it wrote was "[]". Treating that as "none of them" is not a guess: the
        # empty verdict is the common one here, since these candidates were
        # chosen for looking alike rather than for being alike.
        logger.warning("Same-question check returned prose rather than a call; reading it as none")
        return []
    return [
        candidates[n - 1] for n in dict.fromkeys(verdict.same) if 1 <= n <= len(candidates)
    ]


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
    return [
        candidate
        for candidate, vector in zip(candidates, theirs)
        if _cosine(mine, vector) >= memory.PROPOSE
    ]


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
    from src.knowledge import get_store

    team = _team(entry.team_id)
    hits = await get_store(team).search(entry.question, SourceType.PRIOR_ANSWER, k, expand=False)
    seen: dict[str, Entry] = {}
    for hit in hits:
        other = get(hit.entry_id, team)
        if other is None or other.entry_id == entry.entry_id or other.entry_id in seen:
            continue
        if not other.stands:
            continue  # already replaced; it is history, not a second opinion
        if (
            entry.origin == "import" == other.origin
            and entry.from_file
            and entry.from_file == other.from_file
        ):
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
            supersede(other.entry_id, by=entry.entry_id, because=finding.because, team_id=team)
        elif finding.kind == "superseded_by":
            supersede(entry.entry_id, by=other.entry_id, because=finding.because, team_id=team)
            # It arrived already out of date, which happens when an older
            # questionnaire is imported after a newer one. Stop: an entry that
            # no longer stands has no standing to replace or contradict a third.
            break
        else:
            raise_conflict(entry.entry_id, other.entry_id, finding.because, team_id=team)
    return findings


async def scan_pending(
    *, limit: int = 25, concurrency: int = 4, team_id: str | None = None,
) -> list[Finding]:
    """Compare everything that has arrived since the last scan.

    Runs after an import and after an approval rather than at answer time. By
    the time a questionnaire is being answered it is too late to be useful --
    whichever entry retrieval ranked first has already gone into a customer's
    file -- and the person filling in the form is not the person who can say
    which of two answers is our position.
    """
    waiting = pending(limit=limit, team_id=team_id)
    if not waiting:
        return []

    gate = asyncio.Semaphore(concurrency)

    async def one(entry: Entry) -> list[Finding]:
        async with gate:
            try:
                found = await scan(entry)
            except Exception:  # noqa: BLE001 - one bad entry must not stop the sweep
                logger.exception("Could not scan memory entry %s", entry.entry_id)
                return []
            mark_scanned(entry.entry_id, entry.team_id)
            return found

    found = await asyncio.gather(*(one(entry) for entry in waiting))
    return [finding for group in found for finding in group]
