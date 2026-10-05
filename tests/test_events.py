"""The event log: what it records, and that nothing quietly rewrites it.

The value of this table is that it is the one place you can go to find out what
happened. That only holds if writes are append-only, ordering survives events
that land in the same second, and one team cannot see another's activity.
"""

from __future__ import annotations

import pytest

from src import events, identity, store
from src.config import settings
from src.identity import User

ALICE = User(email="m.alsaif@t2.sa", team_id="cybersecurity")
BOB = User(email="mohammed.sa.alsaif@gmail.com", team_id="cybersecurity")
OTHER_TEAM = User(email="someone@t2.sa", team_id="privacy")


@pytest.fixture(autouse=True)
def _people():
    """Events reference users, and users reference teams."""
    conn = store.connect()
    for user in (ALICE, BOB, OTHER_TEAM):
        identity.ensure_team(user.team_id)
        conn.execute(
            "INSERT INTO users (email, team_id, created_at, last_seen_at) VALUES (?, ?, ?, ?)",
            (user.email, user.team_id, store.utcnow(), store.utcnow()),
        )
    conn.commit()


# --- writing ---------------------------------------------------------------


def test_record_returns_an_increasing_id():
    first = events.record(ALICE, events.SIGNED_IN)
    second = events.record(ALICE, events.SIGNED_OUT)
    assert second > first


def test_the_payload_round_trips():
    events.record(
        ALICE,
        events.RUN_FINISHED,
        subject_type="run",
        subject_id="r1",
        source_name="PSAT Questionnaire v2.1.xlsx",
        questions=183,
        needs_review=4,
    )
    [event] = events.recent(ALICE.team_id)
    assert event.payload == {
        "source_name": "PSAT Questionnaire v2.1.xlsx",
        "questions": 183,
        "needs_review": 4,
    }
    assert event.subject_type == "run"
    assert event.subject_id == "r1"
    assert event.actor_email == ALICE.email


def test_arabic_survives_a_payload():
    events.record(ALICE, events.ANSWER_EDITED, answer="نعم، لدينا سياسة معتمدة")
    [event] = events.recent(ALICE.team_id)
    assert event.payload["answer"] == "نعم، لدينا سياسة معتمدة"


def test_an_event_needs_a_kind():
    with pytest.raises(ValueError, match="kind"):
        events.record(ALICE, "")


def test_an_event_with_no_payload_is_fine():
    events.record(ALICE, events.SIGNED_IN)
    assert events.recent(ALICE.team_id)[0].payload == {}


# --- reading ---------------------------------------------------------------


def test_recent_is_newest_first_even_within_one_second():
    """Ordering by timestamp alone would scramble these; the id is the tiebreak."""
    for index in range(5):
        events.record(ALICE, events.ANSWER_EDITED, index=index)
    assert [event.payload["index"] for event in events.recent(ALICE.team_id)] == [4, 3, 2, 1, 0]


def test_recent_honours_the_limit():
    for _ in range(10):
        events.record(ALICE, events.SIGNED_IN)
    assert len(events.recent(ALICE.team_id, limit=3)) == 3


@pytest.mark.parametrize("limit", [0, -5])
def test_a_nonsense_limit_still_returns_something(limit):
    """A limit of 0 in SQLite returns nothing at all; clamp rather than surprise."""
    events.record(ALICE, events.SIGNED_IN)
    assert len(events.recent(ALICE.team_id, limit=limit)) == 1


def test_recent_can_filter_by_kind():
    events.record(ALICE, events.SIGNED_IN)
    events.record(ALICE, events.RUN_FINISHED, subject_id="r1")
    events.record(ALICE, events.RUN_FINISHED, subject_id="r2")
    found = events.recent(ALICE.team_id, kind=events.RUN_FINISHED)
    assert [event.subject_id for event in found] == ["r2", "r1"]


def test_one_team_cannot_see_another():
    events.record(ALICE, events.SIGNED_IN)
    events.record(OTHER_TEAM, events.SIGNED_IN)
    assert [event.actor_email for event in events.recent("cybersecurity")] == [ALICE.email]
    assert [event.actor_email for event in events.recent("privacy")] == [OTHER_TEAM.email]


def test_teammates_share_a_feed():
    """A shared knowledge base means a shared history; that is the point."""
    events.record(ALICE, events.SIGNED_IN)
    events.record(BOB, events.SIGNED_IN)
    assert {event.actor_email for event in events.recent("cybersecurity")} == {ALICE.email, BOB.email}


def test_for_subject_reads_oldest_first():
    """The history of one run is a story, not a feed."""
    events.record(ALICE, events.RUN_STARTED, subject_type="run", subject_id="r1")
    events.record(ALICE, events.RUN_FINISHED, subject_type="run", subject_id="r1")
    events.record(BOB, events.ANSWER_EDITED, subject_type="run", subject_id="r1")
    events.record(ALICE, events.RUN_STARTED, subject_type="run", subject_id="r2")

    story = events.for_subject("run", "r1")
    assert [event.kind for event in story] == [events.RUN_STARTED, events.RUN_FINISHED, events.ANSWER_EDITED]


def test_for_subject_of_an_unknown_thing_is_empty():
    assert events.for_subject("run", "never-happened") == []


# --- append-only -----------------------------------------------------------


def test_nothing_in_the_module_updates_or_deletes():
    """A correction is a new event. Enforced by reading the source, because the
    guarantee is about what the module *offers*, not what SQL can do."""
    import inspect

    source = inspect.getsource(events).upper()
    assert "UPDATE EVENTS" not in source
    assert "DELETE FROM EVENTS" not in source


def test_ids_are_not_reused_after_a_gap():
    """AUTOINCREMENT, so a deleted row's id never comes back to confuse a reader."""
    first = events.record(ALICE, events.SIGNED_IN)
    conn = store.connect()
    conn.execute("DELETE FROM events WHERE id = ?", (first,))
    conn.commit()
    assert events.record(ALICE, events.SIGNED_IN) > first


def test_events_outlive_the_connection():
    events.record(ALICE, events.SIGNED_IN, note="before")
    store.reset_connection()
    assert events.recent(ALICE.team_id)[0].payload["note"] == "before"


def test_the_default_team_is_what_identity_uses():
    """A drift between these two would split one team's history in half."""
    user = identity.local_user()
    events.record(user, events.SIGNED_IN)
    assert events.recent(settings.default_team)[0].actor_email == identity.LOCAL_EMAIL
