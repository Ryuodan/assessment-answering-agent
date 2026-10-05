"""Keeping each person's stored files within a limit, oldest work first.

Questionnaires arrive from other companies and are confidential, and every one
uploaded stayed on the server for good, with its filled copy beside it. So each
person has a storage limit. Under it nothing is touched. Over it, the files
belonging to the work they have not come back to longest are removed until they
are under again.

It is a limit per person rather than per team because that is who the files
belong to: a questionnaire is uploaded by somebody, answered by them, and listed
only for them. A second person on the team brings their own allowance, so the
limit never has to be raised because the team grew.

Two things are never removed, whatever the limit says:

* **A document the team's knowledge base was built from.** It is what answers
  are drafted from and what a person opens to check a citation. Policies belong
  to the team, not to whoever uploaded them, and count against nobody.
* **Anything used in the last `STORAGE_KEEP_DAYS` days.** The limit is a
  number somebody chose for the usage they had then. If a person's work grows
  and nobody raises it, the work in front of them is still left alone -- they
  simply stay over the limit, and the log says so -- rather than a
  questionnaire disappearing from under the person answering it.

What goes can be got back in the way that matters: a filled copy is written
again by pressing Fill, and a questionnaire whose upload has gone keeps its
answers, and says when somebody tries to fill it that the file has to be
uploaded again.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.logs import get_logger
from src import events, store
from src.config import settings
from src.identity import User

logger = get_logger(__name__)

CHECK_EVERY_SECONDS = 60 * 60
"""How often everybody is checked while the server runs. Uploads are a few a
day and the limit is measured in gigabytes, so an hour late costs nothing."""

MB = 1024 * 1024


@dataclass(frozen=True)
class Person:
    """Somebody with files on the server: who they are, and which team's."""

    email: str
    team_id: str


@dataclass
class Item:
    """One file that could be removed, and when it was last of use."""

    path: Path
    size: int
    last_used: datetime
    kind: str  # "questionnaire" | "filled copy"


@dataclass
class Checked:
    """What checking one person's storage found and did."""

    email: str
    team_id: str
    used_bytes: int = 0
    limit_bytes: int = 0
    removed: list[str] = field(default_factory=list)
    freed_bytes: int = 0

    @property
    def over(self) -> bool:
        return bool(self.limit_bytes) and self.used_bytes > self.limit_bytes


