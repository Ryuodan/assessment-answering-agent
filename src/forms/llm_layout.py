"""Asking a model to read a sheet the rules could not.

The rules in `xlsx` find 831 of 824 hand-counted questions across eleven real
workbooks -- everything, plus a handful a person unticks. They get there by
describing shapes we have seen. A questionnaire arriving in a twelfth shape --
a two-row header, questions in a merged block, a sheet whose only structure is
indentation -- falls outside all of them and comes back "no column holds a run
of questions", which is a whole sheet silently lost.

So a model is asked, but only about **structure**, and only where the rules
gave up. It answers one question -- which row heads this sheet, which column
asks, and what is every other column for -- and `xlsx.read_sheet` does the
rest. That split is the whole design:

* It cannot invent a question. Question text is read out of cells, so a
  hallucinated question has nowhere to come from.
* It cannot invent a place to write. Targets are built from real cell
  references by the same code as always, so `fill` is exactly as safe.
* It cannot take the assessing bank's column. A "to be filled by ..." banner
  still overrides whatever the model said, because that is the one mistake
  worse than leaving a question blank.
* It is checked. A reading that yields no questions is discarded and the sheet
  stays skipped, so the fallback can only ever add.

Everything it does produce is marked unconfident, which puts it at the top of
the confirmation panel with its reasoning attached.
"""

from __future__ import annotations

import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from src.config import settings
from src.forms import sheet_view
from src.forms.model import Finding, FormQuestion, Part, Role
from src.forms.xlsx import Layout, read_sheet
from src.forms.xlsx_package import Sheet, Workbook, column_number
from src.llm import structured_llm

logger = logging.getLogger(__name__)

TEMPERATURE = 0.0
"""Reading a layout has one right answer. Nothing here benefits from variety."""


class ColumnReading(BaseModel):
    """One column and what it is for."""

    column: str = Field(description="The column letter, e.g. 'C'")
    role: Literal["number", "question", "answer", "status", "evidence", "theirs", "context", "ignore"]
    because: str = Field(default="", description="Six words at most")


class SheetReading(BaseModel):
    """A model's reading of one worksheet."""

    is_questionnaire: bool = Field(
        description="True only if this sheet holds questions somebody is expected to answer. "
        "False for cover pages, instructions, legends, rating scales, lookup tables."
    )
    header_row: int = Field(
        default=0,
        description="The row number carrying the column headings, or 0 if the sheet has none.",
    )
    question_column: str = Field(default="", description="The column letter holding the questions")
    columns: list[ColumnReading] = Field(default_factory=list)
    reason: str = Field(default="", description="One sentence a person can check against the sheet")


SYSTEM = """You read the layout of a questionnaire worksheet. You are being asked
because a set of hand-written rules could not, so the sheet is probably in an
unusual shape.

You decide four things and nothing else:

1. Whether the sheet holds questions at all. Cover pages, instructions, rating
   scales, legends and lookup tables do not, however much text they carry. Say
   so rather than forcing a reading.
2. Which row holds the column headings. It is often not row 1 -- titles, logos,
   vendor names and dates come first. Answer 0 if the sheet has no headings.
3. Which column holds the questions themselves. Judge by what the column
   contains, not by what it is called: the question column is the one whose
   cells are the things being asked. A column headed "Questionnaire Type"
   holding the same word 200 times is not it; a column headed "Security
   Control" holding 183 distinct requirements is.
4. What every other column is for.

The roles:

  number    the printed question number or reference code
  question  the questions
  answer    free prose we are expected to write
  status    a choice from a fixed list -- a dropdown, or a Yes/No column
  evidence  what to attach or reference
  theirs    a column belonging to whoever SENT this questionnaire, such as one
            headed "to be completed by the reviewer" or "bank use only"
  context   a domain, section, category or clause reference we only read
  ignore    anything else

Two are worth care. `status` is almost always the column offering a dropdown,
even when nothing has been typed into it yet -- a blank questionnaire's status
column is empty by definition. And `theirs` protects the sender: writing in
their column is worse than leaving a question unanswered, so when a heading or
a banner addresses somebody other than the supplier being assessed, say
`theirs`.

Do not guess. If the sheet does not hold questions, say so -- but say it by
filling in the answer with `is_questionnaire` false, never by replying in
words. There is no way to answer here except by filling in the fields."""

USER = """{description}

Read this sheet."""


def _letters(text: str) -> str:
    return "".join(character for character in text.strip().upper() if character.isalpha())


def _reason(reading: SheetReading) -> str:
    return " ".join(reading.reason.split())[:220] or "no reason given"


