# Questionnaires

Reading a customer's questionnaire, answering it, and writing the answers back into the file.

Moved from the README (plan 009); the text is as it was written there, with links re-pointed.

## Filling in a questionnaire

`src/forms` reads a customer's questionnaire and writes answers back into it.
Two functions, one module per format:

```python
form = forms.detect(path)                      # questions, and where answers go
forms.write(path, destination, {target: text}) # a copy, with the answers in it
```

A question usually has more than one place to write: a **status** chosen from
the file's own dropdown and a **comment** in prose. The vocabularies disagree
between files -- one wants `Fully Implemented`, another `Fully Compliant`, a
third `FC` -- so they are read out of the workbook rather than kept here.
Evidence columns are left blank by default.

**Some columns belong to whoever sent the form.** `Compliance (To be updated by
BAB)` reads as an ordinary status column by every other rule, and one workbook
declares ownership in a merged banner a row *above* its headings. Answering
there would be worse than leaving a question blank, so ownership is checked
first and those columns are never written.

### Reading it

Structure decides the layout, not wording. Vocabulary alone put the questions in
a column headed `Questionnaire Type` -- which contains the repeated word
"Enterprise" -- because the heading contains "question"; and it found nothing at
all in a workbook whose fifteen sheets head their questions `HR Security`,
`Physical Security` and so on. So the question column is the one that *behaves*
like questions, with a matching heading as a tiebreak rather than a requirement.
Sheets with no headings at all are read from their numbering, and everything
inferred that way is marked as a proposal for someone to confirm.

**A form of one or two questions is read from its headings alone.** A column
needs three question rows before its shape counts, because below that a column
of sentences under a heading is usually a legend -- two workbooks explain their
compliance ratings that way. So a shorter one is read only when its header row
says so twice: a column headed as the questions, and a column headed as an
answer, a status or evidence. `# | Question | Answer` over two numbered rows is
a form; `# | Question | Domain` is a list. It is the reading of last resort,
taken only when no other column and no headless reading was found, so no sheet
the rules already read reads any differently, and a short sheet without a
numbering column is still refused as a reference table. Every two-question
questionnaire the end-to-end checks uploaded was this shape, and the rules read
each one as nothing (TD-043); the fixture is `short_numbered`.

Against the eleven real workbooks it finds **831 questions where counting the
printed item numbers by hand finds 824** -- all of them, plus seven extras.
Erring that way is deliberate: a confirmation step can remove a row it was
offered and cannot recover one it never saw.

### Writing it

Every target is an **upsert**, and which of the two happened is reported. In the
sample files the destination was missing in three different ways: absent from
the XML entirely, present as an empty string, and -- in the prose Word document
-- not existing as a paragraph at all. A half-finished questionnaire is an
ordinary upload, so the same call has to create or replace per target.

Workbooks are edited as XML in place: only the sheets holding answers are
rewritten and every other part is copied byte for byte. That is measured, not
preferred -- a load-and-save through openpyxl dropped sixteen drawings from one
real file and every cell comment from another, and mangled most conditional
formatting. A cell holding a formula is refused outright, because one workbook
scores itself from 93 formulas on a hidden sheet.

**Even the sheets holding answers keep every byte but the answers.** The
answered cells are spliced into the worksheet's own XML. It used to be parsed
and serialised again, which renamed every namespace prefix but the main one and
dropped the declarations it did not see used -- so the `mc:Ignorable="x14ac xr
xr2 xr3"` that Excel writes on every worksheet named prefixes that no longer
existed, and **Excel refused to open the filled file**. Google Sheets exports do
not carry that attribute, which is why the files tested day to day never showed
it; the team's Zain form does. Checked with Excel itself: the Zain form's filled
copy failed to open before and opens now, as do all twenty-one real
questionnaires filled in every writable cell, and an Excel-saved form taken
through the assistant, the fill button and the download. A sheet shaped in a way
the splice does not recognise -- rows without numbers, say -- still falls back to
the old rewrite.

Text is made safe for the file before it goes in, for every format: characters
XML may not hold (a vertical tab, a form feed -- a model's output can carry
them) are removed, and an Excel cell is capped at the 32,767 characters Excel
accepts. One such character used to fail a whole Word fill, and the Word export
beside it.

