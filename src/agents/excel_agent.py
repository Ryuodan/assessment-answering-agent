"""Reading a questionnaire workbook by exploring it.

The other two readers are given a fixed view of a sheet and asked one question
about it. This one is given the workbook and a handful of tools, and decides
for itself what to look at: which sheets are worth opening, where on a sheet
the questions start, what a column actually contains three hundred rows down.
Then it records a reading per sheet, and stops.

It exists to be **compared**, not to replace anything, so three things are held
identical to the fallback in `forms.llm_layout`:

* the shape it produces -- a `SheetReading` per sheet;
* the checking that shape goes through -- `llm_layout.apply`, so the same
  invented columns are refused and the same ownership banners still win;
* the code that turns a reading into questions -- `forms.xlsx.read_sheet`.

What differs is only how the reading was arrived at, which is the thing being
measured. The costs of the difference are real and worth naming up front: this
makes many model calls where the fallback makes at most one per unreadable
sheet, it takes tens of seconds where the rules take milliseconds, and it can
be confidently wrong about a sheet the rules would simply have declined. In
exchange it can look at things no fixed view contains -- row 400 of a sheet
whose first screen is a title page, a second sheet that turns out to be a
continuation of the first -- and it needs no rule written for a shape before it
can read it.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from src.config import settings
from src.forms import llm_layout, sheet_view
from src.forms.model import DetectedForm, Finding, FormQuestion, Part, Role
from src.forms.xlsx import unreadable
from src.forms.xlsx_package import Sheet, Workbook
from src.llm import chat_llm

logger = logging.getLogger(__name__)

WINDOW_ROWS = 30
"""Rows returned by one `read_rows` call. Enough to see a section start and
what follows it; small enough that a wandering agent cannot pull a 30,000-row
sheet into the conversation a window at a time."""

MATCHES_SHOWN = 12

SOURCE = "read by the Excel agent"
"""What a finding says about where its reading came from, so a report over a
mixed set of files says which reader produced which column."""


@dataclass
class Run:
    """What one reading of one workbook cost and did.

    Kept because the point of this module is a comparison, and "it found the
    same questions" means something quite different at four seconds and at
    ninety.
    """

    calls: int = 0
    """Tool calls the agent made."""

    model_messages: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    steps: list[str] = field(default_factory=list)
    """A line per tool call, in order, for the report."""

    stopped_early: bool = False
    """True when the step budget ran out before every sheet had a reading."""

    readings: dict[str, "llm_layout.SheetReading"] = field(default_factory=dict)
    """What the agent recorded, by sheet name. Filled by the `record` tool."""

    latest: dict = field(default_factory=dict)
    """The most recent streamed state, so a run that overruns still adds up."""

    counted: set = field(default_factory=set)
    """Message ids already added up, so a second round does not double-count."""


SYSTEM = """You read the layout of questionnaire spreadsheets.

These are cybersecurity and privacy assessments sent by other companies. Every
one is laid out differently: some have a title page, some put their headings on
row 8 under a logo, some split one questionnaire across fifteen sheets, some
mix section headings into the same column as the questions.

Your job is to decide, for every visible sheet, four things:

1. Whether the sheet holds questions somebody is expected to answer. Cover
   pages, instructions, rating scales, legends, revision histories and lookup
   tables do not, however much text they carry.
2. Which row holds the column headings, or 0 if the sheet has none.
3. Which column holds the questions. Judge by what the column contains, not by
   what it is called: a column headed "Questionnaire Type" holding the same
   word 200 times is not the question column; one headed "Security Control"
   holding 183 distinct requirements is.
4. What every other column is for:

     number    the printed question number or reference code
     question  the questions
     answer    free prose we are expected to write
     status    a choice from a fixed list -- a dropdown, or a Yes/No column
     evidence  what to attach or reference
     theirs    a column belonging to whoever SENT this questionnaire, such as
               one headed "for reviewer use" or "to be completed by the bank"
     context   a domain, section, category or clause we only read
     ignore    anything else

