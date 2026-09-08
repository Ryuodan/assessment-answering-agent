"""The four reading strategies, and the merge that makes the hybrid one.

The merge is where a hybrid can quietly go wrong -- a sheet counted twice, a
sheet lost between the two readings, the agent's verdict overwriting a better
one from the rules -- so most of this is about that.
"""

from __future__ import annotations

import pytest

from src import forms
from src.forms import reading as reading_module
from src.forms.reading import Reading, disagreements, read
from tests import forms_fixtures as shapes


def test_the_rules_alone_cost_nothing(tmp_path):
    result = read(shapes.status_and_comment(tmp_path / "hr.xlsx"), "rules")
    assert result.questions == 4
    assert (result.model_calls, result.tool_calls, result.tokens) == (0, 0, 0)


def test_a_strategy_that_does_not_exist_is_refused(tmp_path):
    with pytest.raises(ValueError, match="is not one of"):
        read(shapes.simple(tmp_path / "v.xlsx"), "vibes")


def test_the_hybrid_does_not_run_the_agent_when_the_rules_read_everything(tmp_path, monkeypatch):
    """The whole economy of it. A file the rules handle costs nothing extra,
    which is most files."""
    def fail(*args, **kwargs):
        raise AssertionError("the agent should not have been run")

    from src.agents import excel_agent
    monkeypatch.setattr(excel_agent, "read_workbook", fail)

    result = read(shapes.status_and_comment(tmp_path / "hr.xlsx"), "hybrid")
    assert result.questions == 4
    assert "the agent was not run" in " ".join(result.notes)


def test_a_word_file_falls_back_to_the_rules_under_an_agent_strategy(tmp_path):
    """Only spreadsheets have an agent. Dropping Word files from a comparison
    would make the totals incomparable between strategies."""
    path = tmp_path / "prose.docx"
    from docx import Document

    document = Document()
    document.add_paragraph("Q1. Is there an approved information security policy?")
    document.save(path)

    result = read(path, "agent")
    assert result.strategy == "agent"
    assert result.questions == 1
    assert "no agent for this format" in " ".join(result.notes)


def test_only_sheets_that_were_lost_are_offered_to_the_agent(tmp_path):
    """Not the hidden ones, and not the near-empty ones -- those are skipped on
    purpose, and paying an agent to confirm a decision we already made is the
    cost with none of the benefit."""
    form = forms.detect(shapes.status_and_comment(tmp_path / "hr.xlsx"))
    assert reading_module._lost(form) == set(), "the hidden lookup sheet is not 'lost'"


# --- the merge -------------------------------------------------------------


def _form(*parts):
    """A form of (sheet, kind, question count) triples."""
    from src.forms.model import DetectedForm, FormQuestion, Part, Role, Target

    form = DetectedForm(source_name="w.xlsx", format="xlsx")
    for name, kind, count in parts:
        form.parts.append(Part(name=name, kind=kind, questions=count))
        for row in range(2, 2 + count):
            form.questions.append(FormQuestion(
                id=f"{name}!{row}", text=f"Question on {name} row {row}",
                targets={Role.ANSWER: Target(id=f"{name}!C{row}", role=Role.ANSWER)},
            ))
    return form


def test_the_agents_reading_replaces_only_the_sheets_it_was_shown(tmp_path):
    rules = _form(("Good", "questions", 3), ("Lost", "no questions", 0))
    agent = _form(("Lost", "questions", 5))

    merged = reading_module._merge(rules, agent, {"Lost"})
    assert [(p.name, p.questions) for p in merged.parts] == [("Good", 3), ("Lost", 5)]
    assert len(merged.questions) == 8
    assert [q.id for q in merged.questions][:3] == ["Good!2", "Good!3", "Good!4"]


def test_a_sheet_the_agent_made_nothing_of_keeps_the_rules_verdict(tmp_path):
    """"No column holds a run of questions" says more than "the agent recorded
    no reading", and the person confirming the layout reads both."""
    rules = _form(("Lost", "no questions", 0))
    agent = _form(("Lost", "not read", 0))

    merged = reading_module._merge(rules, agent, {"Lost"})
    assert merged.parts[0].kind == "no questions"


def test_the_merge_never_counts_a_question_twice(tmp_path):
    rules = _form(("A", "questions", 2), ("B", "questions", 2))
    agent = _form(("A", "questions", 9), ("B", "questions", 9))

    # Only A was shown to the agent, so B must come through untouched.
    merged = reading_module._merge(rules, agent, {"A"})
    assert [(p.name, p.questions) for p in merged.parts] == [("A", 9), ("B", 2)]
    assert len(merged.questions) == 11
    assert len({q.id for q in merged.questions}) == 11


def test_the_merge_clears_a_no_questions_warning_it_has_disproved(tmp_path):
    rules = _form(("Lost", "no questions", 0))
    rules.warnings.append("No questions were found. The sheets were read as: Lost (no questions)")
    agent = _form(("Lost", "questions", 4))

    merged = reading_module._merge(rules, agent, {"Lost"})
    assert merged.warnings == []


# --- reporting the difference ----------------------------------------------


def test_disagreements_are_reported_sheet_by_sheet():
    """Counts alone hide the case that matters -- two strategies finding the
    same number of questions, in different places."""
    readings = {
        "rules": Reading(_form(("A", "questions", 3), ("B", "no questions", 0)), "rules"),
        "agent": Reading(_form(("A", "questions", 1), ("B", "questions", 2)), "agent"),
    }
    lines = disagreements(readings)
    assert lines == ["A: rules 3, agent 1", "B: rules 0, agent 2"]


