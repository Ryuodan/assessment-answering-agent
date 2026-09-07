"""The Excel agent: its tools, its budget, and what it does with what it recorded.

The model is stubbed out. What is tested is everything the agent's correctness
actually rests on -- that its tools tell it the truth about the file, that they
are bounded, that a reading it records goes through the same checking as any
other, and that a run which overruns still yields the sheets it did read. A
test that a language model reads a spreadsheet correctly would be a test of the
model; these are tests of the machine around it.
"""

from __future__ import annotations

import pytest

from src.agents import excel_agent
from src.forms import llm_layout
from src.forms.xlsx_package import Workbook
from tests import forms_fixtures as shapes


@pytest.fixture
def book(tmp_path):
    with Workbook(shapes.status_and_comment(tmp_path / "hr.xlsx")) as workbook:
        yield workbook


@pytest.fixture
def tools(book):
    """The tools, and the run they write into, bound to one workbook."""
    run = excel_agent.Run()
    return {tool.__name__: tool for tool in excel_agent._make_tools(book, run)}, run


# --- what the tools tell it ------------------------------------------------


def test_it_is_shown_only_the_sheets_it_can_act_on(tools):
    """The hidden lookup sheet holds this file's dropdown values and is not a
    questionnaire. Listing it would invite a reading of it."""
    (tool, _run) = tools
    listed = tool["list_sheets"]()
    assert "Human Resources" in listed
    assert "Score" not in listed


def test_looking_at_a_sheet_shows_its_grid_and_its_columns(tools):
    (tool, _run) = tools
    seen = tool["look_at"]("Human Resources")
    assert "row 1 |" in seen
    assert "Compliance Status" in seen
    assert "dropdown [Fully Compliant" in seen, "the status column has to be recognisable"


def test_a_sheet_it_has_already_recorded_is_not_described_again(tools):
    """Paying for the same screenful twice is how the first eighteen-sheet
    workbook ran out of steps."""
    (tool, _run) = tools
    tool["record"]("Human Resources", True, 1, "B", "C=status, D=answer", "clear")
    assert "already recorded" in tool["look_at"]("Human Resources")


def test_a_sheet_name_that_does_not_exist_is_a_message_not_a_crash(tools):
    (tool, _run) = tools
    assert "no visible sheet" in tool["look_at"]("Sheet42")
    assert "no visible sheet" in tool["read_rows"]("Sheet42", 1)
    assert "no visible sheet" in tool["find_rows"]("Sheet42", "policy")


def test_a_sheet_name_arriving_quoted_or_miscased_still_resolves(tools):
    """Names come back through a model and arrive untidy. Refusing them costs a
    retry, and a retry costs a call."""
    (tool, _run) = tools
    assert "row 1 |" in tool["look_at"]("'human resources'")


def test_reading_rows_returns_a_bounded_window(tmp_path):
    """A confused agent must not be able to pull a 30,000-row sheet into the
    conversation one window at a time."""
    cells = {f"B{row}": f"Question {row}" for row in range(1, 400)}
    path = shapes.build(tmp_path / "long.xlsx", [shapes.SheetSpec("Long", cells)])
    with Workbook(path) as workbook:
        tool = {t.__name__: t for t in excel_agent._make_tools(workbook, excel_agent.Run())}
        window = tool["read_rows"]("Long", 100)

    assert len(window.splitlines()) == excel_agent.WINDOW_ROWS
    assert "row 100 |" in window


def test_reading_past_the_end_of_a_sheet_says_where_it_ends(tools):
    (tool, _run) = tools
    assert "the sheet ends at" in tool["read_rows"]("Human Resources", 900)


def test_finding_rows_reports_where_the_text_is(tools):
    (tool, _run) = tools
    found = tool["find_rows"]("Human Resources", "training")
    assert "row 3, column B" in found


def test_finding_nothing_says_so(tools):
    (tool, _run) = tools
    assert "No cell" in tool["find_rows"]("Human Resources", "quantum cryptography")


