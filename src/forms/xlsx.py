"""Understanding a questionnaire workbook: which sheets, which columns, which rows.

Nothing here guesses silently. Every decision becomes a `Finding` with its
reason, and the ones that are a best guess rather than a clear read say so, so
the confirmation step can put those in front of a person first.

The layouts these files actually use, and what each one costs:

* The header is not on row 1. One sample puts it on row 8, under a title, a
  vendor name and a date.
* Section headings share a column with questions, so "is this a question?"
  cannot be answered by "is this cell non-empty?".
* An answer is usually two values -- a status chosen from the file's own
  dropdown, and a comment in prose -- and the vocabularies disagree between
  files.
* Some columns belong to whoever *sent* the questionnaire. Writing in one would
  be worse than leaving the question blank, so ownership is checked before
  anything else.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from src.config import settings
from src.forms.model import DetectedForm, Finding, FormQuestion, Part, Role, Target, WriteReport
from src.forms.xlsx_package import Sheet, Workbook, column_number

logger = logging.getLogger(__name__)

# --- what headings mean ----------------------------------------------------
# Substring matches against a lower-cased heading. Order within a role does not
# matter; order *between* roles does, and lives in `_role_for`.

_NUMBER = ("s.no", "s. no", "sr.no", "sr. no", "no.", "s#", "#", "serial", "item no")
_NUMBER_EXACT = ("id", "ref", "no", "sn", "s/n", "sl", "q.no", "q. no", "q no", "code", "رقم")
"""Reference-column headings matched whole, never as a substring.

`ID` is the commonest heading for the column holding `GE-01`, `IAM-01`, `GQ7`,
and it has to be recognised: without it there is no numbering column, and
`_looks_like_a_question` falls back to "ends in a question mark, or runs past
fifty characters". That cost a real workbook two whole readings -- nine
questions on a sheet whose questions are `Organisation name` and `Email
address`, and one more, `Do you maintain an incident register`, which is
thirty-six characters and ends in a full stop.

