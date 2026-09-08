"""The operations the interface performs and the agent will later call.

Tested with a stand-in for the answering pipeline, because what matters here is
the wiring around it: which questions a scope selects, that answering twice
merges rather than replaces, that a status column gets a word its own file
accepts, and that a person's correction survives everything that runs after it.
"""

from __future__ import annotations

import pytest

from src import batches, events, identity, tools
from src.config import settings
from src.models import AnsweredQuestion
from tests import forms_fixtures as shapes


@pytest.fixture
def user():
    return identity.local_user()


@pytest.fixture
def batch(user, tmp_path):
    """A four-question workbook, opened."""
    return tools.open_form(user, shapes.simple(tmp_path / "vendor.xlsx"))


@pytest.fixture
def dropdown_batch(user, tmp_path):
    """A workbook with a status column whose words live on a hidden sheet."""
    return tools.open_form(user, shapes.status_and_comment(tmp_path / "isra.xlsx"))


@pytest.fixture
def answers_yes(monkeypatch):
    """Stand in for the pipeline: every question gets a confident yes."""
    seen: dict = {}

    async def fake(questions, language=None, run_id=None, **extra):
        seen["questions"] = questions
        seen["run_id"] = run_id
        seen.update(extra)
        return [
            AnsweredQuestion(
                question=question,
                answer=f"Yes, this is documented and approved. [{question.id}]",
                confidence=0.9,
                needs_review=False,
                citations=["T2 - Information Security Policy.pdf §3.1"],
            )
            for question in questions
        ]

    monkeypatch.setattr(tools.service, "answer_questions", fake)
    return seen


# --- opening ---------------------------------------------------------------


def test_opening_a_form_records_its_questions(batch):
    assert len(batch.form.questions) == 4
    assert batch.source_name == "vendor.xlsx"
    assert batch.exists


def test_opening_a_form_is_recorded(batch, user):
    [event] = events.for_subject(batches.SUBJECT, batch.id)
    assert event.kind == events.FORM_OPENED
    assert event.payload["questions"] == 4


def test_a_batch_survives_a_reconnect(batch):
    from src import store

    store.reset_connection()
    again = batches.load(batch.id)
    assert again is not None and len(again.form.questions) == 4


def test_another_teams_batch_reads_as_absent(batch):
    from src.identity import User

    stranger = User(email="someone@t2.sa", team_id="privacy", role="member")
    with pytest.raises(tools.ToolError, match="No questionnaire"):
        tools.inspect(stranger, batch.id)


# --- scope -----------------------------------------------------------------


def test_an_empty_scope_selects_everything(batch, user):
    view = tools.inspect(user, batch.id, tools.Scope())
    assert all(question["selected"] for question in view["questions"])


def test_a_text_scope_narrows(batch, user):
    view = tools.inspect(user, batch.id, tools.Scope(matching="multi-factor"))
    selected = [q["text"] for q in view["questions"] if q["selected"]]
    assert len(selected) == 1 and "multi-factor" in selected[0].lower()


def test_a_scope_by_sheet_narrows(user, tmp_path):
    opened = tools.open_form(user, shapes.legend_sheet(tmp_path / "legend.xlsx"))
    view = tools.inspect(user, opened.id, tools.Scope(part="Questions"))
    assert all(q["selected"] for q in view["questions"])


def test_a_scope_by_id_narrows(batch, user):
    wanted = batch.form.questions[1].id
    view = tools.inspect(user, batch.id, tools.Scope(ids=(wanted,)))
    assert [q["id"] for q in view["questions"] if q["selected"]] == [wanted]


def test_a_scope_that_matches_nothing_is_not_an_error(batch, user):
    view = tools.inspect(user, batch.id, tools.Scope(matching="quantum cryptography"))
    assert not any(q["selected"] for q in view["questions"])


def test_scope_descriptions_read_as_english():
    assert tools.Scope().describe() == "all questions"
    assert "mentioning 'encryption'" in tools.Scope(matching="encryption").describe()
    assert "not yet answered" in tools.Scope(unanswered_only=True).describe()


# --- answering -------------------------------------------------------------


@pytest.mark.asyncio
async def test_answering_stores_an_answer_for_every_question(batch, user, answers_yes):
    outcome = await tools.answer(user, batch.id)
    assert outcome.attempted == 4 and outcome.answered == 4 and not outcome.failed

    view = tools.inspect(user, batch.id)
    assert view["counts"]["answered"] == 4
    assert all(q["answer"] for q in view["questions"])


