# The answer memory

Approved answers, kept and reused, and what happens when two of them disagree.

Moved from the README (plan 009); the text is as it was written there, with links re-pointed.

What this organisation has already told an assessor is the single most valuable
thing in the system. Measured on the held-out half of the team's own
questionnaires, having it at all is worth about **seventeen points of agreement**
with the security team — more than any prompt, any retrieval setting and any
model choice in this repository. It earns that by being what the team really
wrote, so everything here exists to keep it true.

**A previous answer is worked from, not copied, and the policies still decide.**
The team wrote those answers *from* these policies in the first place, so the
two agreeing is the ordinary case and the policies remain the authority when
they do not. The drafter is told to read what we said before, check it against
our policy, answer as we answered where they agree — and where they conflict, to
follow the policy and report the disagreement.

That report is a **flag, never prose**. `DraftedAnswer.contradicts_memory` is a
field of its own, and `finalize` hands it to `verification.assess`, which turns
it into a review reason: that holds the answer back, caps the score it shows at
the review threshold (plan 030), and shows on the card as "Sources disagree"
beside the answer. It cannot reach the
spreadsheet, because the only string this system writes into a cell is `answer`
— and a note about our own inconsistency is not something to send a customer.

## Only what a person wrote goes in

Approving an answer does two things, and they are separate: it releases the
answer into the file, and — **only if somebody wrote it** — it teaches the
memory. A draft the model produced and a reviewer waved through carries no
information the system did not already have. Remembering it feeds the drafter
its own output: the next questionnaire is answered from a "previous answer" that
was itself a draft, cited as the organisation's own words, at a confidence the
loop manufactured rather than earned. Do that a few times and the memory stops
being a record of what the team says and becomes a record of what the model
said, which is the one thing retrieval cannot correct for.

So the mark that matters is `AnsweredQuestion.by_hand`, set when a person types
an answer and untouched by approval. `remembered` comes back empty when nothing
was learned; the approve button says which of the two effects apply before it is
pressed, and the card carries an **in the answer memory** tag afterwards, which
survives a reload because the batch reports it. Editing one word is enough — the
point is that a person put their own words there, not how many.

**What is remembered is what went into the cell** — `written_text`, not `answer`.
A questionnaire set to brief is filled in with the brief text, and somebody who
shortens an answer by hand has written *that*: storing `answer` regardless put
the untouched full draft into the memory under a reviewer's name, which is the
model's own words laundered through an approval and exactly what this gate
exists to prevent.

## Supersession and contradiction are different things

A later answer that says something different, or something more — an audit that
has since happened, a certificate since issued — **supersedes** the earlier one.
That is not a decision anybody needs to be asked about, so it is applied: the
earlier entry stops being retrieved and is kept, marked, and still visible. It
was true when it was written, an assessor may well ask what we said last year,
and a memory that quietly rewrites its own history cannot be audited.

Two answers that disagree with **nothing to say which is current** are a
different matter. That is not a versioning problem; it is two people believing
different things, and no rule here can pick a winner. It is raised for a person
on the memory page, with both answers side by side and the questionnaire each
was given in.

The ordering key is *approval* time, not upload time: an answer becomes ours
when somebody accepts it, not when a file lands on a disk. The imported
questionnaires record no date at all, so they carry none — they sort equal, and
the first properly dated answer supersedes any of them it matches. That is the
right outcome and worth saying out loud.

## Similarity proposes, a model confirms

Nothing is marked on a distance. Two questions about annual drills embed at
0.793 and are different controls; two about sub-processor DPAs embed at 0.808
and are one question, and no threshold separates those. So the sweep filters
three times, cheapest first: the index proposes the neighbourhood, the questions
alone are re-embedded and compared at `PROPOSE = 0.80`, and a model is asked
which of the survivors actually ask the same thing.

The re-scoring matters more than it sounds. The index embeds `Q: … A: …` as one
document, so a hit's score is a question-*and-answer* similarity: two identical
questions with different answers come back at 0.76. The threshold was calibrated
question against question — 91% of pairs above 0.90 were reusable, 54% between
0.80 and 0.85, 21% below 0.75 — and that is the comparison the sweep makes.
About 3% of the corpus has a cross-questionnaire neighbour that close, so the
model is asked about roughly one entry in thirty rather than all of them.