Two need care. `status` is usually the column offering a dropdown even when
nothing has been typed into it -- a blank questionnaire's status column is
empty by definition. And `theirs` protects the sender: writing in their column
is worse than leaving a question unanswered.

How to work:

* Call `list_sheets` first.
* Then take the visible sheets **one at a time**: `look_at` it, and `record` it
  straight away, before moving on. Do not look at every sheet first and record
  them all at the end -- these workbooks run to eighteen sheets, and you will
  run out of room before you have recorded anything.
* Use `read_rows` when the top of a sheet is a title page and you need to see
  further down, and `find_rows` to locate where questions start or how far they
  run. Most sheets need neither.
* `record` once per visible sheet, including the ones holding no questions --
  `is_questionnaire=false` is a real answer and is often the right one.
* Stop as soon as every visible sheet has been recorded.

Be economical. A sheet whose shape is obvious from `look_at` needs no further
calls, and workbooks like these usually repeat one layout across every sheet."""


def _make_tools(workbook: Workbook, run: Run, only: set[str] | None = None) -> list:
    """The workbook, as things the agent can do to it.

    Every tool is read-only and bounded. Nothing here can write to the file,
    and nothing can return more than a screenful, so a confused agent costs
    time and tokens but cannot damage anything or run away with the context.

    `only` narrows the workbook to the sheets named, which is what the hybrid
    strategy pays for: the rules read the sixteen sheets they understand, and
    the agent is shown only the two they could not.
    """
    visible = {sheet.name: sheet for sheet in workbook.sheets if sheet.visible and (only is None or sheet.name in only)}

    def _sheet(name: str) -> Sheet | None:
        if name in visible:
            return visible[name]
        # Sheet names come back through a model and arrive with stray quotes or
        # a different case surprisingly often. Matching loosely here costs
        # nothing and saves a retry that costs a call.
        wanted = name.strip().strip("'\"").casefold()
        return next((s for s in visible.values() if s.name.casefold() == wanted), None)

    def _log(step: str) -> None:
        run.calls += 1
        run.steps.append(step)

    def list_sheets() -> str:
        """List every sheet you are being asked about, with its size. Call this first."""
        _log("list_sheets")
        lines = [
            f"{sheet.name!r}: {len(sheet.rows)} row(s), {len(sheet.columns)} column(s) holding values"
            for sheet in workbook.sheets
            if sheet.name in visible
        ]
        return "\n".join(lines) or "(no sheets)"

    def look_at(sheet_name: str) -> str:
        """Show the top of a sheet and what each of its columns holds.

        Args:
            sheet_name: the sheet to look at, exactly as `list_sheets` named it.
        """
        _log(f"look_at({sheet_name!r})")
        sheet = _sheet(sheet_name)
        if sheet is None:
            return f"There is no visible sheet called {sheet_name!r}."
        if sheet.name in run.readings:
            # Sending the description again pays for the same screenful twice
            # and invites a loop, which is how the first eighteen-sheet
            # workbook ran out of steps.
            return f"{sheet.name!r} is already recorded. Move on to one that is not."
        return sheet_view.describe(workbook, sheet)

    def read_rows(sheet_name: str, first_row: int) -> str:
        """Read a window of rows, for when the top of a sheet is a title page.

        Args:
            sheet_name: the sheet to read.
            first_row: the row number to start at.
        """
        _log(f"read_rows({sheet_name!r}, {first_row})")
        sheet = _sheet(sheet_name)
        if sheet is None:
            return f"There is no visible sheet called {sheet_name!r}."
        rows = [row for row in sheet.rows if row >= first_row][:WINDOW_ROWS]
        if not rows:
            return f"Nothing on or after row {first_row}; the sheet ends at {max(sheet.rows, default=0)}."
        lines = []
        for row in rows:
            cells = [
                f"{column}: {sheet_view.cell(sheet.value(row, column))}"
                for column in sheet.columns[: sheet_view.GRID_COLUMNS]
                if sheet.value(row, column)
            ]
            lines.append(f"row {row} | " + (" | ".join(cells) if cells else "(blank)"))
        return "\n".join(lines)

    def find_rows(sheet_name: str, text: str) -> str:
        """Find rows containing some text, to locate where questions start.

        Args:
            sheet_name: the sheet to search.
            text: what to look for, matched case-insensitively anywhere in a cell.
        """
        _log(f"find_rows({sheet_name!r}, {text!r})")
        sheet = _sheet(sheet_name)
        if sheet is None:
            return f"There is no visible sheet called {sheet_name!r}."
        needle = text.strip().casefold()
        if not needle:
            return "Give some text to look for."
        hits = [
            f"row {row}, column {column}: {sheet_view.cell(value)}"
            for (row, column), value in sorted(sheet.cells.items())
            if needle in value.casefold()
        ]
        if not hits:
            return f"No cell on {sheet.name!r} contains {text!r}."
        shown = hits[:MATCHES_SHOWN]
        more = "" if len(hits) <= MATCHES_SHOWN else f"\n... and {len(hits) - MATCHES_SHOWN} more"
        return "\n".join(shown) + more

    def record(
        sheet_name: str,
        is_questionnaire: bool,
        header_row: int = 0,
        question_column: str = "",
        column_roles: str = "",
        reason: str = "",
    ) -> str:
        """Record your reading of one sheet. Call this once per visible sheet.

        Args:
            sheet_name: the sheet being recorded.
            is_questionnaire: whether it holds questions somebody must answer.
            header_row: the row carrying the column headings, or 0 if none.
            question_column: the column letter holding the questions.
            column_roles: the other columns, as "A=number, C=status, D=answer".
            reason: one sentence a person could check against the sheet.
        """
        _log(f"record({sheet_name!r}, questionnaire={is_questionnaire})")
        sheet = _sheet(sheet_name)
        if sheet is None:
            return f"There is no visible sheet called {sheet_name!r}."

        run.readings[sheet.name] = llm_layout.SheetReading(
            is_questionnaire=is_questionnaire,
            header_row=header_row,
            question_column=question_column,
            columns=_parse_roles(column_roles),
            reason=reason,
        )
        left = [name for name in visible if name not in run.readings]
        if left:
            return f"Recorded. Still to do: {', '.join(repr(name) for name in left)}."
        return "Recorded. Every visible sheet now has a reading — stop here."

    return [list_sheets, look_at, read_rows, find_rows, record]


def _parse_roles(text: str) -> list[llm_layout.ColumnReading]:
    """Read "A=number, C=status, D=answer" into column roles.

    A string rather than a list of objects because nested arguments are where
    tool calls go wrong most often, and this is the one argument the agent
    fills in on every single call. Anything unparseable is dropped rather than
    failing the call -- a reading with two of its three columns understood is
    worth more than a refusal.
    """
    roles: list[llm_layout.ColumnReading] = []
    allowed = {role.value for role in Role}
    for piece in text.replace(";", ",").split(","):
        if "=" not in piece:
            continue
        column, _, role = piece.partition("=")
        column = "".join(c for c in column.strip().upper() if c.isalpha())
        role = role.strip().lower()
        if column and role in allowed:
            roles.append(llm_layout.ColumnReading(column=column, role=role))
    return roles


CONTEXT_TRIGGER = 12_000
"""Input tokens after which old tool results are cleared from the conversation.