**A cell gets text, not Markdown.** The drafter writes `**bold**`, bullets and
the occasional heading, which the answer cards and the exports render. A
spreadsheet or Word cell shows them literally: 96 of the 1,687 answers stored
against questionnaires carried bold markers, and a filled Fabrikam questionnaire
went back with `**Identifiers** –` in a cell. The fill now writes
`formatting.to_cell_text` -- emphasis removed, bullets as `•`, numbering kept, a
blank line between paragraphs kept.

Word documents go through python-docx, which re-serialises every XML part it
loads. That reformatting is cosmetic -- nothing is lost or added, relationships
come out identical, and every image and embedded font is byte-identical -- but
it is a weaker guarantee than the workbook side, and worth knowing. An Arabic
answer marks its paragraph and runs right-to-left once: filling a document that
had already been filled used to append a second `w:bidi` to every answer, which
Word forgives and the schema does not.

**Detection has to survive its own output.** Filling the answer column made it
the column with the most prose, because plenty of real questions are as short as
`Company Name:`, so re-opening a half-finished workbook moved the questions into
the answer column and every target with them. There is a test for that on every
fixture shape.

**A question is named the way its document names it.** Every question carries
the place it came from, and that place is shown beside it, so a reading can be
checked against the file rather than taken on trust. A spreadsheet row gives
`Human Resources, row 12`. A prose Word question gives `Cybersecurity
Governance, Q1` -- the section and the printed number, not `paragraph 142`,
which is a count nothing in Word will show you. A Word *table* gives the
heading printed above the table, read from the document body in order, because
`document.tables` and `document.paragraphs` are each flattened separately and
cannot be zipped back together; where there is no heading and no numbering
column, it falls back to `table 2, row 5`.

### Five ways to read a questionnaire

The rules above read every file we had. They get there by describing shapes we
have seen, which is exactly the thing that does not generalise -- a
questionnaire arriving in a shape nobody wrote a rule for comes back "no column
holds a run of questions", and a whole sheet is silently lost. So there are
four more readers, and one call to choose between them:

```python
from src.forms.reading import read
read(path, "rules")      # the rules alone
read(path, "assisted")   # the rules, then one model call per sheet they lost
read(path, "agent")      # an agent explores the workbook and reads it all
read(path, "hybrid")     # the rules, then the agent -- shown only what they lost
read(path, "guarded")    # the agent, floored by the rules. The default.
```

All four end at `xlsx.read_sheet`, so the question ids, the targets, the
locations and the write-back are byte-identical between them. A difference
between two readings is a difference in understanding and never in machinery,
which is what makes them comparable at all.

**The model is asked about structure, never about content.** It answers one
question -- which row heads this sheet, which column asks, and what is every
other column for -- and the ordinary reader does the rest. That split carries
four guarantees, and they are the reason this is safe to turn on:

* It cannot invent a question. Question text is read out of cells, so a
  hallucinated question has nowhere to come from.
* It cannot invent a place to write. Targets are built from real cell
  references by the same code as always.
* It cannot take the assessing bank's column. A `To be filled by ...` banner
  still overrides whatever it said, because that is the one mistake worse than
  leaving a question blank.
* It is checked and it is monotone. A reading naming a column that holds
  nothing, or a header row that does not exist, is refused; a reading that
  yields no questions is discarded; and an assisted reading replaces the rules'
  only when it finds *more*. Turning assistance on can rescue a sheet the rules
  lost and cannot damage one they read correctly.

Everything a model produced is marked unconfident, which puts it at the top of
the confirmation panel with its reasoning attached.

**The trigger is emptiness or thinness.** A sheet the rules found nothing on is
offered to the model. So is one where fewer than a quarter of the rows below
the header became questions -- seven questions on a sheet of 133 rows is a
wrong column, not a short questionnaire, and that failure never reports itself.

#### What the agent is, and what it costs

`src/agents/excel_agent.py` is the alternative: an agent with five read-only
tools over the workbook -- list the sheets, look at one, read a window of rows,
search for text, record a reading -- that decides for itself what to look at.
It needs no rule written for a shape before it can read it, and it can look at
things no fixed view contains: row 400 of a sheet whose first screen is a title
page, or a sheet that turns out to be a continuation of the one before it.