@pytest.mark.asyncio
async def test_answering_only_the_unanswered_leaves_the_rest_alone(batch, user, answers_yes):
    first = batch.form.questions[0].id
    tools.set_answer(user, batch.id, first, "A hand-written answer.")

    outcome = await tools.answer(user, batch.id, tools.Scope(unanswered_only=True))
    assert outcome.attempted == 3

    view = tools.inspect(user, batch.id)
    kept = next(q for q in view["questions"] if q["id"] == first)
    assert kept["answer"] == "A hand-written answer.", "an upload must not overwrite reviewed work"


# --- answers that already exist --------------------------------------------
#
# The security team's own words, in the file when it arrived, and a reviewed
# answer written here. Both used to go quietly: "answer this questionnaire"
# selected everything, and everything was answered.


@pytest.fixture
def filled(user, tmp_path):
    """A questionnaire that arrives with two of its four questions answered."""
    return tools.open_form(user, shapes.already_answered(tmp_path / "last year.xlsx"))


@pytest.mark.asyncio
async def test_a_broad_scope_leaves_the_files_own_answers_alone(filled, user, answers_yes):
    outcome = await tools.answer(user, filled.id)

    assert outcome.attempted == 2, "it answered the two that were blank"
    assert outcome.protected == 2, "and reported the two it did not touch"
    assert [q.text for q in answers_yes["questions"]] == [
        "Are access rights revoked immediately on termination?",
        "Do you perform background checks before hiring?",
    ]


@pytest.mark.asyncio
async def test_naming_a_question_does_not_lift_the_guard(filled, user, answers_yes):
    """Ids are how a scope is narrowed, not how permission is given. An agent
    that listed a sheet and passed every id back would otherwise be holding a
    licence to overwrite it."""
    already = filled.form.questions[0].id
    outcome = await tools.answer(user, filled.id, tools.Scope(ids=(already,)))

    assert outcome.attempted == 0 and outcome.protected == 1
    assert "questions" not in answers_yes


@pytest.mark.asyncio
async def test_a_scope_of_nothing_but_answered_questions_is_not_nothing_matched(
    filled, user, answers_yes
):
    """"Nothing matched" sends the caller off to check the sheet names. The
    scope matched perfectly well; every question in it was already done."""
    already = filled.form.questions[0].id
    outcome = await tools.answer(user, filled.id, tools.Scope(ids=(already,)))
    assert not outcome.nothing_matched


@pytest.mark.asyncio
async def test_replacing_happens_when_it_is_asked_for(filled, user, answers_yes):
    already = filled.form.questions[0].id
    outcome = await tools.answer(
        user, filled.id, tools.Scope(ids=(already,)), replace_existing=True,
    )

    assert outcome.attempted == 1
    view = tools.inspect(user, filled.id)
    written = next(q for q in view["questions"] if q["id"] == already)
    assert written["answer"].startswith("Yes, this is documented")


@pytest.mark.asyncio
async def test_an_answer_written_here_is_protected_too(batch, user, answers_yes):
    """A reviewer's correction is worth at least what the file's own words are."""
    first = batch.form.questions[0].id
    tools.set_answer(user, batch.id, first, "A hand-written answer.")

    outcome = await tools.answer(user, batch.id)
    assert outcome.protected == 1

    view = tools.inspect(user, batch.id)
    kept = next(q for q in view["questions"] if q["id"] == first)
    assert kept["answer"] == "A hand-written answer."


@pytest.mark.asyncio
async def test_a_question_left_blank_on_purpose_is_not_answered_again(batch, user, answers_yes):
    first = batch.form.questions[0].id
    tools.blank_answer(user, batch.id, first)

    outcome = await tools.answer(user, batch.id)
    assert outcome.protected == 1
    assert tools.inspect(user, batch.id)["questions"][0]["blanked"]


# --- leaving blank, and taking it back --------------------------------------


def test_taking_back_a_blank_leaves_the_question_unanswered(batch, user):
    """Undo, not reverse. Storing something in its place would be a second
    decision made on the person's behalf."""
    first = batch.form.questions[0].id
    tools.blank_answer(user, batch.id, first)
    tools.blank_answer(user, batch.id, first, blank=False)

    question = tools.inspect(user, batch.id)["questions"][0]
    assert not question["blanked"] and not question["answer"]
    assert first not in batches.answers(batch.id)