def test_agreement_reports_nothing():
    readings = {
        "rules": Reading(_form(("A", "questions", 3)), "rules"),
        "hybrid": Reading(_form(("A", "questions", 3)), "hybrid"),
    }
    assert disagreements(readings) == []


def test_a_sheet_only_one_strategy_saw_counts_as_a_disagreement():
    """It is the most important kind. A whole sheet appearing under one reading
    and not the other is the difference worth opening the file over."""
    readings = {
        "rules": Reading(_form(("A", "questions", 3)), "rules"),
        "agent": Reading(_form(("A", "questions", 3), ("B", "questions", 7)), "agent"),
    }
    assert disagreements(readings) == ["B: rules 0, agent 7"]


def test_a_batch_records_which_strategy_read_the_file(tmp_path):
    """The choice is a cost decision, and a bill nobody can attribute is not a
    decision anyone can revisit."""
    from src import batches, events, identity, tools

    user = identity.local_user()
    batch = tools.open_form(user, shapes.status_and_comment(tmp_path / "hr.xlsx"), strategy="rules")
    [event] = events.for_subject(batches.SUBJECT, batch.id)
    assert event.payload["strategy"] == "rules"
    assert event.payload["tokens"] == 0


def test_the_strategy_defaults_to_the_configured_one(tmp_path, monkeypatch):
    from src import identity, tools
    from src.config import settings
    from src.forms import reading as module

    seen = {}

    def note(path, strategy):
        seen["strategy"] = strategy
        return module.Reading(forms.detect(path), strategy)

    monkeypatch.setattr(module, "read", note)
    monkeypatch.setattr(settings, "detection_strategy", "assisted")
    tools.open_form(identity.local_user(), shapes.simple(tmp_path / "v.xlsx"))
    assert seen["strategy"] == "assisted"


# --- the floor under the agent ---------------------------------------------
#
# The agent generalises best and its characteristic mistake is a quiet
# omission: on one real workbook it read six sheets of seven, decided it was
# finished, and dropped a sheet of five questions without saying so. `guarded`
# runs the rules as well and lets no sheet come back for less.


def test_a_sheet_the_agent_read_for_less_keeps_the_rules_reading():
    agent = _form(("Kept", "questions", 9), ("Dropped", "no questions", 0))
    rules = _form(("Kept", "questions", 3), ("Dropped", "questions", 5))

    floored, rescued = reading_module._floor(agent, rules)
    assert [(p.name, p.questions) for p in floored.parts] == [("Kept", 9), ("Dropped", 5)]
    assert rescued == {"Dropped"}
    assert len(floored.questions) == 14


def test_a_sheet_the_agent_read_for_more_is_kept():
    """Reading a form is not something the rules are authoritative about, and
    the agent finding rows they missed is the reason to run it at all. Only
    'fewer' is overruled."""
    agent = _form(("A", "questions", 64))
    rules = _form(("A", "questions", 63))

    floored, rescued = reading_module._floor(agent, rules)
    assert floored.parts[0].questions == 64
    assert rescued == set()


def test_a_sheet_the_agent_never_mentioned_comes_back_from_the_rules():
    """The same omission by a different route: it recorded no reading at all,
    so no part came back, and the sheet would simply not exist."""
    agent = _form(("A", "questions", 3))
    rules = _form(("A", "questions", 3), ("Forgotten", "questions", 7))

    floored, rescued = reading_module._floor(agent, rules)
    assert [(p.name, p.questions) for p in floored.parts] == [("A", 3), ("Forgotten", 7)]
    assert rescued == {"Forgotten"}


def test_the_floor_never_counts_a_question_twice():
    agent = _form(("A", "questions", 2), ("B", "questions", 4))
    rules = _form(("A", "questions", 5), ("B", "questions", 1))

    floored, _ = reading_module._floor(agent, rules)
    assert len(floored.questions) == 9
    assert len({q.id for q in floored.questions}) == 9


def test_a_sheet_both_skipped_stays_skipped():
    """A cover page is not rescued into a questionnaire by being run twice."""
    agent = _form(("Cover", "no questions", 0))
    rules = _form(("Cover", "no questions", 0))

    floored, rescued = reading_module._floor(agent, rules)
    assert floored.questions == [] and rescued == set()


def test_the_floor_clears_a_no_questions_warning_it_has_disproved():
    agent = _form(("A", "no questions", 0))
    agent.warnings.append("No questions were found. The sheets were read as: A (no questions)")
    rules = _form(("A", "questions", 6))

    floored, _ = reading_module._floor(agent, rules)
    assert floored.warnings == []


def test_guarded_says_which_sheets_the_rules_had_to_rescue(tmp_path, monkeypatch):
    """Named, not just counted. A sheet the agent lost is the thing a person
    would want to look at in the file."""
    from src.agents import excel_agent

    def pretend(path, **kwargs):
        return _form(("Human Resources", "no questions", 0)), excel_agent.Run()

    monkeypatch.setattr(excel_agent, "read_workbook", pretend)
    result = read(shapes.status_and_comment(tmp_path / "hr.xlsx"), "guarded")

    assert result.questions == 4, "the rules' reading came through"
    assert "'Human Resources'" in " ".join(result.notes)


def test_guarded_is_what_the_application_uses_by_default():
    """Chosen deliberately: the agent generalises best, and this is the agent
    with its one measured failure removed.

    Read off the field rather than off `settings`, because the suite pins the
    live value to `rules` -- the default runs an agent against a real model,
    and a test that did that would be slow, billed and nondeterministic.
    """
    from src.config import Settings

    assert Settings.model_fields["detection_strategy"].default == "guarded"
    assert "guarded" in reading_module.STRATEGIES