Matched exactly because these are too short to be safe as substrings: `id`
appears inside `Identity and Access Management`, and `no` inside `Notes`.
"""
_QUESTION = (
    "question", "inquiry", "requirement", "control", "due diligence", "criteria",
    "checklist", "assessment area", "سؤال", "استبيان", "المتطلب",
)
_ANSWER = (
    "response", "answer", "comment", "remark", "detail", "reply", "explanation",
    "narrative", "notes", "إجابة", "الرد", "ملاحظات",
)
_STATUS = (
    "status", "compliance", "complaince", "implementation", "implemented",
    "yes or no", "yes/no", "conformity", "الامتثال", "الحالة",
)
_EVIDENCE = ("evidence", "attachment", "attach", "proof", "supporting", "artefact", "artifact", "دليل")
_CONTEXT = ("domain", "section", "category", "type", "area", "cid", "reference", "clause", "standard")

# "To be filled by ..." / "To be updated by ...". Whose column this is decides
# everything else about it, so it is tested before any other rule.
_OWNERSHIP = re.compile(
    r"\b(?:to\s+be\s+)?(?:filled|completed|updated|answered|provided)\s*(?:in\s*)?by\s+(?:the\s+)?(.{2,60})",
    re.I,
)
# Names we answer under. A column addressed to any of these is ours to write in.
_US = ("third party", "third-party", "3rd party", "vendor", "supplier", "service provider", "contractor")

_ARABIC = re.compile(r"[؀-ۿ]")
# 1 · 1.0 · A.1 · A.3.a · GI.1.1 · DP. 1.6 · REQ-001 · E-A01, but not '(A)' or
# 'Part 2:', which head sections in the very same column.
#
# Two rules do the separating. It must contain a digit, which rules out the
# bare-letter section markers; and any letters must be upper case, which rules
# out an ordinary word followed by a number.
_ITEM_NUMBER = re.compile(
    r"^(?=[^\d]*\d)\(?\s*(?:[A-Z]{1,4}[-. ]?\s*)?[0-9A-Z]{1,4}"
    r"(?:\s*[.\-]\s*[0-9A-Za-z]{1,3})*\s*[.\):]?\s*$"
)


def _label(heading: str) -> str:
    """A heading without the guidance printed under it.

    These forms write the column name and then explain it in the same cell --
    "Compliance Code", newline, "(Give a compliance level code that best
    suits...)". Matching words against the whole cell put four of one workbook's
    columns in the wrong role, because the explanations mention 'applicable' and
    'compliance' where the labels do not.
    """
    first = heading.splitlines()[0] if heading else ""
    return " ".join(first.split("(")[0].split()).lower()


def _has_arabic(text: str) -> bool:
    return bool(_ARABIC.search(text))


def _language(text: str) -> str:
    """Which language a question is in.

    Counted rather than merely detected: these sheets mix an Arabic question
    into an English form and a Latin acronym into an Arabic one, so the test is
    which script carries the sentence, not which appears first.
    """
    arabic = len(_ARABIC.findall(text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return "ar" if arabic > latin else "en"


def _matches(heading: str, needles: tuple[str, ...]) -> str:
    for needle in needles:
        if needle in heading:
            return needle
    return ""


def _owner(heading: str) -> str | None:
    """Who a 'to be filled by ...' heading addresses, or None if it says nothing."""
    match = _OWNERSHIP.search(heading)
    return match.group(1).strip(" .:()") if match else None


def _role_for(heading: str, *, has_dropdown: bool) -> tuple[Role, str]:
    """A column's role, and the evidence for it.

    Ownership first: 'Compliance (To be updated by BAB)' reads as a status
    column by every other rule, and filling it in would put our words in the
    assessing bank's own column.
    """
    full = " ".join(heading.split()).lower()
    text = _label(heading)
    if not text:
        return (Role.STATUS, "a dropdown, with no heading") if has_dropdown else (Role.IGNORE, "no heading")

    owner = _owner(full)
    if owner is not None and not any(name in owner for name in _US):
        return Role.THEIRS, f"addressed to {owner!r}"

    if _matches(text, _EVIDENCE):
        return Role.EVIDENCE, f"heading mentions {_matches(text, _EVIDENCE)!r}"
    if has_dropdown:
        return Role.STATUS, "the column has a dropdown"
    if _matches(text, _STATUS):
        return Role.STATUS, f"heading mentions {_matches(text, _STATUS)!r}"
    if _matches(text, _QUESTION):
        return Role.QUESTION, f"heading mentions {_matches(text, _QUESTION)!r}"
    if _matches(text, _ANSWER):
        return Role.ANSWER, f"heading mentions {_matches(text, _ANSWER)!r}"
    if text in _NUMBER or text in _NUMBER_EXACT or _matches(text, _NUMBER):
        return Role.NUMBER, "heading is a numbering column"
    if _matches(text, _CONTEXT):
        return Role.CONTEXT, f"heading mentions {_matches(text, _CONTEXT)!r}"
    return Role.IGNORE, "heading was not recognised"


# --- finding the header ----------------------------------------------------

HEADER_SEARCH_ROWS = 25
"""How far down to look. The deepest header in the samples is on row 8."""

LONG_TEXT = 40
"""Characters that make a cell prose rather than a label."""

MIN_NUMBERED_ROWS = 4
"""Question rows needed before an unnumbered sheet counts as a questionnaire."""

MIN_QUESTION_ROWS = 3
"""Fewer than this and a column of sentences is a legend, not a questionnaire.