Every screenful the agent has looked at stays in the conversation and is resent
with every later turn, so an eighteen-sheet workbook cost 342,000 input tokens
to produce the same 134 questions the rules produce for nothing -- most of it
re-reading descriptions of sheets it had already recorded.

Clearing them is safe here in a way it would not be in a general agent: a
reading is recorded into `Run.readings` the moment it is made, so the answer
lives outside the conversation and losing the transcript of how it was reached
costs nothing. The most recent few results are kept, because those are the ones
it is still working from.

Set low deliberately. The threshold is the size of *one* request, not of the
run, and one request here rarely passes 30,000 tokens even when the run totals
ten times that -- a higher trigger simply never fires.
"""

CONTEXT_KEEP = 4


def _agent(tools: list, model: str | None = None):
    from langchain.agents import create_agent
    from langchain.agents.middleware import ClearToolUsesEdit, ContextEditingMiddleware

    return create_agent(
        chat_llm(temperature=0.0, model=model),
        tools=tools,
        system_prompt=SYSTEM,
        middleware=[
            ContextEditingMiddleware(
                edits=[ClearToolUsesEdit(trigger=CONTEXT_TRIGGER, keep=CONTEXT_KEEP)],
            )
        ],
    )


def _round(workbook: Workbook, run: Run, path: Path, sheets: set[str], tools: list, steps: int) -> None:
    """One conversation with the agent, over the sheets named."""
    named = ", ".join(sorted(repr(name) for name in sheets))
    try:
        # Streamed rather than invoked, so a run that hits its budget still
        # reports what it spent. `invoke` raises and takes the whole
        # conversation with it, and a comparison that cannot say what the
        # failures cost is not much of a comparison.
        for chunk in _agent(tools).stream(
            {
                "messages": [
                    (
                        "user",
                        f"Read the layout of {path.name!r}. "
                        f"Record a reading for each of these sheets, then stop: "
                        f"{named}.",
                    )
                ]
            },
            {"recursion_limit": steps},
            stream_mode="values",
        ):
            run.latest = chunk
    except Exception as failed:
        # A step budget reached, a provider error, a tool loop. Whatever the
        # agent recorded before it stopped is still usable, so the readings are
        # applied rather than the whole workbook being thrown away.
        logger.warning("The Excel agent stopped early on %s: %s", path.name, failed)
        run.stopped_early = True
    _add_up(run)


def _add_up(run: Run) -> None:
    """Total what the latest conversation cost, and add it to the run.

    Cumulative across rounds, and by message id rather than by round, because a
    second round is a fresh conversation over the sheets the first forgot:
    counting only the last would report a workbook that needed chasing as
    cheaper than one that did not, and re-totalling the state at every stream
    chunk would count the same message dozens of times.
    """
    for message in (run.latest or {}).get("messages", []):
        usage = getattr(message, "usage_metadata", None) or {}
        if not usage:
            continue
        seen = getattr(message, "id", None)
        if seen is not None and seen in run.counted:
            continue
        if seen is not None:
            run.counted.add(seen)
        run.model_messages += 1
        run.input_tokens += usage.get("input_tokens", 0) or 0
        run.output_tokens += usage.get("output_tokens", 0) or 0


STEPS_PER_SHEET = 6
"""Graph steps allowed per visible sheet.

