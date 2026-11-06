"""`inspect fills`: which filled files may hold answers the review gate holds back (plan 029, 0.1b).

Before plan 029 every Workbench fill wrote held answers and recorded
`held_back=0` (TD-052), and a withdrawn approval left its answer released
(TD-053). The audit finds both from the event log and today's answers, and
changes nothing.
"""

from __future__ import annotations

import pytest

from src import batches, cli, events, fill_audit, identity, store, tools
from src.config import settings
from src.models import AnsweredQuestion
from tests import forms_fixtures as shapes

TEAM = settings.default_team
UNGROUNDED = "the reviewer did not find the answer grounded"


@pytest.fixture
def user():
    return identity.local_user()


@pytest.fixture
def flagged(user, tmp_path, monkeypatch):
    """A four-question workbook, every answer flagged by the reviewer."""

    async def fake(questions, language=None, run_id=None, **extra):
        return [
            AnsweredQuestion(
                question=q, answer="Probably.", confidence=0.3, needs_review=True, review_reasons=[UNGROUNDED]
            )
            for q in questions
        ]

    monkeypatch.setattr(tools.service, "answer_questions", fake)
    batch = tools.open_form(user, shapes.simple(tmp_path / "vendor.xlsx"))
    import asyncio

    asyncio.run(tools.answer(user, batch.id))
    return batch


def filled_before_the_fix(user, batch, *, written=4, held_back=0):
    """A FILE_FILLED event as the code before plan 029 recorded it: no `include_unreviewed`."""
    events.record(
        user,
        events.FILE_FILLED,
        subject_type=batches.SUBJECT,
        subject_id=batch.id,
        written=written,
        created=written,
        replaced=0,
        left_blank=0,
        held_back=held_back,
    )


def test_a_fill_that_wrote_held_answers_is_found(user, flagged):
    filled_before_the_fix(user, flagged)

    [found] = fill_audit.held_fills(TEAM)

    assert found.batch_id == flagged.id and found.source_name == "vendor.xlsx"
    assert found.include_unreviewed is None, "recorded before the fix"
    assert len(found.held_unchanged) == 4 and not found.changed_since
    assert found.filled_by == user.email and found.written == 4


def test_a_fill_that_held_them_back_is_not_found(user, flagged):
    """The chat's Fill kept the gate before the fix and recorded its count; since
    the fix, so does the Workbench's."""
    filled_before_the_fix(user, flagged, written=0, held_back=4)
    tools.fill(user, flagged.id)

    assert fill_audit.held_fills(TEAM) == []


def test_written_anyway_is_listed_from_its_own_record(user, flagged):
    tools.fill(user, flagged.id, include_unreviewed=True)

    [found] = fill_audit.held_fills(TEAM)
    assert found.include_unreviewed is True and found.held_back_recorded == 4


def test_an_answer_saved_after_the_fill_is_counted_as_unknown(user, flagged, monkeypatch):
    filled_before_the_fix(user, flagged)
    later = flagged.form.questions[0].id
    monkeypatch.setattr(store, "utcnow", lambda: "2999-01-01T00:00:00+00:00")
    batches.save_answers(flagged.id, [batches.answers(flagged.id)[later]])

    [found] = fill_audit.held_fills(TEAM)

    assert found.changed_since == [later]
    assert later not in found.held_unchanged and len(found.held_unchanged) == 3


def test_written_anyway_lists_only_the_answers_it_wrote(user, flagged):
    """Since plan 029's review "Write them in anyway" names the held answers, and
    the event records which went in: the others were held and not written."""
    agreed = [q.id for q in flagged.form.questions[:2]]
    tools.fill(user, flagged.id, include_unreviewed=True, unreviewed_ids=agreed)

    [found] = fill_audit.held_fills(TEAM)
    assert found.written_anyway == agreed and found.held_unchanged == agreed
    assert "2 written anyway" in "\n".join(fill_audit.report([found], []))


def test_writing_none_of_them_anyway_is_not_listed(user, flagged):
    tools.fill(user, flagged.id, include_unreviewed=True, unreviewed_ids=[])
    assert fill_audit.held_fills(TEAM) == []


def test_an_answer_cleared_after_the_fill_is_counted_as_unknown(user, flagged, monkeypatch):
    """Plan 029's review: an answer emptied after a fill had no row left, and the
    fill dropped out of the audit although the file sent may hold it."""
    filled_before_the_fix(user, flagged)
    monkeypatch.setattr(store, "utcnow", lambda: "2999-01-01T00:00:00+00:00")
    cleared, unblanked = flagged.form.questions[0].id, flagged.form.questions[1].id
    tools.set_answer(user, flagged.id, cleared, "")
    tools.blank_answer(user, flagged.id, unblanked)
    tools.blank_answer(user, flagged.id, unblanked, blank=False)
    for question in flagged.form.questions[2:]:
        tools.set_answer(user, flagged.id, question.id, "")

    [found] = fill_audit.held_fills(TEAM)

    assert sorted(found.changed_since) == sorted(q.id for q in flagged.form.questions)
    assert found.held_unchanged == []


def test_an_answer_cleared_before_the_fill_is_not_counted(user, flagged, monkeypatch):
    first = flagged.form.questions[0].id
    tools.set_answer(user, flagged.id, first, "")
    monkeypatch.setattr(store, "utcnow", lambda: "2999-01-01T00:00:00+00:00")
    filled_before_the_fix(user, flagged)

    [found] = fill_audit.held_fills(TEAM)
    assert first not in found.changed_since and first not in found.held_unchanged


