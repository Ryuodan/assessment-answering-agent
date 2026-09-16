"""Keeping each team's stored files within a limit, oldest work first.

Questionnaires arrive from other companies and are confidential, and every one
uploaded stayed on the server for good, with its filled copy beside it. So each
team has a storage limit. Under it nothing is touched. Over it, the files
belonging to the work nobody has come back to longest are removed until the team
is under again.

Two things are never removed, whatever the limit says:

* **A document the team's knowledge base was built from.** It is what answers
  are drafted from and what a person opens to check a citation.
* **Anything used in the last `STORAGE_KEEP_DAYS` days.** The limit is a
  number somebody chose for the usage they had then. If the team grows and
  nobody raises it, the work in front of people is still left alone -- the team
  stays over its limit and the log says so -- rather than a questionnaire
  disappearing from under the person answering it.

The limit is per team, so a new team brings its own allowance rather than
sharing the first team's.

What goes can be got back in the way that matters: a filled copy is written
again by pressing Fill, and a questionnaire whose upload has gone keeps its
answers, and says when somebody tries to fill it that the file has to be
uploaded again.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src import events, store
from src.config import settings
from src.identity import User

logger = logging.getLogger(__name__)

SYSTEM_EMAIL = "storage@system"
"""Who removed a file, in the event log. Nobody did; the limit did."""

CHECK_EVERY_SECONDS = 60 * 60
"""How often every team is checked while the server runs. Uploads are a few a
day and the limit is measured in gigabytes, so an hour late costs nothing."""

MB = 1024 * 1024


@dataclass
class Item:
    """One file that could be removed, and when it was last of use."""

    path: Path
    size: int
    last_used: datetime
    kind: str  # "questionnaire" | "filled copy"


@dataclass
class Checked:
    """What checking one team's storage found and did."""

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


def _batches(team_id: str) -> list[tuple[str, Path, datetime | None]]:
    rows = store.connect().execute(
        "SELECT batch_id, source_path, updated_at FROM form_batches WHERE team_id = ?", (team_id,)
    ).fetchall()
    return [(row["batch_id"], Path(row["source_path"]), _parse(row["updated_at"])) for row in rows]


def _files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return [path for path in directory.iterdir() if path.is_file()]


def _key(path: Path) -> str:
    try:
        return str(path.resolve()).casefold()
    except OSError:
        return str(path).casefold()


def _stored(team_id: str) -> tuple[list[Path], list[tuple[Path, datetime | None]]]:
    """A team's uploads, and its filled copies with when their batch was last touched."""
    uploads = _files(settings.team_upload_dir(team_id))
    filled = [
        (path, updated)
        for batch_id, _source, updated in _batches(team_id)
        for path in _files(settings.filled_dir / batch_id)
    ]
    return uploads, filled


def used_bytes(team_id: str) -> int:
    """How much a team is storing. Walks two directories; reads no index."""
    uploads, filled = _stored(team_id)
    return sum(path.stat().st_size for path in uploads) + sum(path.stat().st_size for path, _ in filled)


def removable(team_id: str) -> list[Item]:
    """What of a team's storage could go, the longest unused first.

    A questionnaire is in use for as long as any batch reading it is being
    worked on: two people can open the same file. Documents the knowledge base
    was built from are not listed at all.
    """
    from src.knowledge import get_store

    indexed = set(get_store(team_id).documents_indexed())
    last_batch_use: dict[str, datetime] = {}
    for _batch_id, source, updated in _batches(team_id):
        if updated is not None:
            key = _key(source)
            last_batch_use[key] = max(last_batch_use.get(key, updated), updated)

    uploads, filled = _stored(team_id)
    items = []
    for path in uploads:
        if path.name in indexed:
            continue
        last = max(filter(None, (_modified(path), last_batch_use.get(_key(path)))))
        items.append(Item(path, path.stat().st_size, last, "questionnaire"))
    for path, updated in filled:
        last = max(filter(None, (_modified(path), updated)))
        items.append(Item(path, path.stat().st_size, last, "filled copy"))
    # Between two files last used at the same time, the filled copy goes first:
    # pressing Fill writes it again, and nothing brings back the upload.
    return sorted(items, key=lambda item: (item.last_used, item.kind != "filled copy"))


def enforce(team_id: str, *, now: datetime | None = None) -> Checked:
    """Bring one team under its limit, removing only work nobody has used lately."""
    from src.service import _extracted_text_cache_path

    checked = Checked(team_id, used_bytes(team_id), settings.storage_limit_per_team_mb * MB)
    if not checked.over:
        return checked

    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=settings.storage_keep_days)
    for item in removable(team_id):
        if not checked.over or item.last_used >= cutoff:
            break  # oldest first, so everything after a recent one is recent too
        try:
            if item.kind == "questionnaire":
                # The text read out of it is as confidential as the file.
                _extracted_text_cache_path(item.path).unlink(missing_ok=True)
            item.path.unlink()
        except OSError:
            logger.warning("Storage: could not remove %s", item.path, exc_info=True)
            continue
        checked.used_bytes -= item.size
        checked.freed_bytes += item.size
        checked.removed.append(f"{item.kind}: {item.path.name}")
        if item.kind == "filled copy" and not any(item.path.parent.iterdir()):
            item.path.parent.rmdir()

    if checked.removed:
        logger.info(
            "Storage: team %s was over its %d MB limit; removed %d old file(s), %.1f MB.",
            team_id, settings.storage_limit_per_team_mb, len(checked.removed), checked.freed_bytes / MB,
        )
        events.record(
            User(email=SYSTEM_EMAIL, team_id=team_id), events.FILES_REMOVED,
            subject_type="storage", subject_id=team_id,
            files=checked.removed[:500], freed_bytes=checked.freed_bytes,
            limit_mb=settings.storage_limit_per_team_mb, keep_days=settings.storage_keep_days,
        )
    if checked.over:
        logger.warning(
            "Storage: team %s is using %.0f MB, over its %d MB limit. Everything left is either "
            "in its knowledge base or was used in the last %d days, so nothing more was removed. "
            "Raise STORAGE_LIMIT_PER_TEAM_MB if the team needs the room.",
            team_id, checked.used_bytes / MB, settings.storage_limit_per_team_mb,
            settings.storage_keep_days,
        )
    return checked


def enforce_all() -> list[Checked]:
    """Every team, once."""
    if not settings.storage_limit_per_team_mb:
        return []
    from src import identity

    teams = {settings.default_team, *(team["id"] for team in identity.list_teams())}
    results = []
    for team in sorted(teams):
        try:
            results.append(enforce(team))
        except Exception:  # noqa: BLE001 - one team's check must not stop the others'
            logger.exception("Storage: could not check team %s", team)
    return results


async def keep_within_limits(every: float = CHECK_EVERY_SECONDS) -> None:
    """Check every team at startup, then once an interval, until cancelled."""
    while True:
        try:
            await asyncio.to_thread(enforce_all)
        except Exception:  # noqa: BLE001 - housekeeping must never take the server down
            logger.exception("Storage: the check failed")
        await asyncio.sleep(every)