Measured over the nineteen real questionnaires, where the rules are already
right, with every reading also answered into a copy and checked for fidelity:

| strategy | questions | seconds | model calls | tokens  | write failures |
|----------|-----------|---------|-------------|---------|----------------|
| rules    | **1601**  | 2.7     | 0           | 0       | 0 |
| assisted | **1601**  | 27.0    | 14          | 20,166  | 0 |
| agent    | 1598      | 190.7   | 143         | 668,765 | 0 |
| hybrid   | **1601**  | 35.4    | 50          | 78,364  | 0 |

Every one of the 76 readings was also answered into a copy and read back
without losing a package part, so all four are equally safe to *write*. What
separates them is what they see and what they cost.

The agent is the only one that loses questions, and it loses them the way an
agent does rather than the way a parser does: on the Zain form it read six of
seven sheets, decided it was finished, and dropped `7. 3TG + Cobalt` (5
questions) without noticing. It also found two questions on the Murabbah sheet
the other three did not -- two rescues or two section headings, and only
somebody with the file open can say which. That is the shape of the risk: not
malformed output, which is caught, but a confident and quiet omission.

Two of its failures were worth fixing and were fixed. It used to stop after
*five* sheets on that form, losing twelve questions; it is now asked a second
time, on a fresh conversation, naming the sheets it never recorded -- fresh
because handing back the conversation it had just decided it was finished with
put it straight back into the same state. And a fixed step budget was the first
thing to break at all: 60 steps ran out halfway through the eighteen-sheet ISRA
workbook, and the six sheets it never reached came back empty against 53
questions the rules had found in them. The budget now scales with the sheet
count, between a floor and a ceiling, and a run that overruns still applies
whatever it recorded before it stopped.

The cost, though, is structural and did not move. Roughly two model calls per
sheet, each resending the conversation so far: 669,000 tokens and three minutes
across nineteen files, against the fallback's 20,000 and the rules' nothing.
Old tool results are cleared once a request passes 12,000 tokens -- safe here
only because a reading is recorded outside the conversation the moment it is
made -- and it barely dents the total, because the total is the call count and
not the context length.

`hybrid` exists because the exploring is worth keeping and the re-reading is
not. The rules read the sheets they understand; the agent is shown only the
ones they lost. On the ISRA workbook that is 3.3 seconds and 5,684 tokens
against the full agent's 58 seconds and 342,000, for the same answer. Across
all nineteen it is a ninth of the agent's tokens and finds three more
questions, because the sheets the rules read are simply never at risk.

On this corpus none of that matters, because the rules are already right on all
nineteen files -- which is exactly why the corpus cannot settle the question.
The measurement that decides it is the one over files nobody has written a rule
for.

#### What six unseen questionnaires settled

The nineteen files above could not decide anything, because the rules are right
on all of them. Six more arrived later, in shapes nobody had written a rule for
-- a two-row header, a sheet whose reference column is headed `ID`, and one
whose header row reads `Queations | Answer`, a single typo from being
recognised at all. The item numbers printed in each were counted by hand first,
so this is measured against a known answer rather than against agreement:

| strategy | found | of 292 | seconds | model calls | tokens  | re-open failures |
|----------|-------|--------|---------|-------------|---------|------------------|
| rules    | 272   | 93.2%  | 0.7     | 0           | 0       | **2** |
| assisted | 290   | 99.3%  | 9.3     | 4           | 5,686   | 0 |
| agent    | **292** | **100%** | 24.9 | 36          | 73,926  | 0 |
| hybrid   | 290   | 99.3%  | 8.9     | 15          | 21,312  | 0 |

Everything the rules missed traces to one workbook. Its reference column is
headed `ID`, which no rule recognised, so there was no numbering column to
vouch for a short question -- and `Organisation name`, `Email address` and `Do
you maintain an incident register` are all short and none ends in a question
mark. That cost a whole sheet of nine and one question on another.

`assisted` and `hybrid` recovered the lost sheet and not the single question,
and the reason is structural rather than a matter of tuning: **a fallback fires
only where the rules found nothing or almost nothing.** 63 of 64 is a 98%
reading, far above any thinness threshold, so no second opinion was asked. A
fallback can rescue a lost sheet; it cannot repair a nearly-right one. Only a
reader that reads every sheet itself can.

