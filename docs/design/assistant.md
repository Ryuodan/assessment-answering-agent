# The assistant

The chat assistant: what it is, what it may do, and how it was measured.

Moved from the README (plan 009); the text is as it was written there, with links re-pointed.

## Talking to it

There are two interfaces and they are separate pages, not two modes of one.
`/` is the assistant: a conversation, and the answer cards it produces beside
it. `/workbench` is the workbench: every control on screen, nothing hidden, a
person doing the work themselves. Each links to the other in its header, and
`/chat` -- where the assistant used to live -- redirects to `/`, because
somebody has it bookmarked.

The conversation is the front door because it is the one that needs nothing
explained. Everything the workbench does can be asked for in a sentence, and a
person who wants the controls will go and find them; a person meeting a wall of
controls has to be taught before they can start.

Separate because they are different shapes. Interleaving them would mean every
control needing to know which mode it was in, which is a control with a bug
waiting in it. What they *do* share is the thing worth sharing: `cards.js` and
`cards.css` hold the answer card and everything it draws with -- the citation
panels, the clause text, the reviewer's reasoning, the Formatted/Raw switch --
plus the design tokens both pages are built from, so dark mode is one
definition rather than two. Both were lifted out of the workbench rather than
rewritten, so a card looks the same in both, and the four things a card does
that differ by page (discard a question, retry a failed one, open a source
document, edit an answer) are hooks the page assigns.

Sharing the stylesheet is worth doing and worth doing carefully. The first cut
of it swept up the workbench's question list and its composer, which collided
on class name: the chat page's composer inherited a dashed border and a 58px
minimum height from a control it has nothing to do with. A shared stylesheet
should hold what is actually shared and not a line more.

The chat page is three panes -- conversations on the left, the exchange in the
middle, the answers on the right -- and the outer two open and close, because
somebody reading 183 answer cards wants the width and somebody typing does not.
A long turn shows the pipeline's own progress, watched under the batch id, the
same figure the workbench watches; a spinner and a guess would be worse on work
that takes minutes. Policy clauses the assistant looked up are drawn under the
reply as the same citation bubbles an answer card uses, so a claim about what
the policies say can be opened and checked rather than taken on trust -- and
they are stored on the reply message itself, so reopening a conversation
redraws the evidence and not only the words.

### What the assistant is

`src/agents/assistant.py`, and it is mostly a system prompt and eleven tool
wrappers. That is the point: every operation it performs already existed and
was already tested. `src.tools` was written for this from the beginning --
plain functions taking a user and returning data, no request and no response --
so that when an agent arrived it would be *choosing* between operations rather
than being the only thing that knows how to perform them.

```
open_questionnaire   read a file attached to a message
describe_form        what is in it, and how far it has got
list_questions       the questions a scope selects, with their ids. Free
read_existing        what a question already said when the file arrived
answer_questions     answer some or all of them, from the policy corpus
reword_answers       change how existing answers are worded, not what they say
write_one_answer     replace one answer with words a person dictated
set_aside            leave questions out, or bring them back in
propose_fill         report what filling the file would write. It does NOT write
search_policies      look something up in the organisation's own documents
answer_directly      answer a question asked in the conversation, with no file
```

**A question can be asked without a file.** "Do we encrypt customer data at
rest?" is a fair thing to ask, and making somebody build a spreadsheet to find
out would be absurd. `answer_directly` runs the same pipeline a questionnaire
row goes through -- retrieval, drafting, review, citations -- over a question
somebody typed. Each draft is drawn under the reply as the Workbench's answer
card, word for word, with its status, its confidence and the clauses it cites
(plan 030, `src/agents/assistant_cards.py`), and the clauses it cited are
folded under the reply. The model is told the card shows the answer, so its own
reply is one sentence leading into it: when it relayed the draft itself, six of
twelve came back paraphrased, and one, in Arabic, contradicted the draft. The
card is read-only and is kept with the reply, so a reopened conversation draws
it again. Nothing else is stored: no cells, nothing to approve or fill, which
is why it takes five questions at most. A longer list is a questionnaire and
belongs in a file, and it says so.

**The two interfaces do not share a working session, on purpose.** A batch is
visible to the whole team either way -- it is one `batches` table -- but the
conversation does not reach across and pick up what the workbench has open. It
was built and then taken out: continuing on one page work that was started on
the other reads as one session and is not one, and every difference between
them (which questions are selected, what the last run answered, what is still
being edited) becomes a surprise. A file is opened where it is worked on.