def _modified(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _parse(stamp: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _key(path: Path) -> str:
    try:
        return str(path.resolve()).casefold()
    except OSError:
        return str(path).casefold()


def _files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return [path for path in directory.iterdir() if path.is_file()]


@dataclass
class _Batch:
    batch_id: str
    actor_email: str
    source: Path
    updated: datetime | None


def _batches(team_id: str) -> list[_Batch]:
    """Every questionnaire in a team, oldest first -- the order decides ownership."""
    rows = (
        store.connect()
        .execute(
            """
        SELECT batch_id, actor_email, source_path, updated_at
          FROM form_batches
         WHERE team_id = ?
         ORDER BY created_at, rowid
        """,
            (team_id,),
        )
        .fetchall()
    )
    return [
        _Batch(row["batch_id"], row["actor_email"], Path(row["source_path"]), _parse(row["updated_at"])) for row in rows
    ]


def _stored(person: Person) -> tuple[list[Path], list[tuple[Path, datetime | None]], dict[str, datetime]]:
    """One person's uploads, their filled copies, and when each file was last in use.

    Uploads are the files in their own folder, plus -- from before uploads were
    kept per person -- the ones still in the team's folder that their
    questionnaire was the first to read. First to read, because `save_upload`
    gives byte-identical content one name: two people who uploaded the same file
    share it, and it belongs to whoever got there first rather than to both.
    """
    mine = settings.user_upload_dir(person.team_id, person.email)
    shared = settings.team_upload_dir(person.team_id).resolve()

    owner: dict[str, str] = {}
    last_used: dict[str, datetime] = {}
    filled: list[tuple[Path, datetime | None]] = []
    legacy: list[Path] = []
    for batch in _batches(person.team_id):
        key = _key(batch.source)
        owner.setdefault(key, batch.actor_email)
        # In use for as long as anybody's batch reading it is: two people can
        # work on one file, and one of them being finished does not end it.
        if batch.updated is not None:
            last_used[key] = max(last_used.get(key, batch.updated), batch.updated)
        if batch.actor_email != person.email:
            continue
        if batch.source.parent.resolve() == shared and batch.source.is_file() and owner[key] == person.email:
            legacy.append(batch.source)
        filled.extend((path, batch.updated) for path in _files(settings.filled_dir / batch.batch_id))

    uploads = _files(mine) + [path for path in dict.fromkeys(legacy)]
    return uploads, filled, last_used


def used_bytes(person: Person) -> int:
    """How much one person is storing. Walks folders; reads no index."""
    uploads, filled, _ = _stored(person)
    return sum(path.stat().st_size for path in uploads) + sum(path.stat().st_size for path, _ in filled)


def removable(person: Person) -> list[Item]:
    """What of one person's storage could go, the longest unused first.

    Documents the team's knowledge base was built from are not listed at all.
    """
    from src.knowledge import get_store

    indexed = set(get_store(person.team_id).documents_indexed())
    uploads, filled, last_used = _stored(person)

    items = []
    for path in uploads:
        if path.name in indexed:
            continue
        last = max(filter(None, (_modified(path), last_used.get(_key(path)))))
        items.append(Item(path, path.stat().st_size, last, "questionnaire"))
    for path, updated in filled:
        last = max(filter(None, (_modified(path), updated)))
        items.append(Item(path, path.stat().st_size, last, "filled copy"))
    # Between two files last used at the same time, the filled copy goes first:
    # pressing Fill writes it again, and nothing brings back the upload.
    return sorted(items, key=lambda item: (item.last_used, item.kind != "filled copy"))


def enforce(person: Person, *, now: datetime | None = None) -> Checked:
    """Bring one person under their limit, removing only work nobody has used lately."""
    from src.service import _extracted_text_cache_path

    checked = Checked(
        person.email,
        person.team_id,
        used_bytes(person),
        settings.storage_limit_per_user_mb * MB,
    )
    if not checked.over:
        return checked

    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=settings.storage_keep_days)
    for item in removable(person):
        if not checked.over or item.last_used >= cutoff:
            break  # oldest first, so everything after a recent one is recent too
        try:
            if item.kind == "questionnaire":
                # The text read out of it is as confidential as the file.
                _extracted_text_cache_path(item.path).unlink(missing_ok=True)
            item.path.unlink()
        except OSError:
            logger.warning("storage.remove_failed", file=str(item.path), exc_info=True)
            continue
        checked.used_bytes -= item.size
        checked.freed_bytes += item.size
        checked.removed.append(f"{item.kind}: {item.path.name}")
        if item.kind == "filled copy" and not any(item.path.parent.iterdir()):
            item.path.parent.rmdir()

    if checked.removed:
        logger.info(
            "storage.files_removed",
            person=person.email,
            limit_mb=settings.storage_limit_per_user_mb,
            files=len(checked.removed),
            freed_mb=round(checked.freed_bytes / MB, 1),
        )
        events.record(
            User(email=person.email, team_id=person.team_id),
            events.FILES_REMOVED,
            subject_type="storage",
            subject_id=person.email,
            files=checked.removed[:500],
            freed_bytes=checked.freed_bytes,
            limit_mb=settings.storage_limit_per_user_mb,
            keep_days=settings.storage_keep_days,
        )
    if checked.over:
        logger.warning(
            "storage.over_limit",
            person=person.email,
            used_mb=round(checked.used_bytes / MB),
            limit_mb=settings.storage_limit_per_user_mb,
            keep_days=settings.storage_keep_days,
            reason="everything left is in the knowledge base or was used recently",
            fix="raise STORAGE_LIMIT_PER_USER_MB if they need the room",
        )
    return checked


def everybody() -> list[Person]:
    """Whose files are on the server.

    Everyone who can sign in, and everyone a questionnaire is recorded against
    -- which is not the same list. Somebody removed from the access panel leaves
    their files behind, and those still age out."""
    from src import identity

    people = {Person(person["email"], person["team"] or settings.default_team) for person in identity.list_users()}
    people |= {
        Person(row["actor_email"], row["team_id"])
        for row in store.connect().execute("SELECT DISTINCT actor_email, team_id FROM form_batches").fetchall()
        if row["actor_email"]
    }
    return sorted(people, key=lambda person: (person.team_id, person.email))


def enforce_all() -> list[Checked]:
    """Everybody, once."""
    if not settings.storage_limit_per_user_mb:
        return []

    results = []
    for person in everybody():
        try:
            results.append(enforce(person))
        except Exception:  # noqa: BLE001 - one person's check must not stop the others'
            logger.exception("storage.check_failed", person=person.email)
    return results


async def keep_within_limits(every: float = CHECK_EVERY_SECONDS) -> None:
    """Check everybody at startup, then once an interval, until cancelled."""
    while True:
        try:
            await asyncio.to_thread(enforce_all)
        except Exception:  # noqa: BLE001 - housekeeping must never take the server down
            logger.exception("storage.sweep_failed")
        await asyncio.sleep(every)