def test_taking_back_a_blank_leaves_what_the_file_said(filled, user):
    """The file's own words live in the detected form, not in our answers, so
    forgetting ours cannot take them with it."""
    first = filled.form.questions[0].id
    tools.blank_answer(user, filled.id, first)
    tools.blank_answer(user, filled.id, first, blank=False)

    question = tools.inspect(user, filled.id)["questions"][0]
    assert question["existing"].startswith("Yes. The HR process")


@pytest.mark.asyncio
async def test_answering_twice_merges_rather_than_replaces(batch, user, answers_yes):
    ids = [question.id for question in batch.form.questions]
    await tools.answer(user, batch.id, tools.Scope(ids=tuple(ids[:2])))
    await tools.answer(user, batch.id, tools.Scope(ids=tuple(ids[2:])))
    assert tools.inspect(user, batch.id)["counts"]["answered"] == 4


@pytest.mark.asyncio
async def test_a_scope_that_matches_nothing_does_no_work(batch, user, answers_yes):
    outcome = await tools.answer(user, batch.id, tools.Scope(matching="nothing at all"))
    assert outcome.nothing_matched and "questions" not in answers_yes


@pytest.mark.asyncio
async def test_each_question_is_answered_in_its_own_language(user, tmp_path, answers_yes):
    opened = tools.open_form(user, shapes.header_below_preamble(tmp_path / "mixed.xlsx"))
    await tools.answer(user, opened.id)
    languages = {q.id: q.language for q in answers_yes["questions"]}
    assert "ar" in languages.values() and "en" in languages.values()


@pytest.mark.asyncio
async def test_answering_is_recorded_with_its_scope(batch, user, answers_yes):
    await tools.answer(user, batch.id, tools.Scope(matching="multi-factor"))
    [recorded] = [e for e in events.for_subject(batches.SUBJECT, batch.id)
                  if e.kind == events.BATCH_ANSWERED]
    assert recorded.payload["scope"] == "mentioning 'multi-factor'"
    assert recorded.payload["attempted"] == 1


@pytest.mark.asyncio
async def test_a_scope_that_matched_nothing_records_nothing(batch, user, answers_yes):
    """An event log is read to find out what happened. A request that did
    nothing did not happen."""
    await tools.answer(user, batch.id, tools.Scope(matching="quantum cryptography"))
    kinds = [e.kind for e in events.for_subject(batches.SUBJECT, batch.id)]
    assert kinds == [events.FORM_OPENED]


# --- style and revision ----------------------------------------------------


@pytest.mark.asyncio
async def test_answering_always_sends_the_same_prompt(batch, user, answers_yes):
    """There is no way to change how the drafter is asked.

    Wording instructions used to be injected into the drafting prompt. Measured
    on six real questions against rewriting a finished answer, injection
    followed the instruction just as well but cited a third fewer sources -- told
    to be brief, the drafter cites less -- and on one question dropped a caveat
    the sources required. So answering has one prompt, and `revise` does wording.
    """
    import inspect as inspection

    assert "style" not in inspection.signature(tools.answer).parameters
    await tools.answer(user, batch.id)
    assert "style" not in answers_yes


@pytest.mark.asyncio
async def test_revising_rewrites_rather_than_answering_again(batch, user, answers_yes, monkeypatch):
    """Re-running the pipeline would re-retrieve and re-review, so "make it
    shorter" could come back saying something different. It rewrites instead."""
    seen = {}

    async def fake_rewrite(answered, instruction, language=None):
        seen["instruction"] = instruction
        seen["kept_evidence"] = list(answered.evidence)
        revised = answered.model_copy(deep=True)
        revised.answer = "Shorter."
        return revised

    ids = [question.id for question in batch.form.questions]
    await tools.answer(user, batch.id, tools.Scope(ids=(ids[0],)))
    answers_yes.pop("questions", None)

    monkeypatch.setattr(tools.rewrite, "rewrite", fake_rewrite)
    outcome = await tools.revise(user, batch.id, "Make it shorter.")

    assert outcome.attempted == 1, "revising a blank question is answering it"
    assert seen["instruction"] == "Make it shorter."
    assert "questions" not in answers_yes, "the answering pipeline must not run again"
    assert tools.inspect(user, batch.id)["questions"][0]["answer"] == "Shorter."


