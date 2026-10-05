"""Reading questionnaires and writing answers back into them.

One interface, one module per format:

    detect(path)                       -> DetectedForm
    write(path, destination, values)   -> WriteReport

`values` is keyed by the target ids `detect` reported, so nothing above this
layer needs to know whether an answer lands in a spreadsheet cell, a table cell,
or a paragraph that has to be created first.

Adding a format means adding a module with those two functions and one line in
`_FORMATS`. Nothing else changes -- which is the point of the split, since these
questionnaires arrive in whatever shape their author chose.
"""

from __future__ import annotations

from pathlib import Path

from src.forms import docx, xlsx, xlsx_package
from src.forms.model import (
    DetectedForm,
    Finding,
    FormQuestion,
    Part,
    Role,
    Target,
    WriteReport,
    WRITABLE,
)

_FORMATS = {".xlsx": xlsx, ".xlsm": xlsx, ".docx": docx}

SUPPORTED = tuple(sorted(_FORMATS))


class UnsupportedForm(Exception):
    """The file is not a questionnaire format this can read."""


# Re-exported so a caller can catch one thing. Both are "this file cannot be
# read", and the message is written to be shown to whoever uploaded it -- these
# arrive from other companies, and a stack trace is not an answer.
FormatError = xlsx_package.FormatError


def _module(path: Path):
    module = _FORMATS.get(path.suffix.lower())
    if module is None:
        raise UnsupportedForm(
            f"{path.suffix or 'That file'} is not a form this can read. Supported: {', '.join(SUPPORTED)}."
        )
    return module


ASSISTED = (".xlsx", ".xlsm")
"""Formats whose detection can fall back to a model -- see `forms.llm_layout`.

Only spreadsheets. A Word questionnaire is read by two detectors that between
them cover prose and tables, and neither has a "no column holds a run of
questions" failure for a model to rescue; the shape of a Word form is the shape
of the document.
"""


def detect(path: str | Path, *, assist: bool | None = None) -> DetectedForm:
    """Read a questionnaire and report what can be answered in it.

    `assist` offers sheets the rules cannot read to a model, which proposes a
    layout the ordinary reader then extracts from. It defaults to the configured
    setting and is ignored by formats that have no such fallback.
    """
    path = Path(path)
    module = _module(path)
    if assist is not None and path.suffix.lower() in ASSISTED:
        return module.detect(path, assist=assist)
    return module.detect(path)


def write(path: str | Path, destination: str | Path, values: dict[str, str]) -> WriteReport:
    """Write answers into a copy of the questionnaire, leaving the rest alone."""
    path = Path(path)
    safe = {target: xlsx_package.xml_safe(text) for target, text in values.items()}
    return _module(path).write(path, destination, safe)


__all__ = [
    "detect",
    "write",
    "DetectedForm",
    "FormQuestion",
    "Target",
    "Role",
    "Finding",
    "Part",
    "WriteReport",
    "WRITABLE",
    "SUPPORTED",
    "ASSISTED",
    "UnsupportedForm",
    "FormatError",
]