def _validate(
    reading: SheetReading, sheet: Sheet, workbook: Workbook, source: str
) -> tuple[Layout, dict[str, tuple[Role, str]]] | None:
    """Turn a reading into a layout, or None if it does not describe this sheet.

    Every field is checked against the file rather than trusted. A column letter
    that holds nothing, a header row that does not exist, a header below the
    last row -- each is a reading of some other spreadsheet, and the sheet is
    better left skipped than read wrongly.
    """
    if not reading.is_questionnaire:
        return None

    question_column = _letters(reading.question_column)
    if question_column not in set(sheet.columns):
        logger.info(
            "Model proposed column %r, which holds nothing on %r",
            reading.question_column,
            sheet.name,
        )
        return None

    header_row = reading.header_row
    if header_row < 0 or (header_row and header_row not in sheet.rows):
        logger.info("Model proposed header row %s, which is empty on %r", header_row, sheet.name)
        return None
    if header_row >= max(sheet.rows, default=0):
        logger.info("Model proposed header row %s, below every row on %r", header_row, sheet.name)
        return None

    known = set(sheet.columns) | workbook.validated_columns(sheet)
    resolved: dict[str, tuple[Role, str]] = {question_column: (Role.QUESTION, f"{source}: {_reason(reading)}")}
    for column in reading.columns:
        letters = _letters(column.column)
        if letters == question_column or letters not in known:
            continue
        try:
            role = Role(column.role)
        except ValueError:
            continue
        because = " ".join(column.because.split())[:120]
        resolved[letters] = (role, f"{source}: {because}" if because else source)

    return (
        Layout(header_row=header_row, question_column=question_column, headed=bool(header_row)),
        resolved,
    )


SOURCE = "read by the model"
"""How a finding names where its reading came from. The Excel agent passes its
own, so the report says which of the two produced a column."""


def apply(
    workbook: Workbook,
    sheet: Sheet,
    reading: SheetReading,
    *,
    source: str = SOURCE,
) -> tuple[Part, list[FormQuestion]] | None:
    """Read a sheet under a model's reading of it, or None if it yields nothing.

    Separate from `read` so the checking can be tested without a model, which is
    where every failure this guards against actually lives, and so the Excel
    agent can put its own readings through exactly the same checks.
    """
    checked = _validate(reading, sheet, workbook, source)
    if checked is None:
        return None
    layout, resolved = checked

    # The banner outranks the model exactly as it outranks the headings. It is
    # the only thing in the file that says a column belongs to the sender, and a
    # model that has not noticed it must not be able to overrule it.
    from src.forms.xlsx import _ownership_banners

    for column, claim in _ownership_banners(workbook, sheet, layout.header_row).items():
        if column != layout.question_column:
            resolved[column] = claim

    findings = [
        Finding(subject=f"column {column}", verdict=role.value, because=why, confident=False)
        for column, (role, why) in sorted(resolved.items(), key=lambda item: column_number(item[0]))
        if role is not Role.IGNORE
    ]

    part, questions = read_sheet(workbook, sheet, layout, resolved, findings)
    if not questions:
        logger.info("The model's reading of %r produced no questions; leaving it skipped", sheet.name)
        return None

    # One verdict per sheet. `read_sheet` writes the mechanical summary -- which
    # row, which column -- and this replaces it with the same facts plus where
    # the reading came from, rather than leaving the report with two.
    mechanical = next((f for f in part.findings if f.subject == sheet.name), None)
    where = mechanical.because if mechanical else ""
    part.findings = [f for f in part.findings if f is not mechanical]
    part.findings.insert(
        0,
        Finding(
            subject=sheet.name,
            verdict=f"{len(questions)} questions",
            because=f"{source}, not by the rules ({where}) — {_reason(reading)}"
            if where
            else f"{source}, not by the rules — {_reason(reading)}",
            confident=False,
        ),
    )
    return part, questions


def thin(sheet: Sheet, part: Part, layout_row: int) -> bool:
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


_HEADER_ROW = re.compile(r"headings on row (\d+)")


def header_row_of(part: Part) -> int:
    """The header row the rules settled on, read back off the finding.

    Recovered from the report rather than threaded through the return type,
    because the header row is of no interest to anything else and a second
    return value on `xlsx._detect_sheet` would be carried by every caller.
    """
    for finding in part.findings:
        match = _HEADER_ROW.search(finding.because)
        if match:
            return int(match.group(1))
    return 0


def read(workbook: Workbook, sheet: Sheet) -> tuple[Part, list[FormQuestion]] | None:
    """Ask a model to read one sheet. None when it produced nothing usable.

    None is the ordinary outcome for a sheet that really is a cover page, and
    the caller leaves the rules' own verdict in place.
    """
    try:
        reading = structured_llm(SheetReading, temperature=TEMPERATURE).invoke(
            [
                ("system", SYSTEM),
                ("user", USER.format(description=sheet_view.describe(workbook, sheet))),
            ]
        )
    except Exception as failed:
        # Logged as a line, not a traceback. The common case is not a fault: a
        # model looking at a table of contents answers "this is not a
        # questionnaire" in prose, the provider rejects the reply because a
        # tool call was required, and the outcome -- no reading -- is the right
        # one. A stack trace per cover page in a nineteen-file run buried
        # everything else. The prompt now insists on the schema, which makes it
        # rarer, and this keeps it quiet when it still happens.
        logger.warning("Could not read the layout of %r with a model: %s", sheet.name, failed)
        return None
    return apply(workbook, sheet, reading)
