"""Compare the four ways of reading a questionnaire, on real files.

    python -m scripts.compare_detection "C:/path/to/questionnaires"
    python -m scripts.compare_detection ./new --strategies rules,hybrid --write
    python -m scripts.compare_detection ./new --json results.json -v

The strategies are described in `src.forms.reading`. What this adds is the
measurement, and it reports three separate things because they answer different
questions:

* **How many questions each found.** The headline, and the least trustworthy
  number on its own -- more is not better if the extras are section headings,
  and equal counts can still be different questions.
* **Where they disagreed, sheet by sheet.** This is what to read. A sheet where
  one strategy found 13 and another found 0 is either a rescue or a
  hallucination, and only opening the file settles which.
* **What each cost.** Seconds, model calls and tokens per file. A reading that
  is one question better and two hundred times more expensive is a decision,
  not an improvement.

With `--write` it also answers every question into a temporary copy per
strategy and checks the file survived, because a reading that cannot be written
back is not a reading. That is the one place a wrong column becomes damage, and
it is worth knowing before choosing.

There is no ground truth here. These files arrive from other companies and
nobody has counted them by hand, so the script reports agreement and difference
and leaves the adjudicating to a person with the spreadsheet open.
"""

from __future__ import annotations

import argparse
import functools
import json
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Flushed, because a four-way run over a folder of real questionnaires takes
# twenty minutes and most of it is the agent. Redirected to a file, buffered
# output shows nothing at all until the end, and somebody watching cannot tell
# a slow run from a stuck one.
print = functools.partial(print, flush=True)  # noqa: A001

from src import forms  # noqa: E402
from src.forms import reading as reading_module  # noqa: E402
from src.forms.reading import Reading, disagreements, read  # noqa: E402
from src.forms.model import Role  # noqa: E402
from scripts.check_forms import _answers, _parts  # noqa: E402


def _write_back(path: Path, form, destination: Path, strategy: str) -> str:
    """Answer this reading into a copy, and say in a few words how it went.

    Two separate things have to survive, and only one of them is the file.

    The package must come through -- no part lost, nothing rewritten that did
    not hold an answer. And the *reading* must come through: re-opening the
    half-answered copy has to find the same questions in the same places, or
    somebody who fills in half a questionnaire on Monday and re-uploads it on
    Tuesday gets a different set of targets and their answers land nowhere.

    Checking only the first is how a file that wrote 32 values and could not
    find one of them again was reported as `ok`.
    """
    values = _answers(form)
    if not values:
        return "nothing writable"
    try:
        result = forms.write(path, destination, values)
    except Exception as error:
        return f"WRITE FAILED: {type(error).__name__}"

    before, after = _parts(path), _parts(destination)
    lost = sorted(set(before) - set(after))
    changed = [
        name
        for name in sorted(set(before) & set(after))
        if before[name] != after[name] and not name.startswith("xl/worksheets/")
    ]
    if path.suffix.lower() == ".docx":
        changed = [name for name in changed if not name.endswith((".xml", ".rels"))]

    if lost:
        return f"LOST {len(lost)} PART(S)"
    if changed:
        return f"{len(changed)} PART(S) CHANGED THAT SHOULD NOT HAVE"
    if not result.intact:
        return "NOT INTACT"

    # Re-read the copy the same way it was read the first time, so this
    # measures the strategy rather than always measuring the rules.
    again = read(destination, strategy).form
    landed = sum(
        1
        for question in again.questions
        for target in question.writable
        if target.role in (Role.ANSWER, Role.STATUS) and target.existing.strip()
    )
    stable = [q.id for q in again.questions] == [q.id for q in form.questions]
    if not stable:
        return f"UNSTABLE: re-opened as {len(again.questions)} question(s), not {len(form.questions)}"
    if landed < len(values) * 0.97:
        return f"LOST ANSWERS: read back {landed} of {len(values)}"
    return f"ok, wrote {result.written}, re-read {landed}"