## When it runs, and where the entries come from

At ingest, never at answer time. By the time a questionnaire is being answered
it is too late to be useful — whichever entry retrieval ranked first has already
gone into a customer's file — and the person filling in the form is not the
person who can say which of two answers is the organisation's position. The
sweep runs as a background task after an upload, an approval or a correction,
inline at the end of a `cli answers` import, and on demand from the page — where
a press compares fifty and says how many are left, because a button that returns
in twenty seconds gets pressed again and one that hangs for four minutes gets
reloaded. Background sweeps run one at a time: approvals clicked through in a row
used to start a sweep each, over the same pending entries, and a request that
arrives while one is running now makes it go round once more instead.

Three things feed it:

* **Import.** The questionnaires the team filled in before this system, read in
  when the corpus was set up. Undated and unattributed, because the files record
  neither.
* **Approval.** A reviewer read an answer this system drafted, put their name to
  it, and it went into a customer's file. Approving therefore *teaches*: it is
  where the memory grows once the imported questionnaires run out, and
  withdrawing an approval takes the entry back out, because an answer somebody
  withdrew should not be quoted back at them next month.
* **By hand,** on the memory page, for something we say that no questionnaire in
  the corpus happens to ask.

## Answers come in one at a time

Nothing in the app takes a whole questionnaire into the answer memory. An answer
arrives because a person wrote it: **Add an answer** on the memory page, or an
edited answer approved on its card. A file read in wholesale is hundreds of
answers nobody read one by one, and each is retrieved afterwards as something we
said -- so adding is deliberate. **Add an answer** sits above the list, which is
newest first, and the answer just added is the first card, outlined. The import
routes (`/api/memory/import`, `/api/knowledge/prior-assessments`) are gone; the
command line keeps `python -m src.cli answers` for whoever sets up a corpus.

That command reads a spreadsheet or Word form with the reader that opens
questionnaires for answering. The configured detection strategy (`guarded`)
reads it, and the rules alone read it again, kept only when they find more:
harvesting what somebody wrote is a different job from opening a form to answer
it, and on the team's seventeen filled questionnaires `guarded` finds none of
Litware's 183 answers while the rules find all of them.

A cell holding only an unticked box (☐), a dash or punctuation is empty. The
team's BCM form asks for Yes or No by ticking a box and ships with "☐" in every
answer cell: read as answers, the guard against overwriting existing answers
would have kept that form from ever being answered. A ticked mark (☒, ☑, ✓) is
still an answer.

## The knowledge base holds documents

The answer memory is indexed beside the policies, but it is not a document and
is not managed as one. The knowledge base panels list policy documents only; a
previous answer cannot be removed from there (`DELETE /api/knowledge/sources/…`
refuses it), and **Remove every policy document** removes exactly that. Both
used to reach the memory's vectors -- one as a row reading "Answer memory (698)"
beside a remove button, one as "Clear everything" -- and either would have left
hundreds of rows on the memory page pointing at nothing.

In the assistant's knowledge base drawer a long file name is cut short, but its
**law / external** label and chunk count sit on their own line under it, and are
never cut. The label used to end the name, so exactly the long regulator file
names lost it.

## The page

`/memory` is the third page, beside the assistant and the workbench, because it
is a different job done on a different day — usually the day somebody disagrees
with an answer. It lists everything the organisation has said, newest first,
searchable and filterable by whether an entry is still in use and where it came
from; each entry can be corrected, retired, restored or forgotten, and the
disagreements sit at the top where they are the only thing on the page that is
somebody's decision rather than a list to read.

It is the team's, not one person's — like the knowledge base, and for the same
reason: what we have said before is a fact about the organisation, not a private
note. Who imported, approved or corrected each entry is recorded on it, so a
shared record is still an attributable one.

```bash
python -m scripts.build_answer_memory --sync-only   # what is there
python -m scripts.build_answer_memory --rescan      # compare all of it again
```

The historical import is adopted already-compared. Seven hundred model calls is
not something a page should start because somebody opened it; running that sweep
is a decision, and the script is how it is taken.