**The column the counts hide is the last one.** Re-opening a half-answered copy
-- somebody fills in a questionnaire on Monday and comes back to it on Tuesday
-- the rules read that `Queations | Answer` workbook as **0 questions, not 32**.
Blank, its question column has 30 rows of prose and wins; once the answers are
written the answer column has 32 and takes its place. The three model-backed
strategies all survive it, because the rules returning nothing is exactly the
condition that fires the fallback. All four read the blank file identically,
and only three can pick the work back up.

#### And then the rules were fixed

The table above is the measurement, taken before anything was changed, and it
stays as it is: it is the only evidence about generalisation there will ever be
for these six files, and re-running it after fixing the rules would measure
nothing. What follows is what the measurement bought.

Everything the rules missed traced to two causes, and both are narrow enough to
fix without inventing a rule for one customer's spreadsheet:

**A reference column headed `ID`.** `_NUMBER_EXACT` now recognises `ID`, `Ref`,
`No`, `Code` and a few others, matched *whole* rather than as substrings --
`id` sits inside `Identity and Access Management` and `no` inside `Notes`, and
matching those loosely would put a domain column into the numbering role. With
a numbering column present, a short question no longer has to end in a question
mark to be recognised, which is what `Organisation name`, `Email address` and
`Do you maintain an incident register` needed.

**A header row one typo from being recognised.** `Queations | Answer` has only
one heading any rule knows, so the row does not qualify as a header and the
sheet is read headless. The headless reader now consults that row anyway: a
column whose own short label reads as the answer is *excluded* from being the
question column, not merely penalised, because an answer can be arbitrarily
longer than the question it answers and any penalty can be out-scored. Only
labels shorter than `LONG_TEXT` count -- a sentence in the first row is data.

After both: the rules read **292 of 292** on the six unseen files, and the whole
corpus of 25 files comes through at **1,893 questions, 0 write-back failures**,
including the re-open check that the typo workbook used to fail 32-to-0.

Both shapes are in `tests/forms_fixtures.py` as `reference_column_headed_id`
and `headless_typo_header`, because the customer files cannot be committed and
a fix without a fixture is a fix that comes back.

This changes nothing about the default. The rules now handle these two shapes;
the seventh unfamiliar questionnaire will be a third shape, and the argument
for reading it with an agent is exactly the argument that was true before.

#### `guarded`: the agent with its one failure removed

So the agent generalises best, and that is what to optimise for -- the next
questionnaire will be in a shape nobody has seen either. But its characteristic
mistake is not malformed output, which is caught, but a **quiet omission**: on
the Zain workbook it read six sheets of seven, decided it was finished, and
dropped `7. 3TG + Cobalt` and its five questions without saying so.

`guarded` runs the rules as well and lets no sheet come back with fewer
questions than they found in it. Sheet by sheet, not in total, because the
failure being guarded against is losing a whole sheet and a total can hide one
sheet gained against another lost. A sheet where the agent found *more* is
kept: reading a form is not something the rules are authoritative about, and
the agent finding rows they missed is the reason to run it at all. Only "fewer"
is overruled, and the reading says which sheets had to be rescued.

The rules cost milliseconds and no tokens, so this is the agent's price plus
nothing. It is the default.

**The floor is only as good as the rules' reading of the sheet.** Where the
rules read nothing there is nothing to put under the agent, and that is how a
clean two-question questionnaire opened with 0 questions twice in three opens
(TD-043). The rules wanted three question rows, so they read nothing; and the
agent looked at the sheet, described it in prose instead of calling `record`,
and its round simply ended -- no error, no "stopped early" -- as did the second
round that asked again. Both halves are fixed:

