"""The answer memory: what supersedes what, and what needs a person.

The distinction under test is the one that decides whether somebody gets
interrupted. A later answer that says more than an earlier one is an ordinary
update and should pass silently. Two answers that disagree with nothing to say
which is current is two people believing different things, and no rule here can
pick a winner.
"""

from __future__ import annotations

from src.memory import Entry, compare, disagree, verdict_of


def entry(eid: str, answer: str, *, question: str = "Do you have a DPO?", on: str = "") -> Entry:
    return Entry(entry_id=eid, question=question, answer=answer, approved_on=on)


# --- reading a verdict -------------------------------------------------------


def test_a_verdict_is_read_from_the_opening_word_only():
    assert verdict_of("Yes, we encrypt data at rest.") == "yes"
    assert verdict_of("No.") == "no"
    assert verdict_of("Fully Compliant, yes — reviewed annually") == "yes"
    assert verdict_of("Not Implemented") == "no"


def test_an_answer_with_no_verdict_has_none():
    """ "The retention period is twelve months" is an answer and not a yes."""
    assert verdict_of("The retention period is twelve months.") == ""
    assert verdict_of("") == ""


def test_a_caveat_after_a_yes_is_still_a_yes():
    """Reading the whole text for negations turns every qualified yes into a no."""
    assert verdict_of("Yes, although multi-factor is not yet on every system.") == "yes"
    assert not disagree("Yes.", "Yes, although MFA is not yet everywhere.")


# --- supersession ------------------------------------------------------------


def test_a_later_answer_that_says_more_supersedes_quietly():
    """The case that must not raise a conflict: nothing disagrees, the newer one
    simply reflects where things now stand."""
    finding = compare(
        entry("new", "Yes, and audited quarterly since March.", on="2026-09-09"),
        entry("old", "Yes.", on="2025-01-01"),
        same_question=True,
    )
    assert finding.kind == "supersedes"
    assert not finding.needs_a_person


def test_a_later_answer_that_reverses_the_position_supersedes_too():
    """Changing our answer is allowed, and dates are how that is expressed."""
    finding = compare(
        entry("new", "No, the role was retired.", on="2026-09-09"),
        entry("old", "Yes.", on="2025-01-01"),
        same_question=True,
    )
    assert finding.kind == "supersedes"
    assert not finding.needs_a_person


def test_an_older_answer_arriving_late_does_not_displace_a_newer_one():
    finding = compare(
        entry("import", "Yes.", on="2024-01-01"),
        entry("current", "No, the role was retired.", on="2026-09-09"),
        same_question=True,
    )
    assert finding.kind == "superseded_by"


# --- conflict ----------------------------------------------------------------


def test_two_undated_answers_that_disagree_need_a_person():
    """Both real, from the historical import, and nothing says which is current.

    This is not hypothetical: the imported memory holds "yes -- under Data
    Privacy and Data Officer" and "we do not have a DPO, but it falls under the
    Cybersecurity team" for the same question.
    """
    finding = compare(
        entry("a", "Yes — under Data Privacy"), entry("b", "No, it falls under Cybersecurity"), same_question=True
    )
    assert finding.kind == "conflict"
    assert finding.needs_a_person


def test_an_undated_answer_never_displaces_a_dated_one():
    """The 698 imported answers carry no date. They must not overrule an answer
    somebody actually approved."""
    finding = compare(
        entry("import", "Yes."),
        entry("approved", "No.", on="2026-09-09"),
        same_question=True,
    )
    assert finding.kind == "superseded_by"


# --- what is not news --------------------------------------------------------


def test_the_same_answer_twice_is_not_news():
    assert compare(entry("a", "Yes, we do."), entry("b", "yes, we do."), same_question=True) is None


def test_a_different_question_is_never_compared():
    """Similarity proposes a pair; a model confirms it. Without that confirmation
    nothing is marked -- an incident-response drill and a business-continuity
    drill embed at 0.79 and are different controls."""
    assert compare(entry("a", "Yes."), entry("b", "No."), same_question=False) is None


def test_an_entry_stands_until_something_supersedes_it():
    one = entry("a", "Yes.")
    assert one.stands
    one.superseded_by = "b"
    assert not one.stands
