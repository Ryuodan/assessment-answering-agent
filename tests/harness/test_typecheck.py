"""The mypy baseline: new errors fail, fixed errors must leave, line numbers do not matter."""

from __future__ import annotations

from collections import Counter

from harness.typecheck import TypeError_, judge


def error(
    path: str = "src/a.py", line: int = 1, code: str = "type-arg", message: str = "Missing type parameters"
) -> TypeError_:
    return TypeError_(path=path, line=line, code=code, message=message)


def test_an_error_in_the_baseline_passes_even_after_its_line_moves():
    baseline = Counter([error(line=10).key])
    assert judge([error(line=99)], baseline) == []


def test_a_new_error_fails_at_its_file_and_line_with_a_fix():
    [violation] = judge([error(path="src/b.py", line=7)], Counter())
    assert (violation.rule, violation.path, violation.line) == ("TYPES-NEW", "src/b.py", 7)
    assert "never for new ones" in violation.fix


def test_a_second_copy_of_a_baselined_error_is_new():
    baseline = Counter([error().key])
    [violation] = judge([error(line=1), error(line=2)], baseline)
    assert violation.rule == "TYPES-NEW"


def test_a_fixed_error_must_be_removed_from_the_baseline():
    [violation] = judge([], Counter([error().key]))
    assert violation.rule == "TYPES-FIXED"
    assert "poe types-baseline" in violation.fix


def test_line_numbers_inside_messages_do_not_break_matching():
    before = error(code="no-redef", message='Name "x" already defined on line 12')
    after = error(code="no-redef", message='Name "x" already defined on line 40')
    assert judge([after], Counter([before.key])) == []