* the rules read a short form under explicit headings (see
  [Reading it](#reading-it)), so the floor now holds on that shape whatever
  the agent does;
* `src/agents/excel_guard.py` holds the agent's loop to its job. While a sheet
  it was asked about has no reading, every model call must call a tool
  (`tool_choice="any"`, which Groq sends as `required`); once every sheet has
  one, the loop ends before the model is asked again, which also saves the
  call that would only have said "done". A sheet still never read is logged
  with the agent's steps, so the next one shows what it did instead.

Near-empty sheets -- under six cells, which no reader opens -- are no longer put
to the agent either, and a workbook holding nothing else does not run it: a
one-row workbook used to cost a full round, about 5,300 tokens, to be told it
was empty.

#### Measuring it on new files

```bash
python -m scripts.compare_detection "C:/path/to/new questionnaires" --write -v
python -m scripts.compare_detection ./new --strategies rules,hybrid --json out.json
```

It reports three separate things, because they answer different questions: how
many questions each strategy found, **where they disagreed sheet by sheet**,
and what each cost. The middle one is the one to read -- a sheet where one
strategy found 13 and another found 0 is either a rescue or a hallucination,
and only opening the file settles which. With `--write` every reading is also
answered into a temporary copy and checked for fidelity, because a reading that
cannot be written back is not a reading.

There is no ground truth in it. These files arrive from other companies and
nobody has counted them by hand, so it reports agreement and difference and
leaves the judgement to a person.

Which strategy the application uses is `DETECTION_STRATEGY`, default
`guarded`, and every batch records which one read it along with the seconds and
tokens it spent -- a bill nobody can attribute is not a decision anyone can
revisit.

One warning about running the comparison itself: with `--write` it re-reads
every answered copy **the same way it was first read**, so an agent strategy
runs twice per file. That check earns its cost -- it is what caught a file
reported as `ok, wrote 32` that could not find one of those 32 answers again --
but a four-way run over twenty files is twenty minutes, not two.

### These files come from strangers

A questionnaire arrives from another company, over a public endpoint, and is
parsed before anyone has looked at it. So the parser is treated as an attack
surface, and `tests/test_forms_hostile.py` establishes four things.

**A bad file is a sentence, not a stack trace.** Not a zip, truncated, missing
its workbook part, unparseable XML, a workbook listing no sheets -- each raises
`forms.FormatError` with a message safe to show whoever sent it. That matters
beyond tidiness: python-docx raises `PackageNotFoundError` carrying the **full
server path** of the file, which is exactly the leak the rest of this service
already guards against.

**Nothing can make it do unbounded work.** A part that would decompress past
64 MB is refused from the zip directory, before any of it is expanded -- checked
with a timer, because refusing a bomb *after* expanding it would pass a size
assertion and still be the vulnerability. A workbook past 400,000 cells is
refused outright; the largest real one has 1,288.

**Reading a large sheet is linear.** Detection reads the row list inside nested
loops, and recomputing it each time made this quadratic: 4,000 rows took a
second and 30,000 took nearly three minutes -- a denial of service with no
attacker required. Cached, 30,000 rows take one second.

**Answering a file in place does not destroy it.** `write(path, path)` is the
obvious call for "answer this", and writing straight to the destination
truncated the source while it was still being read: the questionnaire was gone
and the error was a raw `BadZipFile`. Output is now assembled in memory and
moved into place, so a crash halfway through leaves the original rather than
half a new file.

### Answering one

`src/tools.py` is every operation the interface performs and the agent will later
call, as plain functions taking a user and returning data -- no request, no
response. Building them first means they can be tested with fixed inputs before
anything non-deterministic is choosing between them.

```
open_form        a file becomes a batch of questions
inspect          what is in a batch and how far it has got
answer           write answers for a selection of its questions
revise           reword answers that exist, under an instruction
set_answer       a person overrules the system
column_roles     where the answers are going to be written
set_column_role  a person moves them somewhere else
set_questions    set a row aside, bring it back, fix its wording
fill             put the answers into the original file
search           look something up, without touching a batch
```

A **scope** is what makes a selection expressible: all of them, the ones still
blank, a named sheet, anything mentioning encryption. Turning a sentence into a
scope and an instruction is the whole of the agent's job later, so it lives here
rather than in the agent.

**Answering has one prompt, and wording is `revise`'s job.** An instruction like
"keep every answer to one sentence" used to be injected into the drafting
prompt. Measured against rewriting a finished answer, over six real questions:

|                 | injected | rewritten |
|-----------------|----------|-----------|
| one sentence    | 6/6      | 6/6       |
| mean length     | 197 ch   | 144 ch    |
| mean citations  | 4.5      | 6.3       |
| mean time       | 6.1 s    | 6.5 s     |

Both followed the instruction. The injected version cited a third fewer sources
-- a drafter told to be brief cites less -- and on one question asserted both an
annual review and a sign-off, where the rewrite kept the original's caveat that
*the sources do not require an annual sign-off*. Told to be brief, a drafter
drops hedges; a rewriter has the finished sentence in front of it and does not.
So injection was removed outright and `src/rewrite.py` does the wording: one call
over the answer and the sources it was already built from, no retrieval and no
review loop, at about a fifth of the cost. The facts, the evidence and the
citations come through untouched, because none of them changed.

The one thing a rewrite must not lose is the answer's **position**. The status
dropdown below is filled by reading the opening clause, and an early rewrite
turned "Yes. We provide training..." into "T2 provides training...", which
states nothing -- so a perfectly good answer left its compliance rating blank.
The rewrite prompt now requires the position to survive.

**A wording instruction is offered before the run, not only after it.** Being
allowed to say how the answers should read only once they existed made the
mechanism look like an afterthought, when it is how anybody actually works:
decide the house style, then answer. So the instruction is asked for beside the
answer button -- and it still runs as a rewording pass once the answers are
written, because that is the version that measured better. Nothing about the
drafting prompt changed; the field is a different moment to type into, not a
different mechanism.

It applies **only to the answers that run produced**. A questionnaire is
answered in sittings, and an earlier sitting may hold answers somebody has since
read and corrected by hand; rewording those because a later batch asked for a
house style would quietly throw that work away. The box under the cards is the
one that means *all of them*, and it says so while the reader is looking at them.

Questions typed by hand have no cells and no batch, so `POST
/api/assessments/revise` rewords a list the caller is holding and hands it
straight back, the way `/answer-questions` does. Both routes run the same
rewrite, so an instruction behaves the same whichever list it is given.

**A list can be both at once.** Somebody reads a questionnaire, notices it asks
nothing about penetration testing, and types the question in beside the file's
own rows. That question has no cell to be written into, so it goes the way any
typed question goes -- answered by the list route, reworded by the list route,
exported rather than written back -- while the rows around it go through the
batch. Sending it to the batch instead produced an answer for a question the
batch had never heard of, and the page fell over rendering it. Rebuilding the
list from the batch used to delete such a row while leaving its answer card on
the page; the rows and their answers now survive every rebuild of the file they
sit beside.

Status columns are answered from the file's own dropdown. The written answer
states a position in its first clause -- yes, no, partly, not applicable -- and
each option in the vocabulary is classified the same way, so `Fully Compliant`,
`Fully Implemented`, `Yes` and `FC` all mean the same thing to it. Where the
answer takes no clear position, or the file has no word for the one it takes,
nothing is written and the reason is reported: a blank dropdown is a question
somebody looks at, a confidently wrong one is a question nobody looks at.

**The word an answer opens with decides.** "Yes.", "No;", "**Yes.**",
"Partially.", "N/A", "نعم", "لا ينطبق" -- when an answer starts with a verdict,
that is its position, and a "Yes" qualified in its own clause ("Yes, partially:
…") is a partial. Phrases are read only when there is no opening word. They used
to be read first, and prose about controls is full of "no longer required", "are
not left in use" and "will be reviewed": over the 1,088 drafted answers in the
deployment's own history that open with a verdict, 19 that said Yes were read as
No -- the dropdown beside them would have said Non Compliant -- and 16 that said
No were read as nothing. Both counts are now zero, and so is the same check over
the team's 698 remembered answers.

A **batch** outlives the request that made it. Answering 183 questions takes
minutes, corrections come afterwards, and the file is filled in later still --
so answers are keyed by question rather than by position, and answering twice
merges rather than replaces. An upload of last year's submission does not
silently overwrite reviewed work. It outlives the *page*, too: a questionnaire
loaded earlier is offered back on the upload panel, because re-uploading the
same file would start a second batch and orphan the answers in the first.

**A person's edit has to reach the file.** An edit made on an answer card used
to live only in the page: it went into every download and *not* into the filled
spreadsheet -- the one place a reviewer would swear they had corrected it. A
finished edit is now written to the batch, against the cell the answer belongs
in, with their name on it, and the status dropdown is re-read from *their*
words: correcting an answer to "No, this is not in place" moves the rating to
`Non Compliant` rather than leaving the model's `Fully Compliant` beside it.
Deleting an answer card sets its row aside for the same reason -- the row is
still in the spreadsheet whatever the page does, so the only thing "remove" can
mean is *write nothing here*, and that has to be said to the server. Both work
the same in Word.

**Detection proposes, a person disposes.** The report under the drop zone names
every sheet, says what each column was taken for and why, and flags any reading
that came from the shape of the sheet rather than from a heading. Each writable
column carries a picker, so a column read wrongly is moved before anything is
answered rather than discovered after 183 answers land in the wrong place; the
correction moves every row on that sheet at once, is recorded against the person
who made it, and replaces the detector's line in the report so the two cannot
disagree. Individual rows can be **set aside** instead of deleted -- detection
over-reports on purpose, the row still exists in the spreadsheet, and somebody
who unticks a row often wants it back once they see the sheet filled in.

Beside the assistant, a set-aside question is listed after the others under
**Set aside -- not written to the file**, its card dashed and dimmed, with
**Include it again** on it; every other card has **Set aside** beside its
question. It used to look exactly like the rest, so "leave that one out" seemed
to be ignored. `inspect` no longer says a set-aside answer `will_be_written`,
does not count it as held back, and the fill report counts it out.

### Checking a new format

```bash
python -m scripts.check_forms "path/to/questionnaires" --write
```

Reports what was found in each file and, with `--write`, answers every question
into a temporary copy and checks the file came through intact. Worth running
whenever a questionnaire arrives in a shape we have not seen.

## Nothing unconfirmed reaches the customer's file

Measured against the security team's own answers on five real questionnaires:
of ten answers that *contradicted* them, ten came back flagged for review with
confidence at or below 0.50. Not one wrong answer was confidently wrong. So the
confidence score is worth acting on rather than displaying, and `fill` acts on
it: an answer nobody has confirmed is held back rather than written.

"Confirmed" means a person was involved -- they edited it, or they approved it
as it stands. Approving exists because the other half of that sentence was a
trap: an answer that is right as written should not have to be retyped to be
released, and requiring an edit to release it teaches people to make a
meaningless one.

The card says which answers are held and why -- "flagged for review: the sources
do not cover this directly" -- because "held back" on its own is a wall, and the
whole point of holding an answer is that somebody should look at it. The fill
report says how many stayed behind and offers to write them anyway, which is a
button somebody has to mean.

**Silence is not a No.** Five of the eight contradictions that survived the
identity fix were the same move: the corpus does not say whether we hold ISO
27001, whether a DPA was signed with this customer, or whether a regulator
audited us this year -- and the drafter answered "No." None of those are policy
questions. A policy says what we do; it does not record that an agreement was
signed or that an audit happened in a period, and those facts sit with the
security team. So the drafting prompt now separates the absence of *evidence*
from the absence of the *thing*: where the sources are silent the answer says
so, scores at or below 0.3, and is held back for a person -- because a wrong No
understates the organisation to a customer, gets quoted back in the next
assessment, and is far harder to withdraw than a blank.

**An answer with nothing of ours behind it is held too.** A previous answer is
the best evidence of *how we answer* and no evidence at all of what is true --
it is our own earlier claim -- so an answer whose every source is a remembered
one is flagged: "nothing in our documents backs this". Measured over nineteen
real questions it catches one, and the one it caught was *"In which
jurisdiction(s) will you store the Personal Data?"*, answered at 0.90 confidence
from two remembered answers and no document, on its way into a customer's file.
The score is left alone -- the answer is well supported by what it was given,
and which *kind* of source that was is a question about provenance rather than
about the writing.

Retrieval is not what causes this, and a floor on policy chunks would not fix
it: that question reached the drafter with thirty-four policy chunks in the
prompt. It cited none of them, because none of them say where we store data.

The same rule governs the organisation profile. An empty certifications list
means *unknown*, never *none* -- a distinction learned expensively, since the
first version read it as "none", instructed the drafter to say so plainly, and
produced "No. T2 does not hold any information-security certifications" at 0.85
confidence while the team's own answers in fourteen real questionnaires said ISO
27001 and SOC 2.
