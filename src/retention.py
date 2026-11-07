"""Saved work is not kept for ever: what nobody has used for `RETENTION_DAYS` is deleted (plan 033).

A questionnaire arrives from another company, usually under an NDA, and a chat
is what somebody said while working on it. Both were kept for good. Now each
is kept for `RETENTION_DAYS` after it was last used -- changed, or opened,
because opening one is using it -- and then deleted, with what is only its own:

* a questionnaire, a file's or a list's: its answers, its upload when no other
  questionnaire reads that file and it is in its owner's own folder, and its
  filled copy;
* a conversation: its messages. Its questionnaire goes by its own date, which
  the chat keeps moving while it is used (`batches.LAST_USED`);
* an answered run (`runs`, which no page reads), by when it ran.

Never the knowledge base or its files, the answer memory, products, people or
the event log. Nothing being answered right now (`busy`), and nothing a chat
turn is running in (`chat_running`), is deleted: the next pass looks again.

A pass runs at start-up and then about once a day (`keep_for_days`, started by
the app beside the storage limit). Each team a pass deleted something of gets
one event with the counts, never content; every pass logs `retention.swept`.
`python -m src.cli inspect retention [--days N]` lists what the next N days
would delete, and changes nothing.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src import batches, busy, chat_running, conversations, events, search_plans, store, uploads
from src.batches import Batch
from src.config import settings
from src.errors import QuestionnaireBusy
from src.forms.model import LIST
from src.identity import User
from src.logs import get_logger

logger = get_logger(__name__)

CHECK_EVERY_SECONDS = 24 * 60 * 60
"""About once a day: a day late on a 180-day limit is nothing."""

ACTOR = "retention"
"""Who the events say deleted the work: nobody pressed anything."""

KINDS = ("questionnaire", "list", "conversation", "run")


@dataclass(frozen=True)
class Due:
    """One thing a pass deletes, and when: no content, only what it is and whose."""

    kind: str
    id: str
    team_id: str
    owner: str
    last_used: str
    kept_until: str


def _parse(stamp: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def kept_until(last_used: str) -> str | None:
    """The day something last used at `last_used` is kept until (ISO date), or None when retention is off."""
    if not settings.retention_days:
        return None
    used = _parse(last_used) or datetime.now(timezone.utc)
    return (used + timedelta(days=settings.retention_days)).date().isoformat()


def due(*, within_days: int = 0, now: datetime | None = None) -> list[Due]:
    """What a pass `within_days` from now deletes, longest unused first. Reads only; nothing when retention is off."""
    if not settings.retention_days:
        return []
    moment = (now or datetime.now(timezone.utc)) + timedelta(days=within_days - settings.retention_days)
    cutoff = moment.isoformat(timespec="seconds")
    conn = store.connect()
    rows = [
        ("list" if row["format"] == LIST else "questionnaire", row)
        for row in conn.execute(
            f"SELECT b.batch_id AS id, b.team_id, b.actor_email AS owner, b.format, {batches.LAST_USED} AS used"
            f" FROM form_batches b WHERE {batches.LAST_USED} < ?",
            (cutoff,),
        )
    ]
    rows += [
        ("conversation", row)
        for row in conn.execute(
            f"SELECT conversation_id AS id, team_id, actor_email AS owner, {conversations.LAST_USED} AS used"
            f" FROM conversations WHERE {conversations.LAST_USED} < ?",
            (cutoff,),
        )
    ]
    rows += [
        ("run", row)
        for row in conn.execute(
            "SELECT run_id AS id, team_id, actor_email AS owner, created_at AS used FROM runs WHERE created_at < ?",
            (cutoff,),
        )
    ]
    found = [
        Due(kind, row["id"], row["team_id"], row["owner"], row["used"], kept_until(row["used"]) or "")
        for kind, row in rows
    ]
    return sorted(found, key=lambda item: (item.last_used, KINDS.index(item.kind), item.id))


def _key(path: Path) -> str:
    try:
        return str(path.resolve()).casefold()
    except OSError:
        return str(path).casefold()


def read_by_a_questionnaire(path: Path, *, other_than: str = "") -> bool:
    """Whether a questionnaire (but `other_than`) was read from this file.

    `save_upload` gives identical content one name, so one file can be two
    questionnaires', and one of them going does not take it from the other.
    """
    rows = store.connect().execute(
        "SELECT source_path FROM form_batches WHERE batch_id != ? AND source_path != ''", (other_than,)
    )
    return any(_key(Path(row["source_path"])) == _key(path) for row in rows)


def _only_its_own(batch: Batch) -> bool:
    """Whether a questionnaire's upload is its alone: in its owner's folder, and read by no other questionnaire.

    A file in the team's folder, from before uploads were kept per person, is
    left to the storage limit, which knows which are the knowledge base's.
    """
    source = batch.source_path
    if not source.name or not source.is_file():
        return False
    try:
        mine = source.parent.resolve() == settings.user_upload_dir(batch.team_id, batch.actor_email).resolve()
    except (OSError, ValueError):
        return False
    return mine and not read_by_a_questionnaire(source, other_than=batch.id)


def in_a_running_chat(batch_id: str) -> bool:
    """Whether a chat turn is running in a conversation about this questionnaire."""
    rows = store.connect().execute("SELECT conversation_id FROM conversations WHERE batch_id = ?", (batch_id,))
    return any(chat_running.running(row["conversation_id"]) for row in rows)


def remove_questionnaire(batch: Batch) -> int:
    """Delete a questionnaire, its answers, and the files only it had; returns how many files went.

    No owner check and no busy check: the caller has made both. The rows go
    first, then the files, so a file that cannot be removed (open in another
    program, say) is logged rather than leaving a questionnaire half deleted.
    A conversation about it keeps its messages and loses its answers panel.
    """
    upload = [batch.source_path] if _only_its_own(batch) else []
    filled = settings.filled_dir / batch.id
    files = upload + ([path for path in filled.rglob("*") if path.is_file()] if filled.is_dir() else [])
    # Its questions' wording goes too: kept search plans hold it (plan 034's review).
    search_plans.forget(batch.team_id, batch.product_id, [(q.text, q.section) for q in batch.form.questions])
    batches.delete(batch.id)
    left = uploads.remove(upload, filled if filled.is_dir() else None)
    if left:
        logger.warning("retention.files_left", batch_id=batch.id, files=len(left))
    return len(files) - len(left)


def _still_unused(item: Due) -> bool:
    """Whether it has not been used since the pass listed it: opened meanwhile, it stays (the review)."""
    if item.kind == "run":
        return True
    table, column, used = (
        ("conversations", "conversation_id", conversations.LAST_USED)
        if item.kind == "conversation"
        else ("form_batches b", "b.batch_id", batches.LAST_USED)
    )
    row = store.connect().execute(f"SELECT {used} AS used FROM {table} WHERE {column} = ?", (item.id,)).fetchone()
    return row is not None and row["used"] <= item.last_used


def _remove(item: Due) -> int | None:
    """Delete one due thing; the files that went with it, or None when it is in use right now."""
    if not _still_unused(item):
        return None
    conn = store.connect()
    if item.kind == "run":
        with conn:
            conn.execute("DELETE FROM runs WHERE run_id = ?", (item.id,))  # its answers cascade
        return 0
    if item.kind == "conversation":
        if chat_running.running(item.id):
            return None
        conversations.delete(item.id)
        return 0
    batch = batches.load(item.id)
    if batch is None:
        return 0
    if in_a_running_chat(batch.id):
        return None
    try:
        with busy.hold(batch.id, ACTOR):  # refused while a run answers it; and none starts while it goes
            return remove_questionnaire(batch)
    except QuestionnaireBusy:
        return None


def sweep(*, now: datetime | None = None) -> dict[str, Counter[str]]:
    """One pass: delete what is due, skip what is in use, and say what went. Returns the counts per team."""
    days = settings.retention_days
    if not days:
        logger.info("retention.swept", days=0, effect="retention is off; nothing is deleted")
        return {}
    counts: dict[str, Counter[str]] = {}
    skipped = 0
    for item in due(now=now):
        try:
            files = _remove(item)
        except Exception:  # noqa: BLE001 - one item must not stop the rest
            logger.exception("retention.remove_failed", kind=item.kind, id=item.id)
            continue
        if files is None:
            skipped += 1
            continue
        tally = counts.setdefault(item.team_id, Counter())
        tally[f"{item.kind}s"] += 1
        tally["files"] += files
    for team_id, tally in counts.items():
        events.record(
            User(email=ACTOR, team_id=team_id),
            events.WORK_EXPIRED,
            subject_type="retention",
            subject_id=team_id,
            days=days,
            **{f"{kind}s": tally[f"{kind}s"] for kind in KINDS},
            files=tally["files"],
        )
    # The searches kept for questions hold their words: they go as the work does (plan 034).
    cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=days)).isoformat(timespec="seconds")
    total: Counter[str] = sum(counts.values(), Counter())
    logger.info(
        "retention.swept",
        days=days,
        search_plans=search_plans.forget_unused(cutoff),
        **{f"{kind}s": total[f"{kind}s"] for kind in KINDS},
        files=total["files"],
        skipped_in_use=skipped,
    )
    return counts


async def keep_for_days(every: float = CHECK_EVERY_SECONDS) -> None:
    """A pass at start-up, then one an interval, until cancelled."""
    while True:
        try:
            await asyncio.to_thread(sweep)
        except Exception:  # noqa: BLE001 - housekeeping must never take the server down
            logger.exception("retention.sweep_failed")
        await asyncio.sleep(every)


def report(items: list[Due], within_days: int) -> list[str]:
    """`inspect retention`'s lines: counts by kind and owner, then each item. Ids and dates only."""
    if not settings.retention_days:
        return ["Retention is off (RETENTION_DAYS=0): nothing is deleted."]
    lines = [f"Kept {settings.retention_days} days after last use. Deleted within {within_days} day(s): {len(items)}"]
    by_owner = Counter((item.kind, item.team_id, item.owner) for item in items)
    lines += [f"  {kind:<13} {team}/{owner}: {count}" for (kind, team, owner), count in sorted(by_owner.items())]
    if items:
        lines.append("")
    lines += [
        f"  {item.kept_until}  {item.kind:<13} {item.id}  {item.team_id}/{item.owner}  last used {item.last_used}"
        for item in items
    ]
    return lines