def test_every_tool_call_is_counted(tools):
    (tool, run) = tools
    tool["list_sheets"]()
    tool["look_at"]("Human Resources")
    assert run.calls == 2
    assert run.steps == ["list_sheets", "look_at('Human Resources')"]


# --- recording -------------------------------------------------------------


def test_recording_says_what_is_left_to_do(tools):
    (tool, _run) = tools
    assert "Every visible sheet now has a reading" in tool["record"](
        "Human Resources", True, 1, "B", "C=status, D=answer", "clear"
    )


def test_a_recorded_reading_is_kept_against_the_sheets_real_name(tools):
    (tool, run) = tools
    tool["record"]("'human resources'", True, 1, "B", "C=status", "clear")
    assert set(run.readings) == {"Human Resources"}


def test_column_roles_are_read_out_of_one_string(tools):
    """A flat string rather than a list of objects: nested arguments are where
    tool calls go wrong most often, and this is the argument filled in on every
    single call."""
    parsed = excel_agent._parse_roles("A=number, C=status; D = answer")
    assert [(c.column, c.role) for c in parsed] == [
        ("A", "number"), ("C", "status"), ("D", "answer"),
    ]


def test_an_unparseable_role_is_dropped_rather_than_failing_the_call(tools):
    """Two of three columns understood is worth more than a refusal."""
    parsed = excel_agent._parse_roles("A=number, C=freetext, nonsense, D=answer")
    assert [c.column for c in parsed] == ["A", "D"]


# --- from recordings to questions ------------------------------------------


def _record(run, sheet="Human Resources", **overrides):
    fields = {
        "is_questionnaire": True, "header_row": 1, "question_column": "B",
        "columns": excel_agent._parse_roles("C=status, D=answer"),
        "reason": "Questions in column B under row 1.",
    }
    fields.update(overrides)
    run.readings[sheet] = llm_layout.SheetReading(**fields)


def test_a_reading_becomes_the_same_questions_the_rules_would_have_made(book, tmp_path):
    """The point of sharing `read_sheet`: an agent-read file is answered,
    filled and written back by code that cannot tell where the reading came
    from."""
    from src import forms

    run = excel_agent.Run()
    _record(run)
    part, questions = excel_agent._read(book, book["Human Resources"], run)

    rules = forms.detect(shapes.status_and_comment(tmp_path / "same.xlsx"))
    assert [q.id for q in questions] == [q.id for q in rules.questions]
    assert [sorted(t.id for t in q.targets.values()) for q in questions] == \
           [sorted(t.id for t in q.targets.values()) for q in rules.questions]


def test_a_sheet_the_agent_called_not_a_questionnaire_is_skipped_with_its_reason(book):
    run = excel_agent.Run()
    _record(run, is_questionnaire=False, reason="A rating scale, not questions.")
    part, questions = excel_agent._read(book, book["Human Resources"], run)

    assert questions == []
    assert "rating scale" in part.findings[0].because
    assert not part.findings[0].confident


def test_a_sheet_the_agent_never_reached_says_so(book):
    """Distinct from "it read this and found nothing": one is a budget that ran
    out and the other is a judgement, and a person choosing between strategies
    needs to tell them apart."""
    run = excel_agent.Run(stopped_early=True)
    part, questions = excel_agent._read(book, book["Human Resources"], run)
    assert part.kind == "not read"
    assert "stopped before" in part.findings[0].because


def test_an_agents_reading_goes_through_the_same_checking_as_the_fallback(book):
    """It cannot name a column the sheet does not have, any more than the
    single-call fallback can."""
    run = excel_agent.Run()
    _record(run, question_column="Z")
    part, questions = excel_agent._read(book, book["Human Resources"], run)
    assert questions == []
    assert part.kind == "no questions"


def test_the_hidden_sheet_is_skipped_without_consulting_any_reading(book):
    run = excel_agent.Run()
    part, questions = excel_agent._read(book, book["Score"], run)
    assert part.kind == "hidden"


