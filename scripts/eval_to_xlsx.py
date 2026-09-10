"""Turn an evaluation run into a spreadsheet somebody can read through.

    python -m scripts.eval_to_xlsx eval/results/heldout_full.json --out eval/results/heldout.xlsx

One row per question: which questionnaire it came from, what was asked, what
the security team wrote, what this system wrote, and how the judge scored the
two against each other. That is the artefact a reviewer actually wants -- the
JSON the harness writes is for the harness, and nobody reads a hundred and
thirty-five answers in a terminal.

Needs `openpyxl`, which is not a dependency of the application:

    pip install -e ".[reports]"

Deliberately kept out of the core requirements. The system never writes a
spreadsheet from scratch -- filling a questionnaire edits the customer's own
workbook through `src/forms/xlsx.py`, with the stdlib, precisely so the
formatting survives. This is a report, which is a different job.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FONT = "Arial"

# The five the reader asked for, then what is needed to act on a low score:
# whether the answer would have been written or held back, and how close the
# answer memory already was to the question.
COLUMNS = [
    ("file name", "file", 34),
    ("question", "question", 62),
    ("real answer", "reference", 62),
    ("generated answer", "answer", 72),
    ("Judge score/approval", "_judge", 20),
    ("judge verdict", "verdict", 14),
    ("judge note", "note", 60),
    ("confidence", "confidence", 11),
    ("would be written", "_written", 15),
    ("nearest remembered question", "twin", 13),
    ("cited its own memory entry", "_own", 13),
]

VERDICTS = {
    "same": "the same position, in different words",
    "broader": "ours says everything theirs does, and more",
    "narrower": "ours leaves out something theirs asserts",
    "drifts": "ours answers a neighbouring question",
    "contradicts": "ours asserts the opposite",
    "declined": "ours declines to answer; theirs does not",
    "unanswerable": "the reference is not an answer (excluded from the score)",
}


def _judge(case: dict) -> str:
    """The judge's verdict as a mark a person can scan a column of."""
    score = case.get("agreement_score")
    if score is None or not case.get("verdict"):
        return "not judged"
    agrees = case["verdict"] in ("same", "broader")
    return f"{score}/5 {'agrees' if agrees else 'differs'}"


def _written(case: dict) -> str:
    held = case.get("needs_review") or (case.get("confidence") or 0) < 0.6
    return "held for review" if held else "yes"


def _own(case: dict) -> str:
    return "yes" if case.get("found_own_answer") else ""


DERIVED = {"_judge": _judge, "_written": _written, "_own": _own}


def _value(case: dict, key: str):
    value = DERIVED[key](case) if key in DERIVED else case.get(key, "")
    return round(value, 3) if isinstance(value, float) else value


def build(payload: dict, out: Path, title: str) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    cases = payload.get("cases") or []
    summary = payload.get("summary") or {}

    book = Workbook()
    sheet = book.active
    sheet.title = "Results"

    header = Font(name=FONT, size=10, bold=True, color="FFFFFF")
    body = Font(name=FONT, size=10)
    fill = PatternFill("solid", fgColor="44546A")
    wrap = Alignment(vertical="top", wrap_text=True)
    plain = Alignment(vertical="top", horizontal="center")

    # A column that is empty on every row invites the reader to wonder what
    # broke. "Cited its own memory entry" is one of those on the held-out set,
    # where no such entry exists to cite.
    columns = [
        column for column in COLUMNS
        if any(str(_value(case, column[1])).strip() for case in cases) or not cases
    ]

    for index, (label, _key, width) in enumerate(columns, start=1):
        cell = sheet.cell(row=1, column=index, value=label)
        cell.font, cell.fill = header, fill
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        sheet.column_dimensions[get_column_letter(index)].width = width

    for row, case in enumerate(cases, start=2):
        for index, (_label, key, _width) in enumerate(columns, start=1):
            value = _value(case, key)
            cell = sheet.cell(row=row, column=index, value=value)
            cell.font = body
            cell.alignment = plain if isinstance(value, (int, float)) else wrap

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{max(len(cases) + 1, 2)}"

    about = book.create_sheet("About this run")
    about.column_dimensions["A"].width = 34
    about.column_dimensions["B"].width = 86

    def line(key: str, value: str, bold: bool = False) -> None:
        row = about.max_row + 1 if about.max_row > 1 or about["A1"].value else 1
        left = about.cell(row=row, column=1, value=key)
        right = about.cell(row=row, column=2, value=value)
        left.font = Font(name=FONT, size=10, bold=True)
        right.font = Font(name=FONT, size=10, bold=bold)
        right.alignment = Alignment(vertical="top", wrap_text=True)

    line("Run", title)
    line("Label in the harness", str(payload.get("label", "")))
    line("Questions graded", str(summary.get("graded", len(cases))))
    if summary:
        line("Agreement with the team", f"{summary.get('agreement', 0)}%", bold=True)
        line("Form (verdict first, no hedging)", f"{summary.get('form', 0)}%")
        line("Held back for a person to read",
             f"{summary.get('held_back', 0)} of {summary.get('graded', 0)}")
        line("Median words — ours / theirs",
             f"{summary.get('median_words_ours', 0)} / {summary.get('median_words_theirs', 0)}"
             "   (reported, never scored)")
        twinned = summary.get("with_a_twin") or {}
        alone = summary.get("without_a_twin") or {}
        line("Where the memory had a near-twin",
             f"{twinned.get('cases', 0)} cases, agreement {twinned.get('agreement', 0)}%")
        line("Where it did not",
             f"{alone.get('cases', 0)} cases, agreement {alone.get('agreement', 0)}%")

    line("", "")
    line("How the judge scores", "Both answers go to the model with one question: does ours "
         "assert the same position as theirs. Not which is better written, and not whether "
         "ours is true — the facts set measures that separately. 5/5 is the same position; "
         "0/5 is the opposite of it.")
    line("", "")
    for verdict, meaning in VERDICTS.items():
        line(verdict, meaning)
    line("", "")
    line("nearest remembered question",
         "Cosine similarity between this question and the closest question in the answer "
         "memory. Above 0.88 the memory has effectively been asked this before.")
    line("would be written",
         "Whether `fill` would write this answer without a person confirming it. "
         "'held for review' means flagged, or below the confidence floor.")

    out.parent.mkdir(parents=True, exist_ok=True)
    book.save(out)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path, help="a JSON file from run_house_eval")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--title", default="")
    args = parser.parse_args()

    payload = json.loads(args.results.read_text(encoding="utf-8"))
    out = args.out or args.results.with_suffix(".xlsx")
    build(payload, out, args.title or str(payload.get("label", args.results.stem)))
    print(f"{len(payload.get('cases') or [])} row(s) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
