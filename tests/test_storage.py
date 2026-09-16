"""A team's stored files are kept within its limit, and only old work goes.

The limit was asked for with one condition: that it must not get in the way if
more teams start using the system and nobody remembers to raise it. So the
tests that matter most here are the ones where nothing is removed -- under the
limit, recent work over it, the knowledge base's own documents, another team's
files -- as much as the one where something is.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src import batches, events, identity, storage
from src.config import settings
from src.identity import User
from src.forms.model import DetectedForm
from tests.conftest import FakeVectorStore, bare_store

NOW = datetime(2026, 9, 15, tzinfo=timezone.utc)
OTHER = "privacy"
MB = 1024 * 1024


@pytest.fixture
def indexed(monkeypatch):
    """Each team's knowledge base, as the names of the documents in it."""
    names: dict[str, set[str]] = {}

    def get_store(team_id=None):
        index = bare_store(FakeVectorStore([]))
        index.documents_indexed = lambda: sorted(names.get(team_id or settings.default_team, set()))
        return index

    monkeypatch.setattr("src.knowledge.get_store", get_store)
    return names


@pytest.fixture
def limit(monkeypatch):
    def set_limit(megabytes: int, keep_days: int = 30):
        monkeypatch.setattr(settings, "storage_limit_per_team_mb", megabytes)
        monkeypatch.setattr(settings, "storage_keep_days", keep_days)
    set_limit(1)
    return set_limit


def _age(path: Path, days: float) -> Path:
    stamp = (NOW - timedelta(days=days)).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def upload(name: str, size_mb: float, days_old: float, team: str | None = None) -> Path:
    directory = settings.team_upload_dir(team)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(b"x" * int(size_mb * MB))
    return _age(path, days_old)


def questionnaire(name: str, size_mb: float, days_old: float, *, touched_days_ago: float | None = None,
                  filled_mb: float = 0, team: str | None = None) -> batches.Batch:
    """An uploaded questionnaire with its batch, optionally filled."""
    team = team or settings.default_team
    source = upload(name, size_mb, days_old, team)
    batch = batches.create(User(email="a@example.com", team_id=team), source,
                           DetectedForm(source_name=name, format="xlsx"))
    touched = NOW - timedelta(days=days_old if touched_days_ago is None else touched_days_ago)
    from src import store
    conn = store.connect()
    conn.execute("UPDATE form_batches SET updated_at = ? WHERE batch_id = ?",
                 (touched.isoformat(timespec="seconds"), batch.id))
    conn.commit()
    if filled_mb:
        copy = settings.filled_dir / batch.id / f"{Path(name).stem} - answered.xlsx"
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_bytes(b"y" * int(filled_mb * MB))
        _age(copy, days_old)
    return batch


def test_under_the_limit_nothing_is_touched_however_old(indexed, limit):
    old = upload("Ancient Vendor Review.xlsx", 0.5, days_old=900)

    checked = storage.enforce(settings.default_team, now=NOW)

    assert old.exists() and checked.removed == [] and not checked.over


def test_over_the_limit_the_longest_unused_work_goes_first_until_under(indexed, limit):
    limit(2)
    oldest = questionnaire("Oldest.xlsx", 1, days_old=400)
    middle = questionnaire("Middle.xlsx", 1, days_old=200)
    newest = questionnaire("Newest.xlsx", 0.5, days_old=100)
    from src.service import _extracted_text_cache_path
    read_out = _extracted_text_cache_path(oldest.source_path)
    read_out.parent.mkdir(parents=True, exist_ok=True)
    read_out.write_text("the other company's answers", encoding="utf-8")

    checked = storage.enforce(settings.default_team, now=NOW)

    assert not oldest.source_path.exists()
    assert not read_out.exists(), "the text read out of it goes with it"
    assert middle.source_path.exists() and newest.source_path.exists()
    assert checked.removed == ["questionnaire: Oldest.xlsx"] and not checked.over


def test_of_old_work_the_filled_copy_goes_before_the_upload(indexed, limit):
    """Pressing Fill writes the copy again; nothing brings back the upload."""
    limit(1)
    old = questionnaire("Old.xlsx", 0.6, days_old=300, filled_mb=0.6)

    checked = storage.enforce(settings.default_team, now=NOW)

    assert checked.removed == ["filled copy: Old - answered.xlsx"]
    assert not (settings.filled_dir / old.id).exists(), "its empty folder goes with it"
    assert old.source_path.exists()


def test_removing_files_keeps_the_answers(indexed, limit):
    limit(1)
    old = questionnaire("Old.xlsx", 1.1, days_old=300, filled_mb=1.1)

    storage.enforce(settings.default_team, now=NOW)

    assert not old.source_path.exists() and not (settings.filled_dir / old.id).exists()
    assert batches.load(old.id) is not None