A sheet costs at least four -- a model turn and a tool call to look at it, the
same again to record it -- and the budget has to leave room for the occasional
`read_rows`. A fixed budget was the first thing to break: 60 steps ran out
halfway through an eighteen-sheet workbook, and the six sheets it never reached
came back empty against 53 questions the rules had found in them.
"""

STEPS_FLOOR = 24

STEPS_CEILING = 200
"""And a ceiling, because the budget is derived from the file.

These arrive from other companies over a public endpoint. A workbook with two
hundred sheets -- whether by accident or on purpose -- would otherwise buy
itself an unbounded run at our expense. Hitting the ceiling is not a failure:
the sheets that were read are kept, and the rest are reported as "not read".
"""


def budget(sheets: int) -> int:
    """How many graph steps a run over `sheets` sheets is worth."""
    wanted = max(STEPS_FLOOR, settings.excel_agent_max_steps, STEPS_PER_SHEET * sheets + 12)
    return min(wanted, STEPS_CEILING)


def read_workbook(
    path: str | Path, *, max_steps: int | None = None, only: set[str] | None = None
) -> tuple[DetectedForm, Run]:
    """Read a workbook with the agent. Returns the form and what it cost.

    The form is built by the same code every other reader uses, so it can be
    filled, answered and written back exactly as if the rules had produced it.

    `only` limits the agent to the named sheets. Everything else comes back as
    "not read", for a caller that already has its own reading of those.
    """
    path = Path(path)
    form = DetectedForm(source_name=path.name, format="xlsx")
    run = Run()
    started = time.monotonic()

    with Workbook(path) as workbook:
        tools = _make_tools(workbook, run, only)
        asked = sum(1 for sheet in workbook.sheets if sheet.visible and (only is None or sheet.name in only))
        steps = max_steps or budget(asked)
        wanted = {sheet.name for sheet in workbook.sheets if sheet.visible and (only is None or sheet.name in only)}
        _round(workbook, run, path, wanted, tools, steps)

        # A second round, for sheets it simply forgot. On the Zain form the
        # agent recorded five sheets of seven and stopped -- not out of budget,
        # just finished -- and the two it never mentioned held twelve questions.
        #
        # Started fresh rather than continued. Handing back the conversation it
        # had just decided it was finished with put it straight back into the
        # same state, and near its budget besides; a clean context holding only
        # the sheets it missed is shorter, cheaper and far likelier to work.
        missed = wanted - set(run.readings)
        if missed and not run.stopped_early:
            logger.info(
                "Asking the Excel agent again about %s on %s",
                ", ".join(sorted(repr(name) for name in missed)),
                path.name,
            )
            _round(workbook, run, path, missed, _make_tools(workbook, run, missed), budget(len(missed)))

        still = sorted(wanted - set(run.readings))
        if still:
            logger.warning("The Excel agent never read %s on %s", ", ".join(repr(name) for name in still), path.name)

        for sheet in workbook.sheets:
            part, questions = _read(workbook, sheet, run)
            form.parts.append(part)
            form.questions.extend(questions)

    run.seconds = time.monotonic() - started
    if not form.questions:
        form.warnings.append(
            "No questions were found. The sheets were read as: "
            + ", ".join(f"{part.name} ({part.kind})" for part in form.parts)
        )
    return form, run


def _read(workbook: Workbook, sheet: Sheet, run: Run) -> tuple[Part, list[FormQuestion]]:
    """Turn one recorded reading into questions, or say why there are none."""
    skipped = unreadable(sheet)
    if skipped is not None:
        return skipped, []

    reading = run.readings.get(sheet.name)
    if reading is None:
        return Part(
            name=sheet.name,
            kind="not read",
            findings=[
                Finding(
                    subject=sheet.name,
                    verdict="skipped",
                    because="the agent stopped before reading this sheet"
                    if run.stopped_early
                    else "the agent recorded no reading for this sheet",
                    confident=False,
                )
            ],
        ), []

    applied = llm_layout.apply(workbook, sheet, reading, source=SOURCE)
    if applied is None:
        because = (
            f"read by the agent as holding no answerable questions — {reading.reason}"
            if not reading.is_questionnaire
            else "the agent's reading did not describe this sheet, so it was refused"
        )
        return Part(
            name=sheet.name,
            kind="no questions",
            findings=[Finding(subject=sheet.name, verdict="skipped", because=because, confident=False)],
        ), []
    return applied


def detect(path: str | Path, *, max_steps: int | None = None) -> DetectedForm:
    """Read a workbook with the agent, discarding the accounting.

    Signature-compatible with `forms.xlsx.detect`, so the two can be swapped in
    a comparison harness without anything else changing.
    """
    return read_workbook(path, max_steps=max_steps)[0]
