"""Showing a worksheet to a language model.

Both model-assisted readers -- the fallback in `llm_layout` and the agent in
`src.agents.excel_agent` -- have to look at the same thing a person would: a
grid of cells, and what each column contains further down. This renders that,
and nothing here decides anything.

Two constraints shape it. A real questionnaire sheet is up to 30,000 rows, so
the grid is a *window*; and the thing being identified -- which row heads the
sheet, which column asks -- is always visible in the first screenful, because
that is where a person would look too. Below the window, columns are described
statistically rather than shown, because "412 rows, 137 characters on average"
says what matters about a question column and 412 quoted cells do not.
"""

from __future__ import annotations

from src.forms.xlsx_package import Sheet, Workbook, column_number

GRID_ROWS = 22
"""Rows of the sheet shown as a grid. Covers every header row in the samples --
the deepest is row 8, under a title, a vendor name and a date -- plus enough
questions beneath it to see what the columns hold."""

GRID_COLUMNS = 16
CELL_WIDTH = 48
"""Cells are truncated, not wrapped. A questionnaire's guidance paragraphs run
to hundreds of characters and would bury the grid they sit in."""

SAMPLE_VALUES = 3
VOCABULARY_SHOWN = 6


def cell(text: str, width: int = CELL_WIDTH) -> str:
    """One cell, flattened onto a line and truncated to fit."""
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[: width - 1] + "…"


def grid(sheet: Sheet, rows: int = GRID_ROWS, columns: int = GRID_COLUMNS) -> str:
    """The top-left corner of the sheet, as a person would see it.

    Row and column labels are the file's own -- row 8, column D -- so anything
    the model says about the sheet can be checked against it in Excel, and so a
    proposal names cells this package can resolve.
    """
    shown_rows = sheet.rows[:rows]
    shown_columns = sheet.columns[:columns]
    if not shown_rows or not shown_columns:
        return "(empty)"

    lines = []
    for row in shown_rows:
        cells = [f"{column}: {cell(sheet.value(row, column))}"
                 for column in shown_columns if sheet.value(row, column)]
        lines.append(f"row {row} | " + " | ".join(cells) if cells else f"row {row} | (blank)")
    if len(sheet.rows) > len(shown_rows):
        lines.append(f"... {len(sheet.rows) - len(shown_rows)} more row(s) below")
    return "\n".join(lines)


def columns(workbook: Workbook, sheet: Sheet, below: int) -> str:
    """What each column holds beneath `below`, as counts rather than contents.

    A column is identified by how it behaves -- how often it is filled, how long
    its text runs, whether it offers a dropdown -- and those three numbers
    separate a question column from an answer column far more reliably than any
    heading does. The dropdown vocabulary is spelled out because it is the one
    thing a status column cannot be recognised without.
    """
    candidates = sorted(
        set(sheet.columns) | workbook.validated_columns(sheet), key=column_number
    )
    if not candidates:
        return "(no columns)"

    lines = []
    for column in candidates:
        values = [sheet.value(row, column) for row in sheet.rows if row > below]
        filled = [value for value in values if value.strip()]
        average = round(sum(len(value) for value in filled) / len(filled)) if filled else 0
        vocabulary = workbook.vocabulary_for(sheet, column)

        parts = [f"{len(filled)} filled", f"avg {average} chars"]
        if vocabulary:
            shown = ", ".join(vocabulary[:VOCABULARY_SHOWN])
            more = "" if len(vocabulary) <= VOCABULARY_SHOWN else f", +{len(vocabulary) - VOCABULARY_SHOWN} more"
            parts.append(f"dropdown [{shown}{more}]")
        elif filled:
            parts.append("e.g. " + " / ".join(cell(v, 60) for v in filled[:SAMPLE_VALUES]))
        else:
            parts.append("empty")
        lines.append(f"column {column}: " + "; ".join(parts))
    return "\n".join(lines)


def describe(workbook: Workbook, sheet: Sheet, *, below: int = 0) -> str:
    """The whole picture of one sheet: the grid, then the columns below it."""
    return (
        f"SHEET {sheet.name!r} — {len(sheet.rows)} row(s), "
        f"{len(sheet.columns)} column(s) holding values\n\n"
        f"THE TOP OF THE SHEET\n{grid(sheet)}\n\n"
        f"WHAT EACH COLUMN HOLDS BELOW ROW {below}\n{columns(workbook, sheet, below)}"
    )