### Asking about the answers

"What is the second question's answer?" is a question about an answer, not a
request to change one, and the assistant used to have no way to answer it: it
could list questions, answer, reword and propose a fill, but not read back what
had been written -- so it described the fill button instead. `read_answers` reads
them, word for word, with whether each is flagged and why, its confidence, and
whether it will go into the file. "The second question" is a *place in the file*
(`position="2"`, or `"last"`, or `"2-4"`), which `list_questions` now shows beside
every id.

**"What sources did you use for question 3?"** is a question about the same
answer, and it got a different answer from the card. The assistant searched the
policies again and listed what that search found: a similar list, not the one
the answer was written from, and the person was holding it up against the
card. `read_answers` now names the sources each answer cites, and with
`with_sources=true` it reads out what each cited clause says, whether it is our
own policy, a regulation or a previous answer, and the reasoning the answer was
drafted with -- all from what was stored with the answer, so nothing is looked
up again. An answer drafted in the conversation with `answer_directly` carries
its cited clauses in what that tool returns, so a question about them later is
answered from those too. Two eval cases, one in Arabic, check that the reply
names the documents the stored answer cites; both pass every run.

That guidance lives in the tool's description, not the system prompt, and a
plain read-back does not list sources. Both were tried the other way. A
paragraph in the prompt, and a sources line after every answer read back, each
made "what is the answer to question 3?" asked in Arabic come back *translated*
rather than quoted: with the paragraph, three runs in five quoted it; without,
five in five. The source questions were answered correctly either way.

Every tool that acts on questions takes `position` too, and the prompt says why:
"make the answer to question 3 more formal" once reworded the *training*
question, whose id is `Human Resources!3` -- a spreadsheet row -- and which is
question 2. A place that is not in the file selects nothing rather than
everything.

The rest of what people ask without thinking about it has a tool or a plain
answer: "undo that" after a rewording is `put_back_drafts`; "translate them to
Arabic" passes a language to the rewording; "approve all of them" is refused,
because approving is a person putting their name to an answer, on its card. An
empty result says what *is* true -- "none of the 4 answers is flagged; 0 have
been approved by a person" -- because told only that nothing matched, the
assistant announced that every answer had been approved.

Three things are handled where the reply is taken rather than in the prompt,
because each was the model's own output and a prompt did not stop it: a copy of
the previous reply appended to this one, the same reply written twice in two
phrasings, and the model's own citation markers ("【search_policies result
#2】"). And the reply language is restated for every model call from the
person's latest message: the rule was already the last paragraph of the prompt,
and with English tool results in front of it an Arabic question got an English
reply.

Now and then the model calls a tool that was never offered to it --
`repo_browser.open_file`, from its own training -- and Groq refuses the whole
request (`tool_use_failed`). That used to end the turn, sometimes after it had
already answered questions, and the next turn reported the broken one instead of
doing what was asked. The turn now carries on from what it had finished, so
nothing already done is done twice, with a one-line note in front of the model
that the tool it called is not there -- sending the same messages again got the
same refused call every time, because the assistant runs at temperature 0. The
note is never stored or shown, and does not count as the person's language. After
two tries, or on any other failure, the turn stops and says so.

`scripts/eval_assistant.py` holds all of this against the real model -- forty
cases, fifteen of them requests nobody would think to test: ordinal questions,
read-backs by topic and in Arabic, "why is it flagged", "undo that", "fix it",
"approve all of them", "thanks", "write me a poem".

Its exit code is its verdict, and on Windows it used to be 139 whatever the score:
the model's and the embeddings' connections were garbage-collected after the
event loop had closed, and Python 3.11's Windows transport crashes doing that.
Every script and the CLI now run through `llm.run`, which closes them while the
loop is still running; the server does the same when it shuts down.

### A conversation kept open all day

Nothing is dropped from a conversation, however long it gets. The model is
shown a window of it: the last `TURNS_REMEMBERED` (20) turns, the most recent
three with their tool calls and results and the rest as what was asked and what
was said. The window always starts at a person's message, and any tool call a
failed turn left without a result is left out of it.