@pytest.mark.asyncio
async def test_rewriting_keeps_the_citations(batch, user, answers_yes, monkeypatch):
    """The sources did not change, so the clause a reader would check has not
    moved either."""
    ids = [question.id for question in batch.form.questions]
    await tools.answer(user, batch.id, tools.Scope(ids=(ids[0],)))
    before = tools.inspect(user, batch.id)["questions"][0]["citations"]

    async def fake_rewrite(answered, instruction, language=None):
        revised = answered.model_copy(deep=True)
        revised.answer = "Shorter."
        return revised

    monkeypatch.setattr(tools.rewrite, "rewrite", fake_rewrite)
    await tools.revise(user, batch.id, "Shorter please.")
    assert tools.inspect(user, batch.id)["questions"][0]["citations"] == before


@pytest.mark.asyncio
async def test_revising_needs_an_instruction(batch, user, answers_yes):
    with pytest.raises(tools.ToolError, match="how the answers should change"):
        await tools.revise(user, batch.id, "   ")


# --- a person overruling the system ----------------------------------------


def test_a_hand_written_answer_is_attributed(batch, user):
    question = batch.form.questions[0]
    tools.set_answer(user, batch.id, question.id, "We use AES-256 throughout.")

    view = tools.inspect(user, batch.id)
    written = next(q for q in view["questions"] if q["id"] == question.id)
    assert written["answer"] == "We use AES-256 throughout."
    assert written["edited_by"] == user.email
    assert written["needs_review"] is False


def test_a_hand_written_answer_records_what_it_replaced(batch, user):
    question = batch.form.questions[0]
    tools.set_answer(user, batch.id, question.id, "First.")
    tools.set_answer(user, batch.id, question.id, "Second.")

    edits = [e for e in events.for_subject(batches.SUBJECT, batch.id)
             if e.kind == events.ANSWER_EDITED]
    assert edits[-1].payload["was"] == "First." and edits[-1].payload["now"] == "Second."


def test_setting_an_unknown_question_is_refused(batch, user):
    with pytest.raises(tools.ToolError, match="No question"):
        tools.set_answer(user, batch.id, "not-a-question", "x")


# --- filling ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_filling_writes_the_answers_into_a_copy(batch, user, answers_yes):
    await tools.answer(user, batch.id)
    filled = tools.fill(user, batch.id)

    assert filled.written == 4 and filled.intact
    assert filled.path.name == "vendor - answered.xlsx"
    assert batch.source_path.exists(), "the original is never consumed"

    from src import forms
    again = forms.detect(filled.path)
    assert again.answered_count == 4


@pytest.mark.asyncio
async def test_a_status_column_is_answered_in_the_files_own_words(
    dropdown_batch, user, answers_yes
):
    await tools.answer(user, dropdown_batch.id)
    filled = tools.fill(user, dropdown_batch.id)

    from src.forms.xlsx_package import Workbook
    with Workbook(filled.path) as workbook:
        sheet = workbook["Human Resources"]
        assert sheet.value(2, "C") == "Fully Compliant"
        assert sheet.value(2, "D").startswith("Yes, this is documented")


@pytest.mark.asyncio
async def test_an_evidence_column_is_left_blank_and_says_why(user, tmp_path, answers_yes):
    path = shapes.build(tmp_path / "ev.xlsx", [shapes.SheetSpec("Q", {
        "A1": "S.No", "B1": "Question", "C1": "Response", "D1": "Evidence",
        "A2": "1.0", "B2": "Does the vendor have documented security policies?",
        "A3": "2.0", "B3": "Does the vendor review those policies annually?",
        "A4": "3.0", "B4": "Are staff bound by non-disclosure agreements?",
    })])
    opened = tools.open_form(user, path)
    await tools.answer(user, opened.id)
    filled = tools.fill(user, opened.id)

    assert any("evidence" in why for why in filled.blank.values())
    assert all(not target.endswith("D2") for target in filled.skipped)


@pytest.mark.asyncio
async def test_unanswered_questions_are_not_written(batch, user, answers_yes):
    ids = [question.id for question in batch.form.questions]
    await tools.answer(user, batch.id, tools.Scope(ids=(ids[0],)))
    filled = tools.fill(user, batch.id)
    assert filled.written == 1


@pytest.mark.asyncio
async def test_filling_twice_reports_replacements(batch, user, answers_yes):
    await tools.answer(user, batch.id)
    tools.fill(user, batch.id)
    again = tools.fill(user, batch.id)
    assert again.created == 4 and not again.replaced, "each fill starts from the original"


def test_a_fill_that_writes_nothing_says_why(batch, user):
    """"Wrote 0 value(s) -- every other part of the file is untouched" is true
    and reads like success, which is the worst way to learn that nothing
    reached your file."""
    filled = tools.fill(user, batch.id)
    assert filled.written == 0
    assert "Nothing has been answered yet" in filled.because