Two workbooks carry a 'Compliance Levels' sheet explaining what each rating
means, in prose, in a column, under a heading. It reads exactly like a
questionnaire until you count the rows.
"""


HEADING_LABEL_LIMIT = 70
"""Characters a column label can run to before it is a sentence, not a label."""


def _header_score(values: dict[str, str]) -> tuple[int, int]:
    """How much a row reads as column headings: (score, columns recognised).

    Both numbers matter, and the count is the one that stops a *question* being
    taken for a header. One sheet asks 'If "Yes", please provide the information
    below, and attach a copy of the certificate' -- the word 'attach' scored it
    as an evidence heading, so everything above that row was discarded as
    preamble and the sheet's forty-one questions vanished. A real header row
    labels several columns at once; a question labels none.
    """
    score = 0
    recognised = 0
    for text in values.values():
        if len(_label(text)) > HEADING_LABEL_LIMIT:
            continue
        role, _ = _role_for(text, has_dropdown=False)
        if role in (Role.QUESTION, Role.ANSWER, Role.STATUS, Role.EVIDENCE, Role.THEIRS):
            score += 2
            recognised += 1
        elif role in (Role.NUMBER, Role.CONTEXT):
            score += 1
            recognised += 1
    return score, recognised


@dataclass(frozen=True)
class Layout:
    """Where the questions are on one sheet."""

    header_row: int
    """Rows at or above this are preamble. 0 when the sheet has no headings."""

    question_column: str
    headed: bool
    """False when the layout was inferred from shape alone, with no headings.

    Everything derived from a headless layout is a proposal rather than a
    reading, and is marked for confirmation.
    """


def _find_headless_layout(sheet: Sheet) -> Layout | None:
    """A sheet whose questions start straight after a section title.

    One supplier form runs `A.1 | Does the company have ... | Yes/No` with no
    column headings anywhere -- the only thing naming the answer column is its
    position. Refusing to read those sheets lost about a hundred questions, and
    guessing them silently would be worse, so they are read and every finding
    from them is marked unconfident.
    """
    # The numbering column settles it where there is one: questions sit
    # immediately to its right. Counting prose instead is not stable once the
    # form has been answered -- fill the answer column and it holds *more* long
    # text than the questions do, because plenty of real questions are as short
    # as 'Company Name:'. Detection has to give the same reading before and
    # after answering, or re-opening a half-finished file moves every target.
    numbering = next(
        (
            column for column in sheet.columns
            if sum(1 for row in sheet.rows if _ITEM_NUMBER.match(sheet.value(row, column).strip()))
            >= MIN_QUESTION_ROWS
        ),
        None,
    )
    # A row that fails to qualify as a header can still name its columns, and
    # that name is the only thing in the file that survives being answered.
    # One workbook heads its two columns `Queations` and `Answer`: a single
    # typo away from a header row, so the whole sheet is read headless -- and
    # once the answer column has been filled it holds 32 rows of prose against
    # the questions' 30, takes their place, and re-opening the half-finished
    # file finds nothing at all.
    #
    # So a column whose own label says it is the answer is excluded rather than
    # penalised: an answer column can hold arbitrarily more text than the
    # questions it answers, and any penalty can be out-scored by a wordy enough
    # answer. Only short labels count -- a cell of `LONG_TEXT` or more is prose,
    # and prose in the first row is data, not a heading.
    labels = sheet.row_values(sheet.rows[0]) if sheet.rows else {}

    def theirs_to_write(column: str) -> bool:
        label = labels.get(column, "")
        if not label or len(label) >= LONG_TEXT:
            return False
        role, _ = _role_for(label, has_dropdown=False)
        return role in (Role.ANSWER, Role.STATUS, Role.EVIDENCE, Role.THEIRS)

    if numbering is not None:
        after = [c for c in sheet.columns if column_number(c) > column_number(numbering)]
        for column in after:
            if theirs_to_write(column):
                continue
            if sum(1 for row in sheet.rows if sheet.value(row, column)) >= MIN_QUESTION_ROWS:
                return Layout(header_row=0, question_column=column, headed=False)

    best: tuple[float, str] | None = None
    for column in sheet.columns:
        if theirs_to_write(column):
            continue
        prose = [row for row in sheet.rows if len(sheet.value(row, column)) >= LONG_TEXT]
        if len(prose) < MIN_QUESTION_ROWS:
            continue
        score = len(prose) - column_number(column) * 0.1
        if best is None or score > best[0]:
            best = (score, column)
    if best is None:
        return None

    # Everything is in play: with no headings there is no preamble to skip, and
    # anchoring on the first long row dropped the nine short numbered questions
    # that came before it. Section rows are filtered later, by shape.
    return Layout(header_row=0, question_column=best[1], headed=False)


def _find_layout(sheet: Sheet) -> Layout | None:
    """The header row and the column holding the questions, chosen together.

    Structure decides this, not wording. Vocabulary alone put the questions in
    'Questionnaire Type' -- a column of the repeated word 'Enterprise' -- because
    the heading contains "question", while the actual questions sat under
    'Security Control'. And it found nothing at all in a workbook whose fifteen
    sheets head their questions 'HR Security', 'Physical Security' and so on,
    none of which any word list would anticipate.

    So the question column is the one that *behaves* like questions: the most
    rows of real prose beneath a plausible header. A matching heading still
    counts, as a tiebreak rather than a requirement.
    """
    best: tuple[float, int, str] | None = None

    for header_row in sheet.rows[:HEADER_SEARCH_ROWS]:
        headings = sheet.row_values(header_row)
        if len(headings) < 2:
            continue
        heading_score, recognised = _header_score(headings)
        if heading_score < 3 or recognised < 2:
            continue

        for column in sheet.columns:
            role, _ = _role_for(headings.get(column, ""), has_dropdown=False)
            below = [row for row in sheet.rows if row > header_row]
            filled = sum(1 for row in below if sheet.value(row, column))
            prose = sum(1 for row in below if len(sheet.value(row, column)) >= LONG_TEXT)

            if role is Role.QUESTION:
                # A column headed 'Question' is the question column, however
                # short its rows are. Requiring prose here lost a whole sheet
                # whose questions are 'Industry', 'Contact email address' and
                # 'Organization's legal name'.
                if filled < MIN_QUESTION_ROWS:
                    continue
                score = heading_score + 100 + min(filled, 40)
                best = best if best and best[0] > score else (score, header_row, column)
                continue

            if prose < MIN_QUESTION_ROWS:
                continue

            score = heading_score + min(prose, 40)
            if role in (Role.ANSWER, Role.EVIDENCE, Role.STATUS, Role.THEIRS):
                # Prose under 'Response' is what we are going to write, not what
                # is being asked. A filled-in questionnaire has just as much text
                # in its answer column as in its question column.
                score -= 12
            # An earlier column is likelier to be the question: forms read left
            # to right, and the answer comes after what it answers.
            score -= column_number(column) * 0.1

            if best is None or score > best[0]:
                best = (score, header_row, column)

    if best is not None:
        return Layout(header_row=best[1], question_column=best[2], headed=True)
    return _find_headless_layout(sheet)


# --- questions -------------------------------------------------------------

MIN_QUESTION_LENGTH = 25
"""Below this, a cell in the question column is a section heading, not a question.

