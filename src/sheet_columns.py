"""Every column of a questionnaire's sheets, for a person to choose where the answers go (plan 043).

Detection proposes the columns it writes to, and the Workbench showed only
those. When it had read the file wrong -- answers headed as a status, say --
the column a person wanted was not on offer, and one set to "do not write here"
left the list. This lists the rest: each column with its heading, a value from
beside the questions, and what detection made of it. Choosing goes through
`tools.set_column_role`, as before; nothing here changes how a file is read.
"""

from __future__ import annotations

import re
from typing import Any

from src.forms.model import FormQuestion
from src.forms.xlsx_package import Workbook, column_letters, column_number
from src.identity import User
from src.questionnaire import require

HEADING_ABOVE = 3
"""Rows above a sheet's first question searched for a column's heading: the
header row, or the second row of a two-row heading."""

SHOWN_CHARS = 60
MOST_COLUMNS = 40
"""A sheet with notes far off to the right would otherwise offer every column up to them."""

_PLACE = re.compile(r"^(.*)![A-Z]*(\d+)$")
"""A target's cell ("Security!C9") or a spreadsheet question's id ("Security!9")."""


def _short(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= SHOWN_CHARS else flat[: SHOWN_CHARS - 1] + "…"


def _rows_by_sheet(questions: list[FormQuestion]) -> dict[str, set[int]]:
    """The rows questions were read from, per sheet: where their answers go, or their id when they go nowhere."""
    rows: dict[str, set[int]] = {}
    for question in questions:
        for place in [target.id for target in question.targets.values()] or [question.id]:
            found = _PLACE.match(place)
            if found:
                rows.setdefault(found.group(1), set()).add(int(found.group(2)))
    return rows


def every_column(user: User, batch_id: str) -> list[dict[str, Any]]:
    """Each sheet questions were read from, with every column beside them, in the file's order.

    A column is listed when it has anything in a question's row or in the rows
    just above the first question, and so is the one after the last of those,
    for an answer column the file left blank, heading and all. `detected` is
    what detection made of the column ("question", "status", ...), or "".
    """
    batch = require(user, batch_id, reading=True)
    if batch.form.format != "xlsx" or not batch.exists:
        return []
    rows = _rows_by_sheet(batch.form.questions)
    out = []
    with Workbook(batch.source_path) as workbook:
        for part in batch.form.parts:
            page = workbook.get(part.name) if part.used else None
            if page is None or part.name not in rows:
                continue
            asked = sorted(rows[part.name])
            above = list(range(asked[0] - 1, max(0, asked[0] - 1 - HEADING_ABOVE), -1))
            detected = {
                f.subject[len("column ") :]: f.verdict for f in part.findings if f.subject.startswith("column ")
            }
            used = [c for c in page.columns if any(page.value(row, c).strip() for row in asked + above)]
            used = sorted(set(used) | set(detected), key=column_number)
            if used:
                used.append(column_letters(column_number(used[-1]) + 1))
            columns = []
            for column in used[:MOST_COLUMNS]:
                heading = next((page.value(row, column) for row in above if page.value(row, column).strip()), "")
                sample = next((page.value(row, column) for row in asked if page.value(row, column).strip()), "")
                columns.append(
                    {
                        "column": column,
                        "heading": _short(heading),
                        "sample": _short(sample),
                        "detected": detected.get(column, ""),
                    }
                )
            out.append({"sheet": part.name, "columns": columns})
    return out