def test_a_file_that_came_answered_needs_nothing_written(filled, user):
    """Not a failure and not the same message. The answers are in the file
    already -- that is what "nothing to write" means here, and telling somebody
    to go and answer something would send them to overwrite the very answers
    that made the write unnecessary."""
    report = tools.fill(user, filled.id)
    assert report.written == 0
    assert "the 2 answer(s) this questionnaire has came with the file" in report.because
    # And what to do next, which is the half a bare "nothing to write" leaves out.
    assert "2 question(s) are still blank" in report.because


@pytest.mark.asyncio
async def test_a_normal_fill_gives_no_reason(batch, user, answers_yes):
    await tools.answer(user, batch.id)
    assert tools.fill(user, batch.id).because == "", "a reason is only for a fill that wrote nothing"


@pytest.mark.asyncio
async def test_a_fill_with_every_answer_set_aside_says_so(batch, user, answers_yes):
    await tools.answer(user, batch.id)
    tools.set_questions(
        user, batch.id, [{"id": q.id, "skip": True} for q in batch.form.questions]
    )
    report = tools.fill(user, batch.id)
    assert report.written == 0 and "set aside" in report.because


def test_filling_without_the_original_says_so(batch, user):
    batch.source_path.unlink()
    with pytest.raises(tools.ToolError, match="no longer on the server"):
        tools.fill(user, batch.id)


@pytest.mark.asyncio
async def test_filling_is_recorded(batch, user, answers_yes):
    await tools.answer(user, batch.id)
    tools.fill(user, batch.id)
    kinds = [e.kind for e in events.for_subject(batches.SUBJECT, batch.id)]
    assert events.FILE_FILLED in kinds


# --- the whole path --------------------------------------------------------


@pytest.mark.asyncio
async def test_open_answer_correct_fill(user, tmp_path, answers_yes):
    """What a person actually does, in order."""
    opened = tools.open_form(user, shapes.status_and_comment(tmp_path / "isra.xlsx"))
    await tools.answer(user, opened.id)

    question = opened.form.questions[1]
    tools.set_answer(user, opened.id, question.id, "No, this is not in place.")

    filled = tools.fill(user, opened.id)
    assert filled.intact and filled.written == 8   # four questions, status + comment each

    from src.forms.xlsx_package import Workbook
    with Workbook(filled.path) as workbook:
        sheet = workbook["Human Resources"]
        assert sheet.value(3, "C") == "Non Compliant", "the correction reaches the dropdown too"
        assert sheet.value(3, "D") == "No, this is not in place."


def test_batches_are_listed_newest_first(user, tmp_path):
    for name in ("one", "two", "three"):
        tools.open_form(user, shapes.simple(tmp_path / f"{name}.xlsx"))
    listed = batches.recent(settings.default_team)
    assert [b["source_name"] for b in listed] == ["three.xlsx", "two.xlsx", "one.xlsx"]


# --- correcting a column ---------------------------------------------------
#
# Detection proposes; a person disposes. These are the operations behind the
# pickers in the report, and the properties that make a correction trustworthy:
# it moves every row on the sheet at once, it survives the answering that
# follows, and it says in the report that it happened.


def test_the_columns_offered_are_the_ones_that_will_be_written(dropdown_batch, user):
    [sheet] = tools.column_roles(user, dropdown_batch.id)
    assert sheet["sheet"] == "Human Resources"
    assert {c["column"]: c["role"] for c in sheet["columns"]} == {"C": "status", "D": "answer"}


def test_a_column_is_named_by_its_heading(dropdown_batch, user):
    """"column D" alone is not something a person can find in their spreadsheet."""
    [sheet] = tools.column_roles(user, dropdown_batch.id)
    assert {c["column"]: c["label"] for c in sheet["columns"]} == {
        "C": "Compliance Status", "D": "Additional Comments",
    }


def test_correcting_a_column_keeps_its_heading(dropdown_batch, user):
    """The heading belongs to the column, not to the role it was given. Losing
    it on correction left the picker offering an unrecognisable "column D"."""
    tools.set_column_role(user, dropdown_batch.id, "Human Resources", "D", "evidence")
    [sheet] = tools.column_roles(user, dropdown_batch.id)
    assert {c["column"]: c["label"] for c in sheet["columns"]}["D"] == "Additional Comments"