def compare(path: Path, strategies: list[str], *, write: bool, workspace: Path, verbose: bool) -> dict:
    """Read one file every way asked for, and report."""
    print(f"\n{'=' * 100}\n{path.name}")
    readings: dict[str, Reading] = {}
    row: dict = {"file": path.name, "strategies": {}}

    for strategy in strategies:
        try:
            result = read(path, strategy)
        except Exception as error:
            print(f"  {strategy:9s} !! {type(error).__name__}: {error}")
            if verbose:
                traceback.print_exc()
            row["strategies"][strategy] = {"error": f"{type(error).__name__}: {error}"}
            continue

        readings[strategy] = result
        sheets = sum(1 for part in result.form.parts if part.used)
        unsure = sum(1 for part in result.form.parts for finding in part.findings if not finding.confident)
        line = (
            f"  {strategy:9s} {result.questions:5d} question(s)  {sheets:3d} sheet(s)  "
            f"{result.seconds:7.2f}s  {result.model_calls:3d} model call(s)  "
            f"{result.tokens:8d} token(s)  {unsure:3d} to check"
        )
        if result.tool_calls:
            line += f"  {result.tool_calls} tool call(s)"
        print(line)
        for note in result.notes:
            print(f"             - {note}")

        entry = {
            "questions": result.questions,
            "sheets": sheets,
            "seconds": round(result.seconds, 2),
            "model_calls": result.model_calls,
            "tool_calls": result.tool_calls,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "unconfident_findings": unsure,
            "notes": result.notes,
        }
        if write:
            destination = workspace / f"{strategy}-{path.name}"
            entry["write_back"] = _write_back(path, result.form, destination, strategy)
            print(f"             write-back: {entry['write_back']}")
        row["strategies"][strategy] = entry

    differences = disagreements(readings)
    row["disagreements"] = differences
    if differences:
        print(f"  --- disagreed on {len(differences)} sheet(s) ---")
        for line in differences:
            print(f"      {line}")
    elif len(readings) > 1:
        print("  --- every strategy read every sheet the same way ---")

    if verbose:
        for strategy, result in readings.items():
            unsure = [
                (part.name, finding) for part in result.form.parts for finding in part.findings if not finding.confident
            ]
            for name, finding in unsure[:12]:
                print(
                    f"      [{strategy}] {name[:20]:20s} {finding.subject[:18]:18s} "
                    f"-> {finding.verdict:10s} {finding.because[:60]}"
                )
    return row


def summarise(rows: list[dict], strategies: list[str]) -> None:
    print(f"\n{'=' * 100}\nSUMMARY over {len(rows)} file(s)\n")
    header = (
        f"  {'strategy':10s} {'questions':>10s} {'seconds':>9s} {'model calls':>12s} {'tokens':>10s} {'failures':>9s}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for strategy in strategies:
        entries = [
            row["strategies"][strategy]
            for row in rows
            if strategy in row["strategies"] and "error" not in row["strategies"][strategy]
        ]
        # Anything that did not start with "ok" is a failure. Testing for an
        # all-upper-case message missed `UNSTABLE: re-opened as 0 question(s)`,
        # which is the most serious result this script can produce.
        failures = sum(
            1
            for row in rows
            if strategy not in row["strategies"]
            or "error" in row["strategies"][strategy]
            or not str(row["strategies"][strategy].get("write_back", "ok")).startswith(("ok", "nothing writable"))
        )
        print(
            f"  {strategy:10s} {sum(e['questions'] for e in entries):10d} "
            f"{sum(e['seconds'] for e in entries):9.1f} "
            f"{sum(e['model_calls'] for e in entries):12d} "
            f"{sum(e['input_tokens'] + e['output_tokens'] for e in entries):10d} "
            f"{failures:9d}"
        )

    disputed = [row for row in rows if row["disagreements"]]
    print(f"\n  {len(disputed)} of {len(rows)} file(s) read differently by different strategies.")
    for row in disputed:
        print(f"    {row['file']}: {len(row['disagreements'])} sheet(s)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path, help="Directory of questionnaires")
    parser.add_argument(
        "--strategies",
        default=",".join(reading_module.STRATEGIES),
        help="Comma-separated: " + ", ".join(reading_module.STRATEGIES),
    )
    parser.add_argument("--write", action="store_true", help="Also answer each reading into a copy and check fidelity")
    parser.add_argument("--json", type=Path, help="Write the results here as JSON")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show the readings marked for checking, and tracebacks"
    )
    args = parser.parse_args()

    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    unknown = [s for s in strategies if s not in reading_module.STRATEGIES]
    if unknown:
        print(f"Unknown strateg(ies): {', '.join(unknown)}", file=sys.stderr)
        return 2
    if not args.folder.is_dir():
        print(f"Not a directory: {args.folder}", file=sys.stderr)
        return 2

    files = sorted(
        path
        for path in args.folder.rglob("*")
        if path.suffix.lower() in forms.SUPPORTED and not path.name.startswith("~$")
    )
    if not files:
        print(f"No {' or '.join(forms.SUPPORTED)} files under {args.folder}", file=sys.stderr)
        return 2

    print(f"Reading {len(files)} file(s) {len(strategies)} way(s): {', '.join(strategies)}")
    workspace = Path(tempfile.mkdtemp(prefix="compare_detection_"))
    rows = []
    try:
        for path in files:
            rows.append(compare(path, strategies, write=args.write, workspace=workspace, verbose=args.verbose))
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    summarise(rows, strategies)
    if args.json:
        args.json.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf8")
        print(f"\n  wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