Measured against the samples: the shortest real question is 'Do you have a
password Policy in place?' at 34 characters, and the longest section heading is
'Cyber Security Event and Incident Management' at 44 -- so length alone cannot
separate them, and the question mark and the numbering column carry the rest.
"""


def _looks_like_a_question(text: str, number: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.endswith(("?", "؟")):          # ? and Arabic ؟
        return True
    if _ITEM_NUMBER.match(number.strip()):
        # A printed item number settles it. Questions are often not sentences --
        # "Industry", "Contact email address", "Service Provider CR Number" are
        # all real questions in these forms, and a length rule threw them away.
        return len(stripped) >= 3
    return len(stripped) >= MIN_QUESTION_LENGTH * 2


BANNER_ROWS = 4
"""How far above the header to look for a 'to be filled by ...' banner."""


def _ownership_banners(
    workbook: Workbook, sheet: Sheet, header_row: int
) -> dict[str, tuple[Role, str]]:
    """Columns claimed by a banner spanning them above the header.

    One workbook says who owns what a row *above* its column headings:
    'To be Filled by the Vendor' merged across D:E, 'To be Filled by Bank
    Albilad' across F:G. Read only the headings and column F is a compliance
    dropdown like any other -- and answering it would put our words in the
    assessing bank's own column, on every sheet of the file.

    So the merged span is what assigns the role, and it outranks the heading.
    """
    claimed: dict[str, tuple[Role, str]] = {}
    for row in range(max(1, header_row - BANNER_ROWS), header_row):
        for column, text in sheet.row_values(row).items():
            owner = _owner(" ".join(text.split()))
            if owner is None:
                continue
            ours = any(name in owner.lower() for name in _US)
            for covered in _span_columns(sheet, row, column):
                if ours:
                    continue
                claimed[covered] = (
                    Role.THEIRS,
                    f"a banner on row {row} says this column is {owner!r}'s",
                )
    return claimed


def _span_columns(sheet: Sheet, row: int, column: str) -> list[str]:
    """Which columns a banner cell covers, via the merge it anchors."""
    from src.forms.xlsx_package import column_letters, split_ref

    for span in sheet.merges:
        if ":" not in span:
            continue
        try:
            start, end = span.split(":")
            first_column, first_row = split_ref(start)
            last_column, last_row = split_ref(end)
        except ValueError:
            continue
        if (first_row, first_column) != (row, column):
            continue
        return [
            column_letters(number)
            for number in range(column_number(first_column), column_number(last_column) + 1)
        ]
    return [column]


def _headless_roles(sheet: Sheet, question_column: str) -> dict[str, tuple[Role, str]]:
    """Roles by position, for a sheet with no headings to read.

    The question column is known. To its left, a column of short item labels is
    the numbering. To its right, the first column carrying anything at all on
    question rows is where answers go -- in these forms it holds either the
    previous answer or the prompt for one ("Yes / No"), and both mean the same
    thing about where to write.
    """
    roles: dict[str, tuple[Role, str]] = {}
    wanted = column_number(question_column)
    question_rows = [row for row in sheet.rows if sheet.value(row, question_column)]

    left = [c for c in sheet.columns if column_number(c) < wanted]
    if left:
        candidate = left[-1]
        labels = [sheet.value(row, candidate) for row in question_rows]
        if sum(1 for label in labels if _ITEM_NUMBER.match(label.strip())) >= max(2, len(labels) // 3):
            roles[candidate] = (Role.NUMBER, "short item labels beside each question")

    for candidate in [c for c in sheet.columns if column_number(c) > wanted]:
        filled = sum(1 for row in question_rows if sheet.value(row, candidate))
        if filled:
            roles[candidate] = (Role.ANSWER, "the first column after the questions that carries values")
            break
    return roles


def _why_question(heading: str, header_row: int) -> str:
    """How the question column was identified, in words a person can check.

    The heading is deliberately left out: the caller puts it in front of every
    column reason, and naming it here as well printed it twice.
    """
    role, why = _role_for(heading, has_dropdown=False)
    if role is Role.QUESTION:
        return why
    if heading:
        return "the column holding the questions, by where the text is"
    return f"the column holding the questions, under the headings on row {header_row}"


def unreadable(sheet: Sheet) -> Part | None:
    """A sheet not worth reading at all, or None to go on.

    Separate from the rest because nothing -- not a cleverer rule, not a model
    -- should reopen these two. A hidden sheet is hidden on purpose, and six
    cells is not a questionnaire.
    """
    if not sheet.visible:
        return Part(name=sheet.name, kind="hidden", findings=[
            Finding(subject=sheet.name, verdict="skipped", because="the sheet is hidden")
        ])
    if len(sheet.cells) < 6:
        return Part(name=sheet.name, kind="empty", findings=[
            Finding(subject=sheet.name, verdict="skipped", because="almost nothing in it")
        ])
    return None


def _resolve_roles(
    workbook: Workbook, sheet: Sheet, layout: Layout
) -> tuple[dict[str, tuple[Role, str]], list[Finding]]:
    """What every column is for, once the layout is settled."""
    findings: list[Finding] = []
    header_row, question_column = layout.header_row, layout.question_column
    headings = sheet.row_values(header_row) if layout.headed else {}

    # Roles for every other column, now that dropdowns can be consulted. A
    # dropdown is a stronger signal than a heading and is knowable only per
    # column, not from the header row alone.
    resolved: dict[str, tuple[Role, str]] = {
        question_column: (Role.QUESTION, _why_question(headings.get(question_column, ""), header_row))
    }
    # Columns holding a value, *plus* columns that only carry a dropdown. An
    # unused dropdown holds nothing, so on a blank questionnaire the status
    # column -- the one the form most wants filled -- was not in `sheet.columns`
    # at all and never got a role.
    candidates = sorted(
        set(sheet.columns) | workbook.validated_columns(sheet) | set(headings),
        key=column_number,
    )
    for column in candidates:
        if column == question_column:
            continue
        heading = headings.get(column, "")
        has_dropdown = bool(workbook.vocabulary_for(sheet, column))
        if not heading and not has_dropdown:
            continue
        resolved[column] = _role_for(heading, has_dropdown=has_dropdown)

    if not layout.headed:
        resolved.update(_headless_roles(sheet, question_column))
    # A banner above the headings outranks them: it is the only thing that says
    # a column belongs to whoever sent the questionnaire.
    for column, claim in _ownership_banners(workbook, sheet, header_row).items():
        if column != question_column:
            resolved[column] = claim

    # A form with somewhere to write a status but nowhere to write prose is
    # usually one whose answer column was worded as a request for evidence.
    # Promote it, and say that the promotion happened.
    if not any(role is Role.ANSWER for role, _ in resolved.values()):
        evidence = [c for c, (role, _) in resolved.items() if role is Role.EVIDENCE]
        if evidence:
            column = evidence[0]
            resolved[column] = (Role.ANSWER, "the only free-text column, so read as the answer")
            findings.append(Finding(
                subject=f"column {column}",
                verdict="answer",
                because=f"{headings.get(column, '')!r} asks for evidence, but it is the only free-text "
                        "column here, and in the completed examples it holds the answer",
                confident=False,
            ))

    for column, (role, why) in sorted(resolved.items(), key=lambda item: column_number(item[0])):
        if role is Role.IGNORE:
            continue
        already = any(f.subject == f"column {column}" for f in findings)
        if not already:
            findings.append(Finding(
                subject=f"column {column}",
                verdict=role.value,
                because=f"{headings.get(column, '')!r}: {why}" if headings.get(column) else why,
                confident=layout.headed,
            ))

    return resolved, findings


def read_sheet(
    workbook: Workbook,
    sheet: Sheet,
    layout: Layout,
    resolved: dict[str, tuple[Role, str]],
    findings: list[Finding],
) -> tuple[Part, list[FormQuestion]]:
    """Turn a settled layout and set of column roles into questions.

    Everything after "which row heads it, which column asks, and what is every
    other column for". Kept separate from how those were decided so that the
    rules, a model asked to read a sheet the rules could not, and the Excel
    agent all produce identical question ids, targets and locations -- and a
    comparison between them is a comparison of the reading, not of the reader.
    """
    header_row, question_column = layout.header_row, layout.question_column
    headings = sheet.row_values(header_row) if layout.headed else {}
    number_column = next((c for c, (role, _) in resolved.items() if role is Role.NUMBER), None)

    # Leftmost wins each role. One workbook heads column D 'Answer' and column E
    # 'Additional Information to Support the Answer'; both read as the answer,
    # and the supplementary one was silently taking the primary one's place.
    writable: dict[Role, str] = {}
    for column, (role, _) in sorted(resolved.items(), key=lambda item: column_number(item[0])):
        if role in (Role.ANSWER, Role.STATUS, Role.EVIDENCE):
            writable.setdefault(role, column)

    questions: list[FormQuestion] = []
    section = ""
    covered = workbook.merged_ranges(sheet)

    for row in sheet.rows:
        if row <= header_row:
            continue
        text = sheet.value(row, question_column)
        if not text and (row, question_column) in covered:
            anchor = covered[(row, question_column)]
            text = sheet.value(*anchor) if anchor[0] == row else ""
        if not text:
            continue

        values = sheet.row_values(row)
        if _is_repeated_header(values, headings):
            continue

        number = sheet.value(row, number_column) if number_column else ""
        if not _looks_like_a_question(text, number):
            section = " ".join(text.split())
            continue

        targets: dict[Role, Target] = {}
        for role, column in writable.items():
            ref = f"{column}{row}"
            targets[role] = Target(
                id=f"{sheet.name}!{ref}",
                role=role,
                label=headings.get(column, ""),
                vocabulary=workbook.vocabulary_for(sheet, column) if role is Role.STATUS else [],
                existing=sheet.value(row, column),
            )
        if not targets:
            continue

        questions.append(FormQuestion(
            id=f"{sheet.name}!{row}",
            number=" ".join(number.split()),
            text=" ".join(text.split()),
            section=section,
            language=_language(text),
            targets=targets,
            location=f"{sheet.name}, row {row}",
        ))

    if questions and len(questions) < MIN_NUMBERED_ROWS and number_column is None:
        # A legend explaining what each compliance rating means reads exactly
        # like a short questionnaire: prose in a column, under a heading. What
        # it lacks is question numbers.
        return Part(name=sheet.name, kind="reference table", findings=[
            Finding(subject=sheet.name, verdict="skipped",
                    because=f"only {len(questions)} rows of prose and no numbering column, "
                            "so this reads as a reference table")
        ]), []

    if not questions:
        return Part(name=sheet.name, kind="no questions", findings=findings + [
            Finding(subject=sheet.name, verdict="skipped",
                    because=f"column {question_column} was read as questions but no row held one")
        ]), []

    findings.insert(0, Finding(
        subject=sheet.name,
        verdict=f"{len(questions)} questions",
        because=f"headings on row {header_row}; questions in column {question_column}",
    ))
    return Part(name=sheet.name, kind="questions", questions=len(questions), findings=findings), questions


def _detect_sheet(workbook: Workbook, sheet: Sheet) -> tuple[Part, list[FormQuestion]]:
    """Read one sheet by the rules. Returns what was made of it, and questions."""
    skipped = unreadable(sheet)
    if skipped is not None:
        return skipped, []

    layout = _find_layout(sheet)
    if layout is None:
        return Part(name=sheet.name, kind="no questions", findings=[
            Finding(subject=sheet.name, verdict="skipped",
                    because="no column holds a run of questions")
        ]), []

    resolved, findings = _resolve_roles(workbook, sheet, layout)
    return read_sheet(workbook, sheet, layout, resolved, findings)


def _is_repeated_header(values: dict[str, str], headings: dict[str, str]) -> bool:
    """Whether this row is the header printed again further down the sheet.

    One sample repeats its column headings at the top of every section, and
    each repeat would otherwise read as a question.
    """
    shared = [column for column in values if column in headings]
    if len(shared) < 2:
        return False
    return all(values[column].strip() == headings[column].strip() for column in shared)


def _thin(sheet: Sheet, part: Part, layout_row: int) -> bool:
    """Whether a sheet was read, but read badly.

    Seven questions on a sheet of 133 rows is a wrong column, not a short
    questionnaire -- that is the ISRA workbook, whose sections are headed 'HR
    Security' and 'Physical Security' and which no word list anticipates. The
    test is coverage: what share of the rows below the header became questions.
    """
    below = [row for row in sheet.rows if row > layout_row]
    if len(below) < settings.detection_assist_min_rows:
        return False
    return part.questions / len(below) < settings.detection_assist_coverage


def _assist(workbook: Workbook, sheet: Sheet, part: Part, found: int) -> tuple[Part, list] | None:
    """A model's reading of a sheet, if it beats what the rules managed.

    Strictly monotone, and deliberately so: the reading is kept only when it
    finds *more* questions than the rules did, so turning assistance on can add
    a sheet the rules lost but can never take away one they read correctly.
    """
    from src.forms import llm_layout

    read = llm_layout.read(workbook, sheet)
    if read is None:
        return None
    assisted, questions = read
    if len(questions) <= found:
        logger.info(
            "The model found %d question(s) on %r against the rules' %d; keeping the rules'",
            len(questions), sheet.name, found,
        )
        return None
    return assisted, questions


def detect(path: str | Path, *, assist: bool | None = None) -> DetectedForm:
    """Read a workbook and report what can be answered in it.

    `assist` offers sheets the rules could not read to a model, which proposes a
    layout this same code then extracts from. Defaults to the configured
    setting; pass it explicitly to compare the two readings of one file.
    """
    path = Path(path)
    assist = settings.detection_assist if assist is None else assist
    form = DetectedForm(source_name=path.name, format="xlsx")

    with Workbook(path) as workbook:
        for sheet in workbook.sheets:
            part, questions = _detect_sheet(workbook, sheet)

            if assist and unreadable(sheet) is None:
                header_row = _header_row_of(part)
                if not questions or _thin(sheet, part, header_row):
                    better = _assist(workbook, sheet, part, len(questions))
                    if better is not None:
                        part, questions = better

            form.parts.append(part)
            form.questions.extend(questions)

    if not form.questions:
        form.warnings.append(
            "No questions were found. The sheets were read as: "
            + ", ".join(f"{part.name} ({part.kind})" for part in form.parts)
        )
    return form


_HEADER_ROW = re.compile(r"headings on row (\d+)")


def _header_row_of(part: Part) -> int:
    """The header row the rules settled on, read back off the finding.

    Recovered from the report rather than threaded through the return type,
    because the header row is of no interest to anything else and a second
    return value on `_detect_sheet` would be carried by every caller.
    """
    for finding in part.findings:
        match = _HEADER_ROW.search(finding.because)
        if match:
            return int(match.group(1))
    return 0


# --- writing ---------------------------------------------------------------


def write(path: str | Path, destination: str | Path, values: dict[str, str]) -> WriteReport:
    """Put answers into a copy of the workbook.

    `values` is keyed by target id -- `'Sheet name!C9'`, exactly as `detect`
    reported it. Every target is an upsert: the cell is created when the file
    never had one there, and replaced when it did. Which of the two happened is
    reported rather than assumed, because a blank template and last year's
    submission are both ordinary starting points and only one of them is safe
    to write over without saying so.
    """
    path, destination = Path(path), Path(destination)
    per_sheet: dict[str, dict[str, str]] = {}
    malformed: dict[str, str] = {}

    for target_id, text in values.items():
        if "!" not in target_id:
            malformed[target_id] = "Not a cell reference; expected 'Sheet!C9'."
            continue
        sheet_name, ref = target_id.rsplit("!", 1)
        per_sheet.setdefault(sheet_name, {})[ref] = text

    with Workbook(path) as workbook:
        before = workbook.part_count
        previous, skipped = workbook.write(destination, per_sheet)

    after = Workbook(destination)
    parts_after = after.part_count
    after.close()

    return WriteReport(
        path=str(destination),
        created=sorted(target for target, was in previous.items() if not was.strip()),
        replaced=sorted(target for target, was in previous.items() if was.strip()),
        skipped={**malformed, **skipped},
        parts_before=before,
        parts_after=parts_after,
    )