def test_nothing_used_recently_is_removed_even_over_the_limit(indexed, limit, caplog):
    """The limit was set for today's usage. Tomorrow's must not lose work to it."""
    limit(1, keep_days=30)
    busy = [questionnaire(f"This month {n}.xlsx", 0.6, days_old=n * 5) for n in range(1, 5)]

    checked = storage.enforce(settings.default_team, now=NOW)

    assert all(batch.source_path.exists() for batch in busy)
    assert checked.removed == [] and checked.over
    assert "STORAGE_LIMIT_PER_TEAM_MB" in caplog.text


def test_an_old_file_someone_is_still_working_on_counts_as_recent(indexed, limit):
    """Uploaded a year ago, answered this week: the file is in use."""
    limit(1)
    reopened = questionnaire("Annual Review.xlsx", 1.5, days_old=365, touched_days_ago=2)

    storage.enforce(settings.default_team, now=NOW)

    assert reopened.source_path.exists()


def test_the_knowledge_bases_own_documents_are_never_removed(indexed, limit):
    limit(1)
    policy = upload("T2 - Access Control Policy.pdf", 3, days_old=800)
    indexed[settings.default_team] = {policy.name}

    checked = storage.enforce(settings.default_team, now=NOW)

    assert policy.exists() and checked.removed == [] and checked.over


def test_each_team_has_its_own_limit_and_only_its_own_files_are_counted(indexed, limit):
    """A second team adds its own allowance. Nothing it stores pushes the first
    team over, and nothing is removed from it because of the first."""
    limit(1)
    identity.ensure_team(OTHER, name="Privacy")
    ours = questionnaire("Ours.xlsx", 0.8, days_old=400)
    theirs = questionnaire("Theirs.xlsx", 0.8, days_old=500, team=OTHER)

    results = {checked.team_id: checked for checked in storage.enforce_all()}

    assert ours.source_path.exists() and theirs.source_path.exists()
    assert not results[settings.default_team].over and not results[OTHER].over


def test_a_team_over_its_limit_loses_only_its_own_files(indexed, limit):
    limit(1)
    identity.ensure_team(OTHER, name="Privacy")
    ours = questionnaire("Ours.xlsx", 0.8, days_old=400)
    theirs = [questionnaire(f"Theirs {n}.xlsx", 0.8, days_old=500, team=OTHER) for n in range(2)]

    storage.enforce(OTHER, now=NOW)

    assert ours.source_path.exists()
    assert [batch.source_path.exists() for batch in theirs] == [False, True]


def test_a_limit_of_zero_turns_it_off(indexed, limit):
    limit(0)
    old = upload("Huge.xlsx", 5, days_old=900)

    assert storage.enforce_all() == []
    assert not storage.enforce(settings.default_team, now=NOW).over
    assert old.exists()


def test_what_was_removed_is_recorded_for_the_team(indexed, limit):
    limit(1)
    questionnaire("Gone.xlsx", 1.5, days_old=400)

    storage.enforce(settings.default_team, now=NOW)

    [event] = events.recent(settings.default_team, kind=events.FILES_REMOVED)
    assert event.actor_email == storage.SYSTEM_EMAIL
    assert event.payload["files"] == ["questionnaire: Gone.xlsx"]
    assert event.payload["freed_bytes"] == int(1.5 * MB)


def test_under_the_limit_the_index_is_not_even_opened(limit, monkeypatch):
    """Checking runs at startup and every hour. Under the limit it must cost two
    directory listings, not a connection to the vector store."""
    def never(team_id=None):
        raise AssertionError("the index was opened while under the limit")

    monkeypatch.setattr("src.knowledge.get_store", never)
    upload("Small.xlsx", 0.1, days_old=900)

    assert storage.enforce(settings.default_team, now=NOW).removed == []


def test_a_failed_check_never_stops_the_next_one(limit, monkeypatch):
    calls = []

    def failing():
        calls.append(1)
        raise RuntimeError("disk went away")

    monkeypatch.setattr(storage, "enforce_all", failing)

    async def run_twice():
        task = asyncio.create_task(storage.keep_within_limits(every=0.01))
        while len(calls) < 2:
            await asyncio.sleep(0.01)
        task.cancel()

    asyncio.run(run_twice())
    assert len(calls) >= 2


def test_the_server_checks_storage_when_it_starts(monkeypatch):
    from fastapi.testclient import TestClient

    from src.api import app

    checked = []
    monkeypatch.setattr(storage, "enforce_all", lambda: checked.append(True) or [])

    with TestClient(app):
        for _ in range(100):
            if checked:
                break
            asyncio.run(asyncio.sleep(0.01))

    assert checked