def test_a_fill_of_a_questionnaire_no_longer_here_is_listed_as_unknown(user, flagged):
    filled_before_the_fix(user, flagged)
    batches.delete(flagged.id)

    [found] = fill_audit.held_fills(TEAM)

    assert found.gone and found.batch_id == flagged.id and found.written == 4
    assert not found.held_unchanged and not found.changed_since
    printed = "\n".join(fill_audit.report([found], []))
    assert "questionnaire no longer on the server" in printed and "not known" in printed


def test_an_approved_answer_is_not_held_today(user, flagged):
    first = flagged.form.questions[0].id
    tools.approve_answer(user, flagged.id, first)
    filled_before_the_fix(user, flagged)

    [found] = fill_audit.held_fills(TEAM)
    assert first not in found.held_unchanged and len(found.held_unchanged) == 3


def test_another_teams_fills_are_not_listed(user, flagged):
    filled_before_the_fix(user, flagged)
    assert fill_audit.held_fills("privacy") == []


def _left_released(batch, question_id):
    """What withdrawing an approval stored before plan 029: the flag cleared, the reasons kept."""
    answer = batches.answers(batch.id)[question_id].model_copy(deep=True)
    answer.needs_review, answer.confidence, answer.confidence_reason = False, 0.85, ""
    batches.save_answers(batch.id, [answer], edited_by="")


def withdrawn(user, batch, question_id):
    events.record(
        user,
        events.ANSWER_EDITED,
        subject_type=batches.SUBJECT,
        subject_id=batch.id,
        question_id=question_id,
        approved=False,
    )


def test_a_withdrawn_approval_that_now_passes_is_found(user, flagged):
    released, approved_again = flagged.form.questions[0].id, flagged.form.questions[1].id
    for question_id in (released, approved_again):
        _left_released(flagged, question_id)
        withdrawn(user, flagged, question_id)
    tools.approve_answer(user, flagged.id, approved_again)

    [found] = fill_audit.released_by_withdrawal(TEAM)

    assert (found.batch_id, found.question_id) == (flagged.id, released)
    assert found.reasons == [UNGROUNDED] and found.confidence == pytest.approx(0.85)
    assert found.withdrawn_by == user.email


def test_a_withdrawn_answer_the_review_would_not_flag_is_not_listed(user, flagged):
    """Confident, no reasons: the gate lets it through and so would the review."""
    question_id = flagged.form.questions[0].id
    answer = batches.answers(flagged.id)[question_id].model_copy(deep=True)
    answer.needs_review, answer.confidence, answer.review_reasons = False, 0.9, []
    batches.save_answers(flagged.id, [answer])
    withdrawn(user, flagged, question_id)

    assert fill_audit.released_by_withdrawal(TEAM) == []


def test_a_withdrawn_answer_at_the_threshold_is_held_by_the_gate_and_not_listed(user, flagged):
    """Plan 030: the gate holds a score at the threshold, as the review does, so it is not released.
    It compared "under" until then, and the audit listed this answer as written as if confident."""
    question_id = flagged.form.questions[0].id
    answer = batches.answers(flagged.id)[question_id].model_copy(deep=True)
    answer.needs_review, answer.review_reasons = False, []
    answer.confidence = settings.review_confidence_threshold
    batches.save_answers(flagged.id, [answer])
    withdrawn(user, flagged, question_id)

    assert fill_audit.released_by_withdrawal(TEAM) == []
    assert tools.ready_to_write(batches.answers(flagged.id)[question_id])[0] is False


def _everything():
    conn = store.connect()
    return (
        [tuple(row) for row in conn.execute("SELECT * FROM events ORDER BY id")],
        [tuple(row) for row in conn.execute("SELECT * FROM batch_answers ORDER BY batch_id, question_id")],
        [tuple(row) for row in conn.execute("SELECT * FROM form_batches ORDER BY batch_id")],
    )


def test_the_audit_changes_nothing(user, flagged, capsys):
    filled_before_the_fix(user, flagged)
    _left_released(flagged, flagged.form.questions[0].id)
    withdrawn(user, flagged, flagged.form.questions[0].id)
    before = _everything()

    fill_audit.held_fills(TEAM)
    fill_audit.released_by_withdrawal(TEAM)
    assert cli.main(["inspect", "fills", "--team", TEAM]) == 0
    assert cli.main(["inspect", "fills", "--team", TEAM, "--json"]) == 0

    assert _everything() == before


def test_inspect_fills_prints_each_candidate(user, flagged, capsys):
    filled_before_the_fix(user, flagged)

    assert cli.main(["inspect", "fills", "--team", TEAM]) == 0

    out = capsys.readouterr().out
    assert "Fills that wrote answers the review gate holds back: 1" in out
    assert "vendor.xlsx" in out and flagged.id in out and "before the fix" in out
    assert "held today and unchanged since the fill: 4" in out
    assert "Approvals withdrawn before the fix, written as if confident: 0" in out


def test_inspect_fills_says_so_when_there_is_nothing(capsys):
    assert cli.main(["inspect", "fills"]) == 0
    out = capsys.readouterr().out
    assert "holds back: 0" in out and "as if confident: 0" in out