It used to be the last sixty messages -- eight or ten turns -- and that window
was saved back as though it were the conversation, so past about ten turns the
beginning of every long conversation was deleted from the history a person
scrolls back through. And a count of messages can cut a turn in half: a tool
result without the call that produced it is a request the model API refuses, and
from then on every turn failed.

Every message now records when it was said and which file it came with, and a
reply that changed the answers carries a **Show the answers** button.

The list of conversations beside them says, under each title, **when it was
last used** -- a time today, "Yesterday", a weekday within the week, then a date
-- and, for a conversation with a questionnaire in it, **the file's name** on a
marked line. The title is written from the first sentence somebody typed, and
for half of them that is "answer these"; the file is what a person recognises
the work by. That
button and the floating **Answers →** are the one filled, coloured control in
the conversation: they were outlined in grey like everything in the header, and
the answers are what the page is for.

What a turn did is folded to one line under the reply -- *11 steps · Read the
file · Answered questions ×8 · Listed questions* -- which opens onto a numbered
list, each step in words with the scope it used beneath. Each tool call used to
be a monospace pill, and in the column beside the answers a long scope wrapped
inside its pill: eleven calls stacked into a ragged tower taller than the reply
they explained.

### Answers that already exist are not ours to overwrite

**A questionnaire usually arrives already answered** -- last year's submission,
or the security team's own draft. Those answers are worth *more* than a fresh
one, not less: they were written by the people who own the subject and know
what was actually agreed with this assessor. The absence of a citation beside
one says nothing about it, and treating them as unverified placeholders is
exactly the mistake to avoid.

Two things were wrong, in the same way, and neither was in the model.

The **count** looked only at answers *we* had written, so a completed
submission was reported as having none. The file's own answers live on the
targets, as the text already in the cell: `describe_form` reports them
separately, `list_questions` marks them "in file", `read_existing` quotes them,
and the workbench shows the sentence itself under the question it answers.

The **guard** did not exist. `unanswered_only` was a narrowing option a caller
had to remember, and "answer this questionnaire" is the most natural
instruction there is -- so a broad scope over 183 reviewed answers replaced
every one of them. It is no longer a matter of remembering: `tools.answer`
refuses to overwrite an answer that already exists -- ours or the file's --
unless the caller passes `replace_existing`, and it reports how many it left
alone rather than saying "nothing matched". Naming the questions by id does not
lift it, because listing a sheet and passing every id back is not the same as
being asked to redo them. Saying so is: "this answer is out of date, write a
new one" gets the flag, and on the workbench the row itself offers
*Answer it again*, one question at a time, with what it would replace shown
above the button.

**Three things are absent rather than discouraged**, and all three were decided
long before there was an agent to decide them for. A prompt that says "do not
fill the file" is a request; a missing tool is a guarantee.

* **It cannot write to a file.** `fill` always stopped for confirmation and
  showed what would change. `propose_fill` reports what would be written; the
  button beside the answers does the writing. An agent that could quietly
  overwrite a customer's spreadsheet would be a worse tool than the one it
  replaced.
* **It cannot manage the knowledge base.** Indexing and removing policy
  documents is the corpus every answer is grounded in, not a task to do by
  conversation. It lives behind a side panel with a list and a delete button.
  Searching it is a different thing, and it can do that.
* **It cannot record feedback on an answer.** Feedback belongs on the answer
  card, where the thing being judged is visible.

Compound instructions are the point. "Read this, answer only the governance
questions, and keep every answer to one sentence" is three calls and a scope,
and turning that sentence into `answer_questions(part="governance")` followed
by `reword_answers("one sentence", part="governance")` is the whole job. The
same is true in Arabic, and the reply comes back in the language it was asked
in while the questions in the file keep their own.

A conversation outlives the request that made it, for the same reason a batch
does: somebody says "read this file", waits four minutes for 183 answers, comes
back after lunch and says "now make the governance ones shorter". The stored
history is LangChain's own, tool calls included, because the agent resumes from
it -- a tidy display transcript would lose which tool returned what, which is
exactly what the follow-up depends on.

### Measuring it

```bash
python -m scripts.eval_assistant --repeat 3 -v
```

`tests/test_assistant.py` tests the machinery a model's choices land on, with
the model stubbed: that a sentence turns into the right scope, that a forbidden
operation is absent, that a turn which fails part way through still records
what it did. Deterministic, free, and it runs in the suite.

