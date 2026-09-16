"""The five ways a questionnaire can be read, behind one call.

    rules     the hand-written rules alone. No network, milliseconds, free.
    assisted  the rules, then one model call for each sheet they could not read.
    agent     an agent explores the whole workbook and reads every sheet itself.
    hybrid    the rules, then the agent -- but shown only the sheets they lost.
    guarded   the agent, floored by the rules. The default.

They all return a `DetectedForm` built by `xlsx.read_sheet`, so the questions,
the ids, the targets and the write-back are identical and a difference between
two readings is a difference in understanding, never in machinery.

Two are worth explaining.

`hybrid` is the economical one. `assisted` gives a sheet one look and one
answer; the agent can go and check -- read row 400, search for where a section
starts, notice that a sheet is a continuation of the one before it -- but doing
that for every sheet of every file costs a few hundred thousand tokens and a
minute per workbook, almost all of it spent re-reading sheets the rules already
had right. Pointing it only at the sheets the rules lost keeps the exploring
and drops the bill to nothing on the files that never needed it.

`guarded` is the careful one, and it exists because of one measured failure.
The agent generalises best -- on six questionnaires in shapes nobody had
written a rule for it read 292 of 292, where the rules read 272 -- but its
characteristic mistake is not malformed output, which is caught, but a **quiet
omission**: on one workbook it read six sheets of seven, decided it was
finished, and dropped a whole sheet of five questions without saying so. So the
rules are run as well, and no sheet is allowed to come back with fewer
questions than they found. The rules cost milliseconds and nothing, they never
skip a sheet they can read, and their over-reporting is what the confirmation
panel is for -- a row offered and unticked is recoverable, a row never shown is
not. This is the strategy to use unless you are measuring.

Which of these to run is a decision to make with numbers, and
`scripts/compare_detection.py` is what produces them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.callbacks import get_usage_metadata_callback

from src import forms
from src.forms.model import DetectedForm, Part

STRATEGIES = ("rules", "assisted", "agent", "hybrid", "guarded")


@dataclass
class Reading:
    """A form, and what producing it cost."""

    form: DetectedForm
    strategy: str
    seconds: float = 0.0
    model_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def questions(self) -> int:
        return len(self.form.questions)

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def _tokens(usage) -> tuple[int, int]:
    """(input, output) tokens totalled across every model a block used.

    The agent adds its own up from the conversation it hands back, but the
    single-call fallback goes through `structured_llm`, which returns a
    validated object with the usage stripped off it. Costing one strategy
    properly and estimating the other would make the comparison worthless, so
    both are counted at the callback.
    """
    inputs = sum(u.get("input_tokens", 0) or 0 for u in (usage.usage_metadata or {}).values())
    outputs = sum(u.get("output_tokens", 0) or 0 for u in (usage.usage_metadata or {}).values())
    return inputs, outputs


def _sheet_of(question) -> str:
    """The sheet a question is on. Its id is "sheet!row", and a sheet name may hold "!".

    Split at the first "!", every question on a sheet called "Q! Section" was
    filed under "Q", and the guarded and hybrid readings dropped the sheet.
    """
    return question.id.rsplit("!", 1)[0]


def _lost(form: DetectedForm) -> set[str]:
    """Sheets a reading produced nothing from, and might have been wrong about.

    Hidden and near-empty sheets are excluded: they are skipped on purpose, and
    handing them to an agent would be paying to be told what we already decided.
    """
    return {
        part.name for part in form.parts
        if not part.used and part.kind not in ("hidden", "empty")
    }


def read(path: str | Path, strategy: str = "rules") -> Reading:
    """Read a questionnaire one of four ways."""
    path = Path(path)
    if strategy not in STRATEGIES:
        raise ValueError(f"{strategy!r} is not one of {', '.join(STRATEGIES)}.")

    started = time.monotonic()
    if strategy == "rules":
        return Reading(forms.detect(path, assist=False), strategy,
                       seconds=time.monotonic() - started)

    if strategy == "assisted":
        before = forms.detect(path, assist=False)
        with get_usage_metadata_callback() as usage:
            form = forms.detect(path, assist=True)
        reading = Reading(form, strategy, seconds=time.monotonic() - started)
        reading.input_tokens, reading.output_tokens = _tokens(usage)
        # One call per sheet the rules could not read is the whole cost model,
        # so it is worth stating rather than inferring from a token count.
        reading.model_calls = len(_lost(before))
        if reading.questions > len(before.questions):
            reading.notes.append(
                f"the model added {reading.questions - len(before.questions)} question(s)"
            )
        return reading

    if path.suffix.lower() not in (".xlsx", ".xlsm"):
        # Only spreadsheets have an agent. Falling back to the rules keeps a
        # mixed folder comparable rather than dropping the Word files from it.
        reading = read(path, "rules")
        reading.strategy = strategy
        reading.notes.append("no agent for this format; read by the rules")
        return reading

    from src.agents import excel_agent

    if strategy == "agent":
        form, run = excel_agent.read_workbook(path)
        return _from_run(form, run, strategy)

    if strategy == "guarded":
        form, run = excel_agent.read_workbook(path)
        floored, rescued = _floor(form, forms.detect(path, assist=False))
        reading = _from_run(floored, run, strategy)
        reading.seconds = time.monotonic() - started
        if rescued:
            reading.notes.append(
                "the rules kept " + ", ".join(f"{name!r}" for name in sorted(rescued))
                + " that the agent read for less"
            )
        return reading

    # hybrid
    rules = forms.detect(path, assist=False)
    lost = _lost(rules)
    if not lost:
        reading = Reading(rules, strategy, seconds=time.monotonic() - started)
        reading.notes.append("the rules read every sheet; the agent was not run")
        return reading

    form, run = excel_agent.read_workbook(path, only=lost)
    merged = _merge(rules, form, lost)
    reading = _from_run(merged, run, strategy)
    reading.seconds = time.monotonic() - started
    reading.notes.append(f"the agent was shown {len(lost)} sheet(s) the rules lost")
    return reading


def _from_run(form: DetectedForm, run, strategy: str) -> Reading:
    return Reading(
        form=form,
        strategy=strategy,
        seconds=run.seconds,
        model_calls=run.model_messages,
        tool_calls=run.calls,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        notes=["the agent ran out of steps"] if run.stopped_early else [],
    )


def _merge(rules: DetectedForm, agent: DetectedForm, lost: set[str]) -> DetectedForm:
    """The rules' reading, with the agent's substituted for the sheets it saw.

    Substituted only where the agent actually found something. A sheet it was
    shown and made nothing of keeps the rules' own verdict, which is usually
    the more informative of the two -- "no column holds a run of questions"
    says more than "the agent recorded no reading".
    """
    by_name = {part.name: part for part in agent.parts}
    found: dict[str, list] = {}
    for question in agent.questions:
        found.setdefault(_sheet_of(question), []).append(question)

    merged = DetectedForm(
        source_name=rules.source_name, format=rules.format, warnings=list(rules.warnings)
    )
    for part in rules.parts:
        replacement = by_name.get(part.name)
        if part.name in lost and replacement is not None and replacement.used:
            merged.parts.append(replacement)
            merged.questions.extend(found.get(part.name, []))
        else:
            merged.parts.append(part)
            merged.questions.extend(
                question for question in rules.questions
                if _sheet_of(question) == part.name
            )
    if merged.questions:
        merged.warnings = [w for w in merged.warnings if not w.startswith("No questions")]
    return merged


def _floor(agent: DetectedForm, rules: DetectedForm) -> tuple[DetectedForm, set[str]]:
    """The agent's reading, but never below the rules' on any sheet.

    Sheet by sheet rather than in total, because the failure being guarded
    against is losing a whole sheet, and a total can hide one sheet gained
    against another lost.

    A sheet where the agent found *more* is kept -- reading a form is not a
    thing the rules are authoritative about, and the agent finding two rows the
    rules missed is the reason to run it at all. Only "fewer" is overruled.
    """
    by_name = {part.name: part for part in rules.parts}
    rules_questions: dict[str, list] = {}
    for question in rules.questions:
        rules_questions.setdefault(_sheet_of(question), []).append(question)

    floored = DetectedForm(
        source_name=agent.source_name, format=agent.format, warnings=list(agent.warnings)
    )
    rescued: set[str] = set()
    for part in agent.parts:
        theirs = by_name.get(part.name)
        if theirs is not None and theirs.questions > part.questions:
            floored.parts.append(theirs)
            floored.questions.extend(rules_questions.get(part.name, []))
            rescued.add(part.name)
            continue
        floored.parts.append(part)
        floored.questions.extend(
            question for question in agent.questions
            if _sheet_of(question) == part.name
        )

    # A sheet the agent never mentioned at all, which is the same omission by a
    # different route: it recorded no reading, so no part came back for it.
    seen = {part.name for part in agent.parts}
    for part in rules.parts:
        if part.name not in seen:
            floored.parts.append(part)
            floored.questions.extend(rules_questions.get(part.name, []))
            if part.used:
                rescued.add(part.name)

    if floored.questions:
        floored.warnings = [w for w in floored.warnings if not w.startswith("No questions")]
    return floored, rescued


def disagreements(readings: dict[str, Reading]) -> list[str]:
    """Where two readings of the same file differ, sheet by sheet.

    The point of the comparison. Counts alone hide the case that matters --
    two strategies finding 133 questions each, in different places.
    """
    names: list[str] = []
    counts: dict[str, dict[str, int]] = {}
    for strategy, reading in readings.items():
        for part in reading.form.parts:
            if part.name not in counts:
                counts[part.name] = {}
                names.append(part.name)
            counts[part.name][strategy] = part.questions

    lines = []
    for name in names:
        row = counts[name]
        if len(set(row.get(s, 0) for s in readings)) > 1:
            lines.append(
                f"{name}: " + ", ".join(f"{s} {row.get(s, 0)}" for s in readings)
            )
    return lines


def by_sheet(form: DetectedForm) -> dict[str, Part]:
    return {part.name: part for part in form.parts}