def test_findings_say_the_agent_produced_them(book):
    """A report over a mixed set of files has to say which reader read what."""
    run = excel_agent.Run()
    _record(run)
    part, _ = excel_agent._read(book, book["Human Resources"], run)
    assert "Excel agent" in part.findings[0].because


# --- the budget ------------------------------------------------------------


def test_the_budget_grows_with_the_workbook():
    """A fixed budget was the first thing to break: 60 steps ran out halfway
    through an eighteen-sheet workbook and the six sheets it never reached came
    back empty against 53 questions the rules had found."""
    assert excel_agent.budget(18) > excel_agent.budget(2)
    assert excel_agent.budget(18) >= excel_agent.STEPS_PER_SHEET * 18


def test_a_small_workbook_still_gets_room_to_recover():
    assert excel_agent.budget(1) >= excel_agent.STEPS_FLOOR


# --- being pointed at part of a workbook -----------------------------------


def test_it_can_be_shown_only_some_sheets(tmp_path):
    """What the hybrid strategy pays for: the rules keep the sheets they read,
    and the agent is shown only the ones they lost."""
    with Workbook(shapes.status_and_comment(tmp_path / "hr.xlsx")) as workbook:
        run = excel_agent.Run()
        tool = {t.__name__: t for t in excel_agent._make_tools(workbook, run, only=set())}
        assert tool["list_sheets"]() == "(no sheets)"
        assert "no visible sheet" in tool["look_at"]("Human Resources")


def test_a_second_round_is_asked_about_the_sheets_it_forgot(tmp_path, monkeypatch):
    """On the Zain form the agent recorded five sheets of seven and stopped --
    not out of budget, just finished -- and the two it never mentioned held
    twelve questions between them."""
    rounds: list[set] = []

    def pretend(workbook, run, path, sheets, tools, steps):
        rounds.append(set(sheets))
        if len(rounds) == 1:
            _record(run, "Human Resources")          # one of two, then "done"
        else:
            _record(run, "Second")

    monkeypatch.setattr(excel_agent, "_round", pretend)
    path = shapes.build(tmp_path / "two.xlsx", [
        shapes.SheetSpec("Human Resources", {"A1": "#", "B1": "Question", "B2": "Is there a policy?"}),
        shapes.SheetSpec("Second", {"A1": "#", "B1": "Question", "B2": "Is there another?"}),
    ])
    excel_agent.read_workbook(path)

    assert rounds[0] == {"Human Resources", "Second"}
    assert rounds[1] == {"Second"}, "the second round asks only about what is missing"


def test_a_run_that_stopped_early_is_not_asked_again(tmp_path, monkeypatch):
    """It ran out of steps rather than forgetting, so a second round would run
    out in the same place and bill for it twice."""
    rounds = []

    def pretend(workbook, run, path, sheets, tools, steps):
        rounds.append(set(sheets))
        run.stopped_early = True

    monkeypatch.setattr(excel_agent, "_round", pretend)
    excel_agent.read_workbook(shapes.simple(tmp_path / "v.xlsx"))
    assert len(rounds) == 1


def test_the_conversation_is_pruned_once_it_grows(tmp_path):
    """Every screenful looked at is resent with every later turn. Clearing old
    tool results is safe here only because a reading is recorded into the run
    the moment it is made, so the answer never lives in the transcript."""
    assert excel_agent.CONTEXT_TRIGGER <= 20_000, \
        "a threshold above one request's size never fires"


def test_the_budget_has_a_ceiling(monkeypatch):
    """The budget is derived from the file, and these files arrive from other
    companies. A workbook with two hundred sheets must not be able to buy
    itself an unbounded run at our expense."""
    assert excel_agent.budget(500) == excel_agent.STEPS_CEILING

    from src.config import settings
    monkeypatch.setattr(settings, "excel_agent_max_steps", 10_000)
    assert excel_agent.budget(1) == excel_agent.STEPS_CEILING