Whether the model picks the right tool is a different question and cannot be
tested that way -- an agent asked the same thing twice may do it two ways and
both may be right. So the eval asserts the things that would be wrong whichever
route was taken: tools that must have been called, tools that must **not** have
been, how many questions end up answered, the language of the reply, and for
the cases where the answer is a fact rather than a tool call, what the reply
has to say. Fourteen cases, English and Arabic, run as many times as asked so
that variance is visible.

It earns its cost. The first run scored 98% and the failure was the worst kind
available: asked to answer everything and keep each answer to one sentence, the
assistant answered, never called `reword_answers`, and **reported that it had**
-- "Answered all 4 questions with a single short sentence each". Three runs at
92% then found two more, both consistent rather than flaky, and both the same
root cause: it had no way to see the questions. It passed
`matching="training OR awareness"` as one literal string, matched nothing, and
concluded the file had no training questions; and it could not get a question
id, so `set_aside` was unusable and it guessed `'1'`.

The fixes were a tool and two prompt rules -- `list_questions`, a statement
that `matching` is a substring and not a query language, and a rule that
`answer_questions` ignores wording completely so an instruction about length is
still outstanding when it returns. Also a rule against claiming work that no
tool did. **14 cases x 3 runs: 100%, no variance.**

One more came from driving it by hand rather than from the eval, which is worth
recording as an argument for doing both: asked in Arabic how many questions
were left, it read "1 answered" off a four-question file and replied "one
remaining". `describe_form` now says "1 answered, 3 still blank" rather than
leaving the subtraction to be done, and there are cases for it in both
languages.

The set has grown to nineteen as the interface has, and it keeps earning its
cost. Adding cases for the answers a file arrives with, for what the file
already said, and a ceiling on how often one tool may be called turned up three
more faults in a single run: it announced *"let me
run propose_fill"* and ended the turn having called nothing; it answered an
Arabic instruction in English; and one of the new checks was itself wrong,
rejecting "**Two** of the questions already have answers" because it compared
case-sensitively. Two prompt rules and one test fix later: **19 cases x 3 runs,
99%**, with one case that reworded on two runs of three.

**Twenty-two cases, and the clearest argument yet for running all of them.**
Two of the new ones are the overwrite guard from both sides -- told "answer
this questionnaire" on a file the security team had half-filled, it must answer
the blanks and leave theirs; told one answer is out of date, it must actually
redo that one. Both passed first time. Everything that broke that round broke
somewhere else, and each break was caused by fixing the one before it.

*Adding `answer_directly` cost two search cases twenty-five points each.*
"What does our policy say about password length?" started drawing a full
drafted answer -- twelve seconds, ten thousand tokens -- where the person had
asked to be shown the clause. The boundary is now drawn by the shape of the
question rather than its topic: *what the documents say* is a search, *what our
answer is* is a draft, and when it is genuinely both, search first because it
is cheap.

*Fixing that cost `will-not-fill-a-file` half its score, on both runs.* Asked to
write the answers into the file, the assistant replied in prose and called
nothing. The bullet had always said "You cannot fill a file" first and named
`propose_fill` second, and twenty lines of new text between it and the rule
against announcing a call instead of making it was enough to tip the reading
from *here is what to do* into *here is what to decline*. It now leads with the
action -- "fill it in", "save it" -> **call `propose_fill`** -- and says what
not calling it costs: no report, no button, and no idea what would have gone
into which cell.

*And fixing that broke the rewording case, in a new way.* Told "make them all
more formal", it proposed filling the file. Strengthening the fill rule had
made `propose_fill` more salient without bounding it, so it began reaching for
it to round a run off. The bullet now carries its own limit -- those
instructions and nothing else -- and the case, which had been failing
intermittently for two rounds before any of this, has been clean since.
**22 cases x 2 runs: 100%, no variance.**

The lesson arrived three times in one afternoon: a system prompt is not a set
of true statements, it is a document with an order, and adding a true statement
in the middle of it changes what the statements around it mean. None of the
three faults was anywhere near the feature being built, and none would have
been found by testing that feature.

**Twenty-four cases now.** The last two are the plain-language overrides --
"just show me the clause" on a question shaped for drafting, "answer it
properly, the way we would put it to an assessor" on one shaped for a lookup.
They are the escape hatch out of the search/draft boundary, and putting them in
the suite is the argument against making people learn a command for it: the
words they would use anyway are guaranteed to work, rather than happening to.