def test_correcting_a_column_moves_every_row_on_the_sheet(dropdown_batch, user):
    """A column is wrong for the whole sheet or not at all."""
    updated = tools.set_column_role(user, dropdown_batch.id, "Human Resources", "E", "answer")
    for question in updated["questions"]:
        columns = {t["role"]: t["id"].rsplit("!", 1)[1] for t in question["targets"]}
        assert columns["answer"].startswith("E"), columns


def test_a_column_can_be_taken_out_of_the_writing_entirely(dropdown_batch, user):
    updated = tools.set_column_role(user, dropdown_batch.id, "Human Resources", "C", "ignore")
    for question in updated["questions"]:
        assert "status" not in {t["role"] for t in question["targets"]}


def test_moving_the_answer_column_does_not_leave_the_old_one_behind(dropdown_batch, user):
    """A swap that kept both would write the answer into two columns."""
    updated = tools.set_column_role(user, dropdown_batch.id, "Human Resources", "E", "answer")
    for question in updated["questions"]:
        refs = [t["id"].rsplit("!", 1)[1] for t in question["targets"]]
        assert not any(ref.startswith("D") for ref in refs), refs


def test_a_status_column_picks_up_its_own_files_words(dropdown_batch, user):
    """The vocabulary is whatever *this* file's dropdown offers, so a status
    moved onto a different column reads that column's list, not the old one."""
    updated = tools.set_column_role(user, dropdown_batch.id, "Human Resources", "C", "status")
    [target] = [
        t for t in updated["questions"][0]["targets"] if t["role"] == "status"
    ]
    assert target["vocabulary"] == [
        "Fully Compliant", "Partially Compliant", "Non Compliant", "Not Applicable",
    ]


def test_the_report_says_a_column_was_corrected(dropdown_batch, user):
    """Left alone, the report went on saying "column D: answer" directly above a
    picker reading "evidence", and neither told the person which one fill would
    follow."""
    updated = tools.set_column_role(user, dropdown_batch.id, "Human Resources", "D", "evidence")
    [part] = [p for p in updated["parts"] if p["name"] == "Human Resources"]
    [finding] = [f for f in part["findings"] if f["subject"] == "column D"]
    assert finding["verdict"] == "evidence"
    assert user.email in finding["because"]
    assert "answer" in finding["because"], "it should still say what was read from the file"


def test_a_correction_survives_answering(dropdown_batch, user, answers_yes):
    """The order people actually work in is correct, then answer, then fill."""
    import asyncio

    tools.set_column_role(user, dropdown_batch.id, "Human Resources", "E", "answer")
    asyncio.run(tools.answer(user, dropdown_batch.id))
    filled = tools.fill(user, dropdown_batch.id)

    from src.forms.xlsx_package import Workbook
    with Workbook(filled.path) as workbook:
        sheet = workbook["Human Resources"]
        assert sheet.value(2, "E").startswith("Yes,")
        assert sheet.value(2, "D") == "", "the column it was moved off stays empty"


def test_a_role_that_cannot_be_written_is_refused(dropdown_batch, user):
    """Only three roles name somewhere to put an answer. Accepting 'question'
    here would silently make the sheet unanswerable."""
    with pytest.raises(tools.ToolError):
        tools.set_column_role(user, dropdown_batch.id, "Human Resources", "D", "question")
    with pytest.raises(tools.ToolError):
        tools.set_column_role(user, dropdown_batch.id, "Human Resources", "D", "nonsense")


def test_correcting_a_sheet_that_has_no_questions_is_refused(dropdown_batch, user):
    with pytest.raises(tools.ToolError):
        tools.set_column_role(user, dropdown_batch.id, "Score", "C", "answer")


def test_a_correction_is_recorded_against_the_person_who_made_it(dropdown_batch, user):
    tools.set_column_role(user, dropdown_batch.id, "Human Resources", "D", "evidence")
    kinds = [e.kind for e in events.for_subject(batches.SUBJECT, dropdown_batch.id)]
    assert events.ROLES_CORRECTED in kinds


def test_a_second_correction_does_not_credit_the_file_with_the_first(dropdown_batch, user):
    """Only detection's own reading is worth quoting back."""
    tools.set_column_role(user, dropdown_batch.id, "Human Resources", "D", "evidence")
    updated = tools.set_column_role(user, dropdown_batch.id, "Human Resources", "D", "answer")
    [part] = [p for p in updated["parts"] if p["name"] == "Human Resources"]
    [finding] = [f for f in part["findings"] if f["subject"] == "column D"]
    assert "read from the file" not in finding["because"]
    assert finding["because"] == f"set by {user.email}"