**Forty-two cases, after the answer cards (plan 031).** Plan 030 told the model
that a question answered in the chat is shown as its card, and to "never
restate, translate, summarise or reword the answer". The first run since scored
98%. One miss was a one-off: an empty reply, which passed three times in three
on a re-run. The other was not. Asked in Arabic to answer a file and "make each
answer one short sentence", the assistant answered and skipped `reword_answers`
in three runs of four, saying the answers were short when nothing had made them
so. It passed three in three on the code before plan 030. "Reword" in a rule
about its own reply had been read as a rule about the answers. The rule now
says "do not repeat the drafted text in your reply", and that `reword_answers`
still rewords a questionnaire's answers on request. Three in three again, and
the six cases that draft in the chat still pass. The runs read a copy of the
index, so nothing they wrote reached the real one (TD-072).

A failing case prints the tools it called *and what it said*, neither needing
`--verbose`. "It did not call X" is not a finding -- what it called instead is
-- and "replied in ar, got en" does not say whether the assistant was wrong or
the counting was, which is a question that came up and could not be answered
because the reply was gone. On the same theme, `--verbose` itself used to die
with a UnicodeEncodeError on a Windows console: the one flag for diagnosing an
Arabic failure could not print Arabic.

And the suite clears up after itself now. It left a batch and a conversation
behind per case, sixty a run, and they surfaced in the interface -- "Or pick
up" and the conversation list filling with fixture questionnaires nobody had
uploaded, until 177 rows had to be deleted by hand. A test that dirties the
thing it is testing is not finished.

**A fill that writes nothing is not a quiet success.** "Wrote 0 value(s) into
the file -- every other part of it is untouched" is a true sentence that reads
like it worked, which is the worst possible way for somebody who has just
watched a run finish to learn that nothing reached their file. Zero has causes
and they are different problems, so `fill` reports which: nothing has been
answered yet, every answered row is set aside, or -- the one that is not a
problem at all -- the answers were already in the file when it arrived and
there was genuinely nothing to add. Neither interface offers a download for a
file it did not write.

**A turn you can watch.** The assistant's progress bar only ever appeared on
later turns: it was watched under the batch id, and the turn that uploads a
file has no batch yet -- so the one turn long enough to need a bar was the one
turn that never had one. The page now names the turn itself and passes that
name with the request, and the assistant reports each step under it as it
starts: *Reading the file*, *Working out which questions that means*, then a
counted bar while answering. Three dots keep moving throughout, because the
label can only ever be as fresh as the last poll and "Working" for ninety
seconds is indistinguishable from a page that has frozen.

A deliberately blank answer is its own state, distinct from a question nobody
has answered yet -- the two look identical from outside and are opposites, one
a decision and the other work outstanding. `fill` writes an empty cell for it
rather than skipping the question, because the file may already hold last
year's answer and "leave this blank" has to be able to clear it; and
`unanswered_only` treats it as settled, so "finish the rest" does not offer it
back. Taking it back is an undo rather than a reversal: the stored answer is
forgotten and the question is unanswered again, because storing something in
its place would only be a second decision made on the person's behalf.

**Clearing an answer is not leaving it blank.** The ✕ on a card, and emptying an
answer in its editor, take *our* answer away and nothing more: the cell is left
exactly as the file had it -- empty if it arrived empty, last year's answer if
it arrived with one. *Leave blank* is the one action that writes an empty cell
over what was there, and the card says so before anything is written. Emptying
the editor used to store an empty answer "written by hand", which was neither
state: nothing was written, the card said no answer had been produced, and the
workbench counted it as an edit on its way into the file.

**A question typed beside a spreadsheet's rows has no cell to go into.** It is
answered like any other and leaves through the exports, which is useful --
somebody notices the form is missing something and asks anyway -- but the one
moment to find that out is not after opening the filled file. The row says so
while it is being typed, and the fill report says so again. Reading a **PDF**
while a spreadsheet is open is the sharper version of the same thing: a PDF has
no cells at all, so it used to drop the batch on the floor and leave every row
from the spreadsheet pointing at a questionnaire the page no longer held. It
now asks first, and says where the work went.
