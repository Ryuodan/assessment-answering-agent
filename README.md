# Assessment Answering Agent

Answers assessment questionnaires — vendor security reviews, compliance
attestations, RFP forms — from your own guidelines and the assessments you have
already filled in. Handles English and Arabic, including a single form that
mixes both.

Upload your policies and a few completed assessments, submit a new one, and the
agent extracts every question, retrieves what supports it, drafts an answer,
reviews that answer for grounding, and flags whatever a human should read.

Built on **LangChain 1.x**, **LangGraph 1.x**, **Groq** for generation and a
self-hosted **BGE-M3** endpoint for multilingual embeddings.

---

## How it works

```
                          ┌──────────────────────────────┐
  guidelines (PDF/DOCX) ──▶ chunk ────────────────┐      │
                          │                       ▼      │
  previous assessments ──▶ extract Q/A pairs ──▶ Chroma  │  knowledge base
                          └──────────────────────────────┘
                                                  │
  new assessment ──▶ extract questions ──▶ fan out (one run per question)
                                                  │
                       ┌──────────────────────────┴───────────────────┐
                       │  retrieve ─▶ draft ─▶ review ─┬─▶ finalize   │
                       │      ▲                        │              │
                       │      └──── refined query ─────┘              │
                       └──────────────────────────────────────────────┘
                                                  │
                                     answers + confidence + citations
```

The parts worth calling out:

**Documents are converted by Docling, except when they should not be.** Every
upload is submitted to the hosted Docling service and comes back as Markdown
with tables intact, which is what keeps a question next to the answer cell that
belongs to it. Conversion goes through the *asynchronous* endpoint and is
polled: docling-serve caps synchronous requests at `DOCLING_SERVE_MAX_SYNC_WAIT`
seconds and answers 504 past it, so on a corpus holding real reference material
— a 161-page controls guide, a 173-page standard — the synchronous path fails
on exactly the documents worth having. If Docling is unreachable the loader
falls back to local pdfplumber / python-docx extraction, so an upload never
fails purely because a container is down — set `DOCLING_FALLBACK_LOCAL=false`
if you would rather it failed loudly.

**OCR is decided per document, not per deployment.** Forcing it on costs about
2.3x and, on a born-digital policy, changes nothing that matters: Docling
recognises table structure with a separate model that runs either way, so the
only text OCR adds is what it reads off the logos — page-footer email addresses
scattered through the chunks. Forcing it off would silently index a scanned
document as empty. So each PDF's text layer is sampled at upload and OCR is
switched on for that file alone when there is not enough text to work with.

**Arabic PDFs with a visual-order text layer are read locally instead.** Some
Arabic PDFs store the shapes the renderer draws, right-to-left, rather than the
letters an author typed. Docling reads those as disconnected fragments: it drops
most of each sentence and reverses embedded numbers, which is how a 12-character
minimum password length was once indexed as 21. Such files are detected at
upload (by their share of Arabic presentation forms) and read with pdfplumber
instead, then put back into logical order with the Unicode bidirectional
algorithm and NFKC. Latin and numeric runs survive the round trip intact —
`AES-256` and `NIST SP 800-63B` come back unchanged. The routing decision is
logged for every file.

**Previous answers are indexed as question/answer pairs, not as prose.** An LLM
pass pulls each answered row out of a completed assessment and stores the
question and answer together. A new question then matches on question wording,
and the answer your organisation actually gave travels with it. This is what
makes the output sound like you rather than like a policy document.

**They lead the prompt, but they do not get all of it.** Previous answers sort
ahead of guidelines because the drafter should read them first. For a while
that ordering also decided what fitted: the prompt was filled from the top of
the same list, so once a previous-answers bank was indexed, a dozen entries
scoring 0.20–0.48 pushed out policy clauses scoring 0.60, and a retrieval retry
that added three more pushed the guideline count to zero. The clause with the
answer had been retrieved and ranked thirteenth of thirty; the drafter never
saw it and wrote "the documentation does not state a period". The same question
answered correctly whenever no retry happened, which is what made it look like
run-to-run randomness rather than a rule. Selection is now separate from
ordering: `MAX_PRIOR_ANSWER_CHUNKS` of the `MAX_EVIDENCE_CHUNKS` slots may be
previous answers, the rest belong to the guidelines, and either kind may use
room the other does not need.

**A question is retrieved as its parts, not as one blob.** A question that asks
two things — "how quickly is access revoked, and how are we notified" — embeds
as a blend of both and ranks the clause for neither first. Before retrieving,
each question is split into several searches, one per thing it asks, phrased the
way a policy would state it and covering both languages for the key concept. Set
`QUERY_EXPANSION=false` to retrieve on the question's own wording alone.

Two details of that decide whether it works, and both were wrong. The budget
included the verbatim question in its count, so `MAX_SEARCH_QUERIES=4` bought
*three* decomposed angles — and a question like "walk us through offboarding"
needs asset return, access revocation and post-departure monitoring from five
different policies. Measured by kind: questions expecting one document retrieve
it 92% of the time, questions expecting three or more only 43%.

And the planner was quietly defeating its own bilingual instruction. Asked for
an Arabic query "in addition to" the English one, it wrote them on a single
line — `asset return policy OR سياسة إرجاع الأصول`. Queries are embedded, not
keyword-matched, so that string is searched *as itself*: a blend that means
nothing in either language and matches neither clause, while consuming one of
the few slots available. The prompt now forbids joining phrasings and the
budget is six. Together those took documents never retrieved at all from 26 to
19, and eliminated OR-merging entirely.

**Expansion completes a series, not a chapter.** A retrieval hit inside a split
unit pulls in its siblings, so the drafter never sees three items of a
nine-item list and reports them as the list. That is right for a clause series
and wrong for a standard with no internal headings to divide on: 79% of units
in this corpus are a single chunk and 96% are six parts or fewer, but the
remaining few run to 40, 100 and 113 parts, and between them hold 61% of all
the text. One hit inside one of those returned fourteen chunks from a single
document, filled every slot in the drafting prompt, and pushed every other
policy out — measured at a mean of 8.7 of 14 slots going to one document, and
all 14 on four of the golden questions. `MAX_EXPANDED_PARTS` draws the line;
past it the hit is returned alone, which is not contextless, because every part
repeats the unit's stem. Capping it moved document recall from 49.3% to 60.9%
and clause recall from 34.9% to 47.7%, and took evidence lost to the prompt
budget from eight documents to none.

**A heading is not a retrievable section.** Sectioning splits on every heading,
so a heading immediately followed by another one — "## Contents",
"## Definitions", "## KEY TASKS" — became a unit whose entire content was its
own title. 105 such chunks were indexed from this corpus, the shortest eleven
characters long. They embed close to any query using the same word and consume
a slot to say nothing.

Fixing it took two changes at two levels, and the first alone was almost
useless. Merging the heading into the section it introduces cut those chunks
from 105 to 98 — because the unit is then divided *again* by the packer, and
when the block after a heading is too large to fit, the packer flushed
everything accumulated so far as its own group. The heading it had just been
given came straight back out as "part 1 of N". Ninety-two of the ninety-eight
survivors were that. The heading now leads the first piece of the split
instead, which took the count to **16**, and consolidated the corpus from 3,153
chunks to 2,940.

Worth knowing before copying this: measured on its own, the chunking work cost
about two points of document recall and three of clause recall. Larger, fewer
chunks carry more per embedding and discriminate slightly less. It stays
because an eleven-character chunk being ranked, cited and shown to a user as a
source is a correctness problem rather than a tuning one, and because the query
and budget changes below more than repaid it.

**Chunks are whole sections, not single clauses — and never larger than that.**
Retrieval units follow the document's own structure, then adjacent units are
merged until they approach `CHUNK_SIZE`, and anything with no structure left to
split on is hard-wrapped at the nearest clean boundary. That last step matters
on converted standards: a single-cell Markdown table holding an entire section
has no rows to divide by, and it produced 9,000-character chunks that would
have crowded everything else out of the drafting prompt. Clause-scoped chunks cite beautifully and answer badly: with
§3.4.3 and §3.4.4 in separate chunks, a question about how quickly access is
revoked retrieved 3.4.4 alone and concluded the policy specified no timeframe.
It does — in 3.4.3, one clause away. Every chunk still records the *range* of
clauses it covers, so a citation stays precise.

**The relevance score is a cosine, and for a long time it was not.** Chroma's
`l2` space returns the *squared* euclidean distance; LangChain's converter
divides by `sqrt(2)` on the assumption that it is an unsquared norm. For
unit-length BGE-M3 vectors that yields `sqrt(2) * cos - 0.414`, an affine
squash — so a chunk matching at cosine 0.72 was displayed as 0.60, and one at
0.65 as 0.50. Nothing ranked differently, because the transform is strictly
increasing and no code compared a score against a fixed threshold, but every
person reading the number was reading a good match as a mediocre one. The
cosine is now recovered in `_evidence()` and the store's own figure kept
alongside it as `raw_score`. Note also that absolute values are not
comparable between embedding models: on this corpus BGE-M3 scores unrelated
text at cosine 0.33 and gibberish at 0.27, so 0.65 is a wide margin, not a
weak one.

**Several searches agreeing on a chunk is a signal, and it is free.** Query
expansion issues one search per thing the question asks, in both languages,
and those searches are written to converge. A chunk three of them return
independently has been arrived at three ways; `QUERY_AGREEMENT_WEIGHT` lifts
it proportionally. It costs nothing — the searches have already run — and it
is inert where it would mean nothing: with query expansion off every chunk has
one hit and the multiplier is exactly 1, and with the reranker on the
cross-encoder's ordering is used instead. Measured on the golden set it is a
small effect (see below), which is worth knowing before relying on it.

**Two numbering conventions, both of which have to be read.** T2's own
policies number clauses with dots — 3.4.1. The NCA and SDAIA publications
number controls with dashes — 1-1-1 — and the ECC implementation guide, the
largest document in this corpus, uses nothing else: 352 dashed control ids and
not one dotted clause. Recognising only dots left all 843 of its chunks with no
clause identifier at all, so its citations gave a file name and no reference,
and the mechanical check that a named clause is actually supported could not
evaluate a single claim drawn from it. Corpus-wide only a quarter of chunks
carried an identifier. Both notations are read now, each kept in the separator
its own document uses, because the identifier is something a reader looks up in
that document — and a control table's chunk carries the *range* of rows it
holds, since citing the first of nine rows looks precise and is not.

**Half of every Markdown table Docling emits is alignment padding.** Docling
pads each cell to the width of the widest cell in its column, so a table
carrying one 200-character definition pads all of its other rows to match.
Across this corpus that padding is 47% of all table text -- 7.07M characters of
table holding 3.73M characters of content, and one 18-row table measuring
40,320 characters to hold 8,323.

The cost is not cosmetic, because the padding is charged three times: against
`CHUNK_SIZE`, so tables that fit comfortably were split anyway; into the
embedding, so half of a table chunk's vector was runs of spaces; and again in
the drafting prompt, where thirty evidence chunks share one context window. The
vulnerability-scanning frequency table is the case that exposed it. It measures
~2,000 characters padded and ~700 unpadded, so it was cut into four pieces, and
each piece carried only row one of the table as its repeated header -- which in
that table is Docling's flattening of a merged cell, `| | Systems | Systems |
...`, naming no column at all. The drafter was shown six columns called
"Systems" and no row saying which frequency belonged to which kind of system.

Padding is now stripped when the table is parsed, so every stage downstream
counts and stores content rather than whitespace. Nothing but whitespace is
removed -- every cell, every pipe and every duplicated spanning label survives,
asserted as a property test on the non-whitespace characters, and verified
across all 80 documents at 0 rows dropped and 0 cells altered. Where the header
*is* a spanned label, the rows beneath it are carried onto every piece too, up
to the first that really names the columns.

The corpus went from 3,034 chunks to 1,720 and from 2.90M characters of stored
content to 1.92M -- which is de-duplication, not loss: a split table repeated
its header on every piece. Measured the same way against the source text, the
new index covers *more* of it than the old, 1.22% of source 5-grams absent
against 2.61%.

**Docling is asked for a heading hierarchy, which it does not build by
default.** `do_pdf_heading_hierarchy` is off in Docling, and the consequence
here was severe: 85 of 86 documents came back with every heading at one level.
The chunker sections on heading depth, so a flat document gives it a list where
it expects a tree, and a chapter with no sub-levels cannot be divided by its own
subsections. Turning it on produced real trees — one policy went from 34
headings all at level 2 to `{2: 2, 3: 6, 4: 26}`.

The crude measure said this changed nothing: chunks trapped in oversized units
moved only from 1,925 to 1,887, and on the ECC guide the count went marginally
*up*. Measured on retrieval instead it was worth 5.8 points of document recall
and 10.8 of clause recall, because better sectioning produces chunks whose text
is more coherent and which therefore embed better. The lesson is about the
metric, not the setting: unit-size statistics are a proxy, and the proxy was
wrong.

**Precision was the wrong lever, and it took four experiments to establish.**
Recall had been measured all along; precision had not, so `eval/retrieval.py`
now reports it alongside, alongside a budget curve computed from a single pass.
On this corpus only 17% of the chunks reaching the drafter sit on a clause the
question asked about, and even the five best-ranked are barely a third — so the
prompt looked badly polluted and cutting it looked obviously right.

It was not. Four ways of raising precision were measured, each scored on
generation with three paired judge passes:

| intervention | precision | accuracy |
|---|---|---|
| relative score floor (0.85) | +3.8 | not run: cost 8.7 recall first |
| smaller per-query `top_k` (5) | +1.0 | not run: cost 4.7 clause recall |
| LLM relevance grader, floor 8 | +4.2 | **-1.3** |
| LLM relevance grader, floor 16 | +2.7 | **-1.9** |

The grader bought more precision than anything else, cut the prompt by 40% with
recall almost intact, and still lost accuracy — in six paired passes across two
settings, never once positive. Raising the protected floor made it worse, which
rules out "the floor was too low".

The conclusion is that the drafter is not much distracted by off-target policy
text, and that the material the metric scores as noise is doing some work: a
definitions section, a neighbouring control, the regulation a policy
implements. `eval/retrieval_targets.json` names only each question's *primary*
sources, so measured precision is a lower bound, and this result says the gap
between it and the truth is wide. Treat the precision figure as a comparator
between configurations, never as a thing to maximise.

The grader survives behind `RELEVANCE_FILTER_ENABLED`, off. It is worth
retrying against a larger golden set, where "relevant" could be defined well
enough for the metric to tell a useful neighbour from a useless one.

**Agreement was counted once per copy, not once per search.** `retrieve` stamps
each chunk with how many of the round's searches returned it, but a chunk six
queries agree on comes back in six batches, and the state reducer sums
`query_hits` when it de-duplicates: six copies each stamped with six
accumulated to thirty-six. The multiplier meant to top out at 1.75 reached 6.4,
and since cosines on policy prose span only 1.5x end to end, ranking was decided
by how many phrasings found a chunk rather than by how well it matched. Fixed by
collapsing duplicates in `retrieve`; measured afterwards, retrieval was
unchanged, because the evidence budget is rarely the binding constraint --
roughly 37 distinct chunks are retrieved and 38 are allowed through, so almost
nothing was being cut and ordering had little to decide.

**The search drawer, and two views of a chunk.** `GET /api/search` runs the
same retrieval the drafter uses, but returns the passages rather than an answer
written from them, so a person can check what the corpus actually says. Three
modes, because the two methods fail in opposite ways: `semantic` finds material
that means the same thing in either language, `keyword` finds the literal
string -- which is what you want when checking whether a policy really says
"90 days" -- and `hybrid` fuses them by reciprocal rank rather than by score,
since a BM25 rank and a cosine are not comparable numbers. A lexical hit is
flagged `is_lexical` so its figure is never read as a similarity. Units are not
expanded here: the answering path completes a split series so the drafter never
mistakes a fragment for the whole list, but a search result should be the chunk
that actually matched.

Chunks render either as the raw Markdown the parser produced or laid out, and
the toggle sits next to the text in both the search drawer and an answer's
citations. The formatted view earns its keep now that tables survive chunking
intact -- but it is also where this feature failed once before, by splitting a
row on the pipe and discarding the first and last field, which is right only
when a row has both an opening and a closing pipe. 1,081 of 3,044 chunks lost
up to 92% of their words and nothing caught it, because a prettier panel still
looks correct.

So `renderChunk` verifies itself: it compares the word multiset of what it
produced against the source text and falls back to raw if one word went
missing. Building that guard found its own bug -- reading the rendered text off
`textContent` concatenates adjacent table cells, so a header row of six cells
reading "Systems" came back as the single word "SystemsSystemsSystems...", and
the check reported a loss on 185 of 194 real chunks. Every one was a false
alarm, and left alone it would have silently disabled the formatted view
entirely. Measured against 246 real chunks -- 136 with tables, 10 Arabic --
after the fix: none loses a word.

**A citation names the file, not just a code.** Answers cite
`T2 - سياسة إدارة كلمات المرور..pdf [PRO-PMP-2024] §5–5.2`, because the internal
document code alone is not something a reader can find in a folder of eighty
files. The code stays alongside it, since assessors ask for it.

**Every answer is reviewed before you see it.** A second model call checks each
claim against the retrieved sources and can send the question back for one more
retrieval round with a differently-worded query. Answers that stay ungrounded,
or that land below the confidence threshold, come back flagged rather than
silently accepted — the failure mode that matters in compliance work is a
confident wrong answer, not a missing one. A mechanical check runs alongside it:
any clause the prose names must appear in something the drafter actually read.

That last distinction is load-bearing. Checking against what the drafter
*listed* as used, rather than what it read, flagged correct answers: asked how
often penetration testing runs, the drafter read both halves of a split policy
section, wrote a correct sentence citing §3.1.20 from the second half, and
listed only the first. The clause existed and was on screen. Support is now
judged against everything retrieved, and the chunk that backs a named clause is
attached to the answer's evidence — so the reader can check it instead of
taking the citation on trust, and "1 supporting source" no longer appears under
an answer built on two.

**Not knowing is a valid answer.** When the knowledge base does not cover a
question, the agent says so and scores itself low instead of inventing a
certification you do not hold.

---

## Setup

Dependencies live in `.venv` in this directory, managed by [uv](https://docs.astral.sh/uv/).

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux / Git Bash
source .venv/Scripts/activate       # .venv/bin/activate on macOS and Linux
```

To build the environment from scratch, or to add a package:

```bash
uv sync --extra dev                 # create .venv from pyproject.toml
uv pip install <package>            # note: `uv pip`, and there is no `pip` inside .venv
```

Then:

```bash
cp .env.example .env                # then set GROQ_API_KEY
```

The only credential you need is a Groq key. Embeddings run locally through
sentence-transformers (see `src/embeddings.py`) and need no key.

**If a command fails with `ModuleNotFoundError`, check which interpreter you
are on before installing anything.** A conda environment or another project's
`.venv` earlier on `PATH` will supply its own `uvicorn` and `python`, which then
import this project's code against the wrong site-packages. Verify with:

```bash
python -c "import sys; print(sys.prefix)"
```

It must print the `.venv` inside this directory. Running through the
interpreter explicitly — `.venv/Scripts/python.exe -m uvicorn src.api:app
--reload` — sidesteps activation entirely and is the reliable way to be sure.

---

## Running

### Web interface

```bash
uvicorn src.api:app --reload
```

Open <http://127.0.0.1:8000>. Upload guidelines and previously answered
assessments, then submit a new assessment. The document library opens original
PDFs, shows the extracted text used by the agent, and includes bundled English,
Arabic and bilingual trial documents. Results are editable inline and download
as JSON, CSV (UTF-8 with a BOM, so Excel opens Arabic correctly), PDF or Word.

**The question list is the unit of work, not the file.** An upload is read into
a list of questions that can be corrected before anything is answered — which
matters because extraction is the step most likely to need a human: a numbered
list can lose an item to a page break, and a row of guidance can read as a
question. Answering is minutes and extraction is seconds, so reviewing first
costs nothing and can save a whole run.

The same list takes typed questions, so a single question can be asked without
any document at all. And it can be added to after a batch has been answered:
only the questions still waiting are sent, so a second batch never re-answers —
or re-charges for — the first. Deleting a question that has already been
answered takes its answer with it, and a question that has been answered cannot
be edited, because changing the words under an existing answer would make the
pair a lie.

**Prefer Word for an Arabic questionnaire.** A PDF stores glyphs, so the Arabic
has to be shaped, bidi-reordered and hand-wrapped before it is drawn — and the
order of those steps against line breaking is delicate enough to have gone
wrong twice. A .docx stores the characters and a right-to-left marker, and
Word does the layout; the text also stays selectable, searchable and editable,
so a reviewer can finish the form in the file the agent produced. Both formats
take the same options and apply the same rule about what to include.

### CLI

```bash
python -m src.cli guidelines policies/*.pdf
python -m src.cli answers completed/2024-vendor-review.docx
python -m src.cli answer new-assessment.docx --out filled.json
python -m src.cli answer new-assessment.docx --language ar
python -m src.cli stats
```

### API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/knowledge/guidelines` | Index policy documents |
| `POST` | `/api/knowledge/prior-assessments` | Index completed assessments as Q/A pairs |
| `GET` | `/api/knowledge` | What is currently indexed |
| `DELETE` | `/api/knowledge/sources/{name}` | Remove one file |
| `DELETE` | `/api/knowledge` | Empty the knowledge base |
| `GET` | `/api/search` | Search the indexed corpus directly — `mode=semantic\|keyword\|hybrid` |
| `GET` | `/api/documents` | List uploaded and bundled trial documents |
| `GET` | `/api/documents/{origin}/{category}/{name}/file` | View the original file |
| `GET` | `/api/documents/{origin}/{category}/{name}/preview` | Preview PDF or DOCX in the browser |
| `GET` | `/api/documents/{origin}/{category}/{name}/text` | View extracted text |
| `POST` | `/api/assessments/answer` | Answer a new assessment (extract and answer in one call) |
| `POST` | `/api/assessments/extract` | Extract the questions without answering them |
| `POST` | `/api/assessments/answer-questions` | Answer a list of questions, with no document involved |
| `GET` | `/api/assessments/progress/{run_id}` | How far a run has got, while it is still running |
| `POST` | `/api/assessments/export/pdf` | Render the answers as a PDF |
| `POST` | `/api/assessments/export/docx` | Render the answers as a Word document |

Interactive docs at `/docs`.

---

## Language handling

By default each question is answered in the language it was asked in, so a form
that mixes Arabic and English comes back mixed the same way. Pass `language=ar`
or `language=en` to force one language for the whole assessment — the agent will
answer an English question in Arabic from Arabic or English sources, and vice
versa, because BGE-M3 embeds both into one space.

---

## Tracing

Every LLM call, retrieval and graph step can be recorded to LangSmith. It is
**off by default and should stay off until the data question is settled**,
because switching it on is a decision about data residency rather than about
observability.

> **Tracing sends your policy text outside Saudi Arabia.**
> A trace carries the prompt, and the prompt carries the policy chunks
> retrieved to answer the question. LangSmith offers an EU region and a US
> region; **there is no Saudi region**, so any tracing at all is a cross-border
> transfer of internal policy text and of the client questionnaires being
> answered. For an organisation whose own corpus includes NCA and SDAIA
> material, that is a question for whoever owns the documents — and, quite
> possibly, one with a PDPL answer attached. Enable it only once you are
> comfortable with it, and turn it off again when you no longer need it.

The setting therefore defaults to false, and when it is on the service logs a
warning at every start naming the project, the endpoint and the fact that the
data leaves the country — so nobody discovers months later that a debugging
switch was left on.

```bash
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com   # EU region
LANGSMITH_API_KEY=lsv2_...
LANGSMITH_PROJECT=Cyber-Assessment-Answering-Agent
```

**Putting those four lines in `.env` is not, on its own, enough — and the way
it fails is silent.** LangChain and the LangSmith client read `os.environ`
directly. Settings here are loaded by pydantic-settings, which populates the
`Settings` object and *not* the environment, and nothing in this codebase calls
`load_dotenv`. So the values arrive in `settings.langsmith_tracing`, no library
ever asks, and tracing looks configured while recording nothing.
`config.configure_tracing()` is the bridge. It runs at import of `src.config`,
so every entry point — the API, the CLI, `eval/` — is covered without each
having to remember, and it uses `setdefault` so a variable already exported in
the real environment beats whatever is in the file. Tracing with no API key is
refused outright rather than half-configured, with a warning saying so.

The test suite never traces. `tests/conftest.py` forces it off for the session:
a deployment with tracing on in its `.env` would otherwise have every test that
touches a chain post runs to the shared project, paying a network round trip
per test to fill it with fixtures.

**What a trace says.** A LangGraph run is called `LangGraph` by default and
carries nothing to filter on, which makes a project of a few thousand runs
useless for the one thing it is for — finding the question that went wrong. So
each run is named for its question and tagged with the axes worth slicing by:

```
answer[12]   tags: run:9f3c1a  lang:ar  type:free_text
             metadata: question_id, question (300 chars), language,
                       question_type, run_id, section
```

The `run_id` tag is the batch, because the first thing anyone looking at a
failed answer wants is the other questions from the same run. The metadata
carries no answer text and no document text beyond the question itself — the
prompts already carry the sources, and there is no reason to send them twice.

Inside a run you get the graph as it executed — `plan → retrieve → rerank →
draft → review → finalize`, the retry edge when the reviewer sends one back,
and every `ChatGroq` call with its token counts, which is also how the token
cost of a configuration change can be read off rather than estimated.

## One embedding per query

Guidelines and prior answers are not two stores. They are one Chroma
collection, `assessment_knowledge`, told apart by a `source_type` filter on the
metadata. Asking for each separately therefore sent the same text to the
embedding service twice and got the same 1024 numbers back -- with query
expansion, two round trips per query and half of the embedding work in a run,
against the slowest and least reliable dependency the system has.

`KnowledgeStore.search_types` embeds the text once and runs one local Chroma
query per source type against that vector. Still one query per type rather than
a single unfiltered one, because the types have different budgets
(`TOP_K_GUIDELINES` against `TOP_K_PRIOR_ANSWERS`): a single search returns the
best `k` regardless of kind, and on a corpus that is almost entirely guidelines
that means prior answers never appear at all.

Two things about this were easy to get wrong, so both are pinned by tests.
The by-vector call returns **raw distances** -- lower is nearer -- where the
by-string call LangChain would otherwise use returns **relevance**, higher is
nearer. Swapping one for the other without applying
`_select_relevance_score_fn` would invert the ranking and silently corrupt the
cosine figure shown to a reader, since `cosine_from_relevance` is calibrated
against that exact scale. And moving the embedding out of Chroma and into this
class meant the fake vector store the suite runs on no longer intercepted it,
so every retrieval test started reaching the network; `_embed_query` exists as
a seam for that reason and the fake answers it.

## Page numbers

Docling emits Markdown with no page information whatsoever, so until now a
citation could name a clause but never a page. It will insert a fixed
placeholder between pages if given one, and the local pdfplumber loader already
emits `--- page N ---` markers that the chunker reads. `docling_client` asks for
the placeholder and rewrites it into those markers, so page numbers reach chunk
metadata without the chunker learning a second convention -- verified against a
nine-page policy, where eight placeholders became nine markers and every one of
its fourteen chunks came out with a page.

Chunks record `page` and `page_end`, because running over a page break is
ordinary -- a table continues, a clause carries on -- and citing only where the
text starts sends a reader to the wrong half of it. The locator shows the page
beside the clause rather than instead of it:

```
T2 - Vulnerabilities Management Policy.pdf §3.1.1 (Page: 3)
T2 - Cybersecurity Incident and Threat Management Policy.docx.pdf §3.1.6 (Pages: 5–6)
T2 -   سياسة إدارة كلمات المرور..pdf [PRO-PMP-2024] §5–5.2 (Page: 4)
```

A clause number says what to look for; the page says where to open the file,
and on a 161-page standard that is the difference between a citation someone
can check and one that merely identifies the text. Because `locator` is a
computed field on `Evidence`, this reaches the citation chips, the retrieved
sources list, the search drawer and both exports without any of them changing.
A document indexed before page markers existed reports no page rather than a
guessed one: an invented page number makes an uncheckable citation look
checkable.

This changes what extraction produces, so `_EXTRACTION_VERSION` is `7` and the
placeholder is part of the cache key. Adopting it means re-extracting the
corpus (Docling, about an hour) and re-indexing (embedding, about 25 minutes).

## Where the time goes

Measured by wrapping each graph node and each remote call, rather than
estimated.

**Answering one question: about 13 seconds, three quarters of it Groq.**

| stage | median | share |
|---|---|---|
| plan | 4.0 s | 38% |
| retrieve | 0.7 s | 6% |
| rerank | 0.00 s | — (off) |
| draft | 2.4 s | 19% |
| review | 3.0 s | 24% |
| finalize | 0.00 s | — |

The planner is the largest single item, larger than drafting: it is a
structured-output call, and Groq's tool-calling overhead is fixed while the
prompt is too short to amortise it. Retrieve looks cheap and is not idle --
54 vector searches summing to 81.9 s of service time compress into 12.8 s of
wall clock, which is the concurrency inside that node doing its job.

Retrieve was 2.24 s until an empty collection stopped being searched. The query
is embedded *before* the source-type filter is applied, so asking a
prior-answers collection holding zero chunks still cost a full remote round
trip -- five or six per question, against the slowest and least reliable
dependency in the system. `retrieve` now consults the cached per-type counts
first. That also meant the evidence split could no longer be positional:
`results[0::2]` and `[1::2]` assumed every query produced exactly one search of
each kind, which is false the moment one is skipped, and would have labelled
guideline chunks as prior answers.

**Indexing is 99.8% embedding, and none of it is ours to fix.**

| stage | share |
|---|---|
| extract (cache hit) | 0.1% |
| chunk | 0.1% |
| embed + store | 99.8% |

293 ms per chunk. The client already batches at 64 per request, and the
endpoint is flat at roughly 5.1 texts/s no matter how it is asked:

```
embed_documents(  1)   757 ms/text        1 parallel batch    5.1 texts/s
embed_documents( 64)   197 ms/text        2 parallel batches  5.3 texts/s
embed_documents(128)   198 ms/text        8 parallel batches  5.1 texts/s
```

It is serialised server-side, so neither larger batches nor more connections
help. 2,698 chunks is about nine minutes of pure embedding; the rest of a
24-minute re-index is per-document overhead. The only levers are fewer chunks
or a faster embedding service.

Extraction is the other order of magnitude: **0.002 s from cache against 61.6 s
through Docling**, which is why `data/extracted` is worth keeping alongside the
index rather than regenerating.

**`MAX_CONCURRENT_QUESTIONS` buys latency and nothing else.** Twelve real
questions, same corpus, same models:

```
concurrency 1:  121.1 s (10.1 s each)   0 errors   0 rate limits   mean confidence 0.83
concurrency 4:   36.0 s ( 3.0 s each)   0 errors   0 rate limits   mean confidence 0.84
```

Answer order, question-to-answer mapping and citation counts are unchanged,
because `asyncio.gather` returns in argument order regardless of completion
order and each question owns its state. `tests/test_concurrency.py` pins that
at 1, 2, 4 and 8 with completion order deliberately reversed -- the arrangement
a collector that appended results as they arrived would get wrong while looking
correct serially -- along with the cap actually being honoured, a failure
staying contained, and the document fan-out reading the same setting through
LangGraph's `max_concurrency`.

## Facing a network

Three properties were established by attack rather than by reading, and the
tests that establish them are in `tests/test_hostile_input.py`.

**Nothing a caller names reaches the filesystem.** `/api/documents/{origin}/
{category}/{name}` puts three caller-controlled segments into a path.
`resolve_document` refuses any name that is not its own basename, insists on a
supported suffix, and compares the resolved parent against the resolved base,
so `../../.env`, its URL-encoded and doubled forms, and the Windows-separator
variants all end at a 400. Uploads are reduced to a basename before writing,
which is checked by asserting that every file written lands in the upload
directory itself rather than by trusting the reduction.

**A broken dependency is a sentence, not a stack trace.** Every route here
talks to something that can be down -- Chroma, the embedding host, Groq,
Docling, the disk. An unhandled exception handler turns any of them into a
clean 500 with the detail in the log, because FastAPI's default page carries
server paths into the browser. Search goes further and degrades: literal
matching needs no network, so when the embedding host stops answering the
results still come back, flagged `degraded` so the interface can say which half
ran rather than implying the corpus is empty.

**Concurrency was where the real bug was.** `get_store()` was an `lru_cache`,
which does not hold a lock while the wrapped function runs, so two threadpool
requests both constructed a `KnowledgeStore` and raced through Chroma's
process-wide client registry -- a bare `KeyError` on the persist directory, and
a 500 for whichever request lost. It surfaced only when the search drawer began
loading its file list at the same moment the page asked for knowledge stats.
Under a lock now, and asserted by having eight threads construct it at once.

## Cost of a request

A 16-way concurrent burst of 48 requests took 30.8 seconds and now takes 7.8.
Almost all of it was bookkeeping rather than work:

| | before | after |
|---|---|---|
| search, median | 10.97 s | **2.37 s** |
| search, p95 | 12.69 s | **2.93 s** |
| `/api/knowledge` | 7.22 s | **2.08 s** |

Three things were being recomputed that never change between writes. Counting
chunks per source type and listing indexed file names were a full metadata scan
each -- 216 ms and 207 ms against a search that itself takes 45 ms, so nine
tenths of a search was overhead, and `stats()` repeated the same scan on every
page load. They share one cached catalog now, invalidated exactly where the
lexical index already was. Separately, the literal matcher was building a BM25
index it never consults, 511 ms of tokenising per process for a substring
query; the chunk map it actually wants is now cached on its own. Both builds
are locked, so a concurrent burst builds once rather than once per thread.

The caching is only as good as its invalidation, so `tests/test_store_caches.py`
exercises every write path: a new document appears immediately, a deleted one
disappears, a re-upload replaces rather than duplicates, and a document added
after the first search is visible to the next one.

## Configuration

Everything lives in `.env` (see `.env.example`). The values you are most likely
to change:

| Setting | Default | Notes |
| --- | --- | --- |
| `GROQ_CHAT_MODEL` | `openai/gpt-oss-120b` | Used for extraction, drafting and review |
| `LANGSMITH_TRACING` | `false` | Record traces to LangSmith — **sends policy text outside Saudi Arabia**; see [Tracing](#tracing) |
| `DOCLING_BASE_URL` | `http://localhost:8092` | Docling host root; clear it to use the local loaders only |
| `DOCLING_DO_OCR` | `false` | Turn on for scanned documents — much slower |
| `DOCLING_FALLBACK_LOCAL` | `true` | Use pdfplumber/python-docx when Docling is unreachable |
| `EXTRACTED_TEXT_DIR` | `./data/extracted` | Cache for document text shown in the interface |
| `GROQ_BASE_URL` | `https://api.me-central-1.groqcloud.com` | ME-Central-1 region; clear it for `api.groq.com` |
| `MAX_ANSWER_ATTEMPTS` | `3` | Draft/review rounds per question |
| `MAX_CONCURRENT_QUESTIONS` | `4` | Raise carefully — Groq rate limits apply |
| `QUERY_EXPANSION` | `true` | Split a multi-part question into one search per part |
| `HYBRID_SEARCH` | `false` | Fuse a BM25 pass with the dense search — see Evaluation |
| `RERANKER_ENABLED` | `false` | Cross-encoder reranking; downloads ~2.3 GB on first use |
| `DOCLING_DO_OCR` | `false` | Force OCR on every document — normally unnecessary |
| `DOCLING_OCR_AUTO` | `true` | Turn OCR on by itself for a PDF with no text layer |
| `REVIEW_CONFIDENCE_THRESHOLD` | `0.6` | Below this, an answer is flagged for review |
| `TOP_K_GUIDELINES` | `5` | Guideline chunks retrieved per search query |
| `TOP_K_PRIOR_ANSWERS` | `5` | Previous answers retrieved per question |
| `MAX_EVIDENCE_CHUNKS` | `14` | Sources shown to the drafter per question |
| `MAX_PRIOR_ANSWER_CHUNKS` | `4` | How many of those may be previous answers |
| `EVAL_JUDGE_MODEL` | `openai/gpt-oss-120b` | Grades `eval/`; deliberately not the drafting model |

---

## Tests

```bash
pytest                # offline: loaders, routing, fan-out, failure containment
pytest -m live_ai     # opt-in: real Groq and embedding calls, costs tokens
python -m scripts.selfcheck   # checks the wiring, not just the units
```

---

## Evaluation

`eval/` scores the system against a golden question set — questions paired with
the core facts a correct answer must state, verified against the source
documents by a human.

`eval/golden_set.json` holds 42 cases across seven categories. The first 28
cover T2's own policies. The rest were added with the NCA ECC guide and the
SDAIA PDPL material, and cover two things the internal policies alone cannot:
**Regulatory Reference**, answered from the standards themselves, and
**Cross-Source Synthesis**, where a correct answer has to combine T2's policy
with the regulation — the breach question, for instance, has three separate
notification duties with three different deadlines, one internal and two
regulatory.

```bash
python -m eval.run_eval answer --out eval/results/current.json
python -m eval.run_eval score  eval/results/current.json --notes "what changed"
python -m eval.run_eval score  eval/results/current.json --baseline eval/results/previous.json
python -m eval.run_eval history
```

Every scored run is appended to `eval/history.jsonl` with the settings that
produced it — model, top-k, which retrieval passes were on, attempt budget — so
a later comparison can tell a real improvement from a configuration difference.
`history` prints them oldest first.

`answer` asks the live system every golden question. `score` grades any answers
file — including runs archived from an earlier version of the system — so a
change is measured against its predecessor on one rubric by one judge.

Three things keep the judge honest. It grades on a different model from the one
that wrote the answer. It is given the facts rather than asked to recall them,
so it checks whether the answer says what was already established rather than
what the policy says. And because the fact lists are known to be incomplete, a
specific the answer asserts that no listed fact covers is recorded as an
`unverified_claim` for a human to check, never scored as a fabrication.

The report also carries the calibration numbers: the spread of confidence
across the run and its correlation with the score. Confidence that does not move
with correctness is worse than no confidence at all, because it makes the review
queue meaningless.

### Measuring retrieval, separately from the answer

The judge reads the answer text and nothing else, so a low score cannot be
attributed: "the retriever never found the clause" and "the drafter was handed
the clause and ignored it" produce the same number. That blindness is not
theoretical — a change that dropped the guideline count in the drafting prompt
to *zero* on retried questions moved the graded accuracy by less than a point.

```bash
python -m eval.run_eval retrieval
python -m eval.run_eval retrieval --plans eval/results/plans.json --label with-agreement
python -m eval.run_eval retrieval --baseline eval/results/before.retrieval.json
```

It scores what retrieval found against `eval/retrieval_targets.json` — the
documents and clauses the golden set's `source_reference` names — by running
the real planning, retrieval, reranking and selection nodes. **No model grades
anything**, so a pass costs almost nothing and is deterministic once the
queries are fixed, which makes it the right tool for settling retrieval
settings that the judge's three-point noise cannot resolve.

Two design points are load-bearing:

**The targets are resolved once, into a file you can read.** Matching a prose
reference to a filename at scoring time would mean the metric partly measures
the string matcher. It does: the first version of that matcher reported eleven
broken references in the golden set, and every one of them was the matcher's
fault — CamelCase filenames tokenising as one word, an English document title
against an Arabic-only filename, a Jaccard variant that preferred a short
wrong filename to a long right one. Resolved and checked once, all 149 clauses
the golden set names were found in the corpus, in the documents it attributes
them to. The references are sound; it was the automation around them that was
not, which is exactly the failure that would have produced confident nonsense.

**`--plans` pins the expanded queries.** The planner is an LLM and rewrites its
searches slightly on every run, which moved document recall by several points
between two passes of an unchanged system — more than most settings worth
testing. Reuse one plan file across a sweep and the comparison is a comparison.

Three numbers matter more than recall@k. **Prompt recall** is whether the
material reached the drafter, which is the only place it can affect an answer.
**Selection loss** is material that was retrieved and then cut — the failure
the generation eval hides most completely. **Never retrieved** is the
retriever's own miss. Cases whose expected answer is "nothing documents this"
have nothing to retrieve and are excluded rather than counted as misses.

### Running a measurement pass

Settings that change a score are read from the environment, so a pass is one
command with the variable set in front of it, and the history file records
which one produced which numbers:

```bash
python -m eval.run_eval answer --out eval/results/baseline.json
python -m eval.run_eval score eval/results/baseline.json --label baseline --notes "42-case set, expanded corpus"

RERANKER_ENABLED=true python -m eval.run_eval answer --out eval/results/reranked.json
python -m eval.run_eval score eval/results/reranked.json --label reranked --notes "cross-encoder on"

GROQ_CHAT_MODEL=openai/gpt-oss-120b python -m eval.run_eval answer --out eval/results/gptoss.json
python -m eval.run_eval score eval/results/gptoss.json --label gptoss --notes "gpt-oss-120b drafter"
```

Then `python -m eval.run_eval history` to see them side by side, or
`score ... --baseline eval/results/baseline.json` for a per-case diff.

Two things worth knowing before reading the numbers.

**Score one answers file more than once before believing its total.** The same
unmodified `r18_docling.json`, graded four times by the same judge against the
same golden set, scored 79.0, 75.2, 77.6 and 77.1 — a spread of 3.8 points with
nothing changing but the judge. A single grading of a single run is not a
measurement at this resolution, and quoting one as though it were produces
confident claims that the next pass contradicts.

What *is* stable is the **paired** difference. Across four gradings of the same
two files, the delta between them stayed between -4.4 and -5.7 and never
changed sign, while each file's absolute level wandered by more than two
points. So grade both files in the same pass, repeat the pass, and read the
difference — never the level. Roughly 1.5 points of per-case movement also
comes from the drafter itself, which runs at temperature 0.2.

And the reranker adds about 30 seconds per question on CPU, so that pass takes
an extra twenty minutes or so.

### What the golden set currently says

Measured on the T2 policy corpus, 28 cases, judged by `openai/gpt-oss-120b`:

Measured on the **42-case set against the full 80-document corpus**. Every run
is in `eval/history.jsonl`; accuracy is only comparable within one judge column,
because judges differ in severity far more than configurations do.

| Drafter | Reranker | Accuracy (gpt-oss judge) | Fact recall | Contradictions |
| --- | --- | --- | --- | --- |
| minimax-m2.7 | off | 64.3% | 52.7% | 12 |
| gpt-oss-120b | off | 61.4% | 46.2% | 13 |
| minimax-m2.7 | on | 70.5% | 63.1% | 5 |
| gpt-oss-120b | on | 74.8% | 57.0% | 5 |
| gpt-oss-120b, after the grounding and citation fixes | on | 73.3% / 76.2% | 55.6% | 5 |

Two later runs stand apart from the rows above, because they were measured
after a previous-answers bank was added to the corpus and with the reranker
off, which is the configuration the system now runs in. They are comparable to
each other and to nothing else in this table:

| Previous answers in the prompt | Accuracy | Fact recall | Contradictions | Calibration |
| --- | --- | --- | --- | --- |
| uncapped (the old behaviour) | 56.2% | 36.2% | 15 | 0.284 |
| capped at 4 of 14 | 57.1% | **47.0%** | 12 | 0.396 |

**Accuracy is flat and fact recall is not**, which is the interesting part: the
answers changed from confidently thin to substantially complete without the
rubric total moving much. Guideline citations went from 70 to 120 across the
set, previous-answer citations from 51 to 26, and the number of answers
claiming the documentation does not cover the question fell from 4 to 1.

The per-case diff says where the movement came from. Splitting the 42 cases by
whether the change actually altered what the drafter saw:

| | cases | net score change |
| --- | --- | --- |
| sources identical — the cap did nothing | 18 | **−5** |
| sources changed — the cap did something | 24 | **+7** |

Five points of loss on cases whose input never changed is the noise floor,
measured rather than assumed, and it is worth more than the totals: one case
scored 5 and then 1 on byte-identical citations and a near-identical answer. So
per-category swings on a single run of this set mean very little. `Regulatory
Reference` fell 51.4% to 34.3%, and four of those six points are one case whose
sources were unchanged — but not all of it, and there is a plausible mechanism
for the rest: with ten guideline slots instead of two, lower-ranked internal
policy chunks reach the prompt and can dilute an answer that should come from
the regulation alone. Worth watching if regulatory questions matter most; the
reranker addresses exactly that ordering problem.

### What retrieval actually does

The first measurement of retrieval on its own, on the 80-document corpus with
the reranker off. Of 69 documents the golden set says an answer needs:

| | documents |
| --- | --- |
| reached the drafting prompt | 35 |
| retrieved, then cut before the prompt | 7 |
| **never retrieved at all** | **27** |

Document recall into the prompt is 50.7%, clause recall 32.9%, MRR 0.62, and
22 of 40 scorable cases had every source they needed. **The dominant failure is
recall, not ordering** — 27 documents are never found, and no amount of
reranking, fusion or agreement-weighting can promote a chunk that was never
returned. That is the number to attack, and it is one the generation eval could
never have shown, because an answer written without the right document reads
like a drafting failure.

Retrieval also degrades gracefully across categories in a way worth knowing:
`Direct Extraction` reaches 90% document recall, while `Synthesis` and
`Scenario-Based` — the questions that expect four or five different policies —
sit near 27%. A 14-slot prompt filled from `k=5` searches simply cannot hold
five documents' worth of clauses, so those questions are budget-bound rather
than retrieval-bound.

### What the measurements changed

Those numbers were the starting point. Working from them rather than from
intuition produced this, on the same corpus with the queries pinned:

| | Document recall | Clause recall | Lost to the budget | Never retrieved |
| --- | --- | --- | --- | --- |
| before | 47.8% | 32.2% | 11 | 25 |
| **after** | **66.7%** | **58.4%** | 4 | **19** |

Five changes, in order of how much they mattered.

**Capping unit expansion** was most of it, and it was invisible until retrieval
was measured directly: the prompt was being filled with one document's chapter.

**Widening the net only helped once the leak was fixed.** Raising
`TOP_K_GUIDELINES` on its own made things *worse* — retrieved recall rose from
60.9% to 71.0% while prompt recall fell from 49.3% to 42.0%, because everything
extra was cut before the drafter saw it. With expansion capped, the same change
is a small gain. The order of operations was the whole point: a lever that
looks harmful can be a lever whose benefit is being thrown away downstream.

**Fixing the query planner** — six queries instead of four, and one phrasing
per line — is what finally moved *never retrieved*, from 26 to 19. Nothing
about ranking or budget can recover a document no search ever asked for.

**Raising the prompt budget** to 30 chunks absorbs what the wider net finds.
This one has to be re-derived whenever retrieval changes, and the pattern
repeated exactly: after the planner fix, evidence lost to the budget jumped
from 1 document to 9, and lifting the budget converted that into recall.

**Capping how much of the prompt previous answers may take**, if a
previous-answers bank is indexed — see `MAX_PRIOR_ANSWER_CHUNKS` above.

Every one of those was found by measuring, and two of them looked like
*regressions* until the stage after them was fixed. That is the argument for
scoring retrieval in stages rather than end to end: `retrieved` and `in the
prompt` moving in opposite directions is the signal, and a graded accuracy
number cannot show it.

What is left is a pure recall problem: 19 of 69 expected documents are never
retrieved at all, almost all of them on questions expecting four or five
policies at once. `HYBRID_SEARCH=true` recovers roughly one and remains off,
having measured worse on the graded set. That is the next thing to attack, and
it will not be fixed by ranking.

### Does better retrieval produce better answers?

Graded end to end against a control on the same corpus:

| | Accuracy | Fact recall | Contradictions | Flagged | Sources per answer |
| --- | --- | --- | --- | --- | --- |
| before | 57.6% | 48.7% | 12 | 16 | 1.43 |
| after the retrieval work | 73.3% | 60.6% | 4 | 11 | 1.98 |
| **after extraction and numbering** | **79.0%** | **61.6%** | **4** | 13 | — |

The last row is the heading hierarchy and the dashed control ids together, on a
re-indexed corpus. Split the usual way: 7 cases whose citations were unchanged
contributed **−1**, and the 35 whose citations changed contributed **+13**.
`Scenario-Based` gained 25 points and `Cross-Source Synthesis` 20; citations
carrying a clause reference went from 108 to 173. Confidence also began
correlating with correctness again, from −0.02 to 0.26, having collapsed when
absence questions came to dominate the low-confidence band.

Split the usual way, by whether the change altered what the answer was built
from:

| | cases | net score change |
| --- | --- | --- |
| citations identical — nothing changed for this case | 11 | **+1** |
| citations differed | 31 | **+32** |

That is the shape a real improvement makes, and it is worth contrasting with
the query-agreement change measured above, where six of fourteen points came
from cases the change never touched. Here the untouched cases contribute +1.
Five independent measurements agree: clause recall up 26 points, fact recall
up 12, distinct sources per answer up 38%, contradictions down to a third, and
answers citing nothing at all down from 7 to 3.

By category, `Regulatory Reference` went 37.1% to 94.3% and `Cross-Lingual /
Arabic` 66.7% to 90.0% — both dominated by the documents that were being
crowded out of the prompt. `Out of Bounds` did not move, which is the right
answer: those questions are correct when they report an absence, and nothing
here changes whether an absence is real.

Two costs, both worth stating. Given five sources where it previously had one,
the drafter sometimes writes a broader answer and loses a specific reference —
the dilution risk that comes with a 30-chunk prompt. And input tokens per
question roughly doubled, for the drafting and the review call alike.

**Confidence stopped correlating with correctness, and the reason is not what
it looks like.** The correlation fell from 0.38 to about zero. Answers the
system was confident about score 3.62 on average; answers it was *not*
confident about score 3.67 — statistically indistinguishable. But five of the
nine low-confidence answers are `Out of Bounds` questions, where the correct
answer is that the documentation does not cover the topic, and the drafting
prompt explicitly instructs a confidence at or below 0.3 for exactly that case.
Retrieval improving meant more of those absences were identified correctly, and
each correct one is a low-confidence, high-scoring point that flattens the
correlation.

So the number is measuring the wrong thing rather than reporting a broken
system, and the fix is not to make the model more confident about admitting
ignorance. A reviewer arguably *should* see "we have nothing documenting this"
near the top of the queue before it goes back to an assessor. What the
correlation cannot distinguish — and a human reading the queue can — is
"uncertain because the sources are thin" from "certain that the sources are
silent". The remaining genuine miscalibration is narrower: one answer scored 5
at a confidence of 0.20 because the grounding reviewer judged it ungrounded
despite three good citations.

**Query agreement was measured and is close to neutral.** With the expanded
queries pinned so the comparison is exact:

| `QUERY_AGREEMENT_WEIGHT` | Document recall | Clause recall | Cases fully covered |
| --- | --- | --- | --- |
| 0 | 50.7% | 32.9% | 22 |
| 0.10 / 0.20 / 0.30 | 49.3% | 34.9% | 23 |

Clause recall up two points, document recall down one and a half, and the
effect saturates immediately — 0.10, 0.20 and 0.30 produce byte-identical
results, so only a handful of chunks are close enough for the lift to reorder
them. It is on by default because the finer-grained measure improves and it
costs nothing, but it is not a lever: with 37 chunks retrieved into 14 slots,
reordering rarely changes membership.

Graded end to end against a control that differs only in that weight, it looks
much better than it is — and this is the clearest example in the project of why
the generation eval cannot settle a retrieval question:

| | Accuracy | Fact recall | Calibration |
| --- | --- | --- | --- |
| `QUERY_AGREEMENT_WEIGHT=0` | 57.6% | 48.7% | 0.384 |
| `QUERY_AGREEMENT_WEIGHT=0.15` | 64.3% | 45.9% | 0.557 |

A 6.7-point gain, with fact recall moving the other way. Splitting the 42 cases
by whether the change altered the citations at all:

| | cases | net score change |
| --- | --- | --- |
| citations identical — the weight did nothing | 21 | **+6** |
| citations differed — the weight did something | 21 | +8 |

**Six of the fourteen points came from cases the change provably did not
touch.** One of them scored 1 and then 5 on identical citations. So the noise
floor on this set runs to about six points in whichever direction it happens to
fall — the prior-answer cap measured it at −5 on eighteen unchanged cases —
and an +8 on the half that did change is not distinguishable from it. The
honest reading is that query agreement's effect on graded accuracy is **not
measurable here**, which is exactly what the retrieval numbers predicted.

That is the argument for the retrieval harness in one table. It has no judge,
no drafting temperature and no mixture-of-experts routing, so with the queries
pinned it resolves a two-point change that a 42-case graded run cannot see
through a six-point fog.

**Judge variance is about three points, so read the table with that in mind.**
The last row is one answers file scored twice by the same judge: 73.3% and
76.2%. Nothing about the system changed between them. Retrieval breadth shows
the same picture — `TOP_K_GUIDELINES` of 5 and 8 both scored exactly 160/210
with the reranker on, so the smaller value is the better default: same answers,
fewer chunks to rerank. Only differences larger than that spread are worth
acting on, which in this project means the reranker and nothing else.

**The reranker is the finding.** Same drafter, same settings, only the
cross-encoder differs: +13.4 points for gpt-oss-120b and +6.2 for
minimax-m2.7, with contradictions of a golden fact more than halved. It matters
most on the regulatory questions, which went 45.7% to 88.6% — dense scores on
this corpus bunch between 0.32 and 0.36, so on eighty documents the right chunk
routinely lands just outside the cutoff, and ordering within that band carries
almost no information. It costs about 30 seconds per question on CPU and
roughly a second on a GPU, which is the real decision to make about it.

**The drafter matters much less than it looks.** The two models sit 2.9 to 4.3
points apart depending on the judge, inside the noise band. minimax-m2.7 covers
more expected facts (63.1% against 57.0%) while gpt-oss-120b scores slightly
higher on the rubric.

A caution about that comparison, and the reason for the second judge: the
default judge *is* gpt-oss-120b, so scoring its own answers is self-marking.
Re-scoring both reranked runs with `llama-3.3-70b-versatile` narrowed the gap
from 4.3 to 2.9 points, so there is a real but modest self-preference. Note also
that the neutral judge scored the identical answers at 86.7% and 83.8% — twelve
points more generous across the board. That is judge severity, not quality, and
it is why the history file records which judge produced each row.

Hybrid search is the one change that did not survive measurement, and it is off
for that reason (measured on the earlier 28-case set). It does what it was added to do — it moved the PDPL 72-hour
breach-reporting clause from rank 11 to rank 1, a miss the human evaluation
called the highest-stakes in the set — but it promotes the wrong section of the
right document about as often, and it cost the password-length question that
the Arabic fix had just recovered. Six wins, five regressions is a coin flip,
and the coin lands on the failure mode that matters most here: a confident "the
policy does not specify". The code, the flag and its tests are kept because the
trade-off is corpus-dependent, not because it is dormant.

---

## Layout

```
src/
  config.py       settings, read once from .env
  models.py       domain models + structured LLM output schemas
  llm.py          Groq factory, with recovery for Groq's tool_use_failed
  embeddings.py   BGE-M3, run locally through sentence-transformers
  documents.py    PDF/DOCX extraction, incl. the RTL text-layer path
  docling_client.py  the hosted Docling conversion service
  chunking.py     structure-aware chunking with clause ranges
  extraction.py   text -> questions, text -> Q/A pairs
  knowledge.py    Chroma store for guidelines and prior answers
  verification.py mechanical checks, and why a score came out low
  formatting.py   the slice of Markdown the drafter actually writes
  export_pdf.py   PDF export, incl. Arabic shaping and line breaking
  export_docx.py  Word export; Word lays Arabic out, so we only mark it
  prompts.py      every prompt
  graph/          LangGraph state, nodes and wiring
  service.py      the orchestration the API and CLI share
  api.py          FastAPI app
  cli.py          command line
  static/         the web interface
eval/             golden-set runner, LLM judge and scoring report
demo_data/        generator for the bundled trial corpus
```

---

## Limits

- **Arabic sentences containing Latin runs can arrive out of order.** A
  displaced list marker is repaired at ingestion — `…؟ وما .25` becomes
  `25. …؟ وما`, which is what stabilised question extraction from 27-or-28 to a
  reliable 28. But where an embedded acronym splits an Arabic sentence, the
  segments around it can still be transposed by the converter, and repairing
  that reliably would mean reconciling two independent extractions of the same
  page. Arabic questions containing Latin acronyms are the ones to check.
- **Scanned PDFs need OCR turned on.** Set `DOCLING_DO_OCR=true` to read them;
  with OCR off (the default) a PDF with no text layer is rejected with an
  explanatory error rather than silently indexed empty. The local fallback has
  no OCR at all. Except when 
- **Answers are drafts.** Anything flagged `needs_review` — and ideally
  everything else — should be read by a person before the form is submitted.
- **Storage paths are anchored to the project, not the working directory.** A
  relative `CHROMA_DIR` in `.env` would otherwise mean a different folder
  depending on where the process was launched, and the failure is silent: an
  empty database is created and the knowledge base reports nothing indexed.
- **The embedding endpoint is a hard dependency at ingest time.** If
  `EMBEDDING_BASE_URL` is unreachable, indexing that file fails and is reported
  per file; answering fails per question and the rest of the run continues.
  `src/embeddings.py` carries a commented local `HuggingFaceEmbeddings`
  alternative for working offline — the vectors are compatible, since it is the
  same BGE-M3 model.
- **Filled forms are not written back into the original file.** Output is JSON
  or CSV; re-injecting answers into the source PDF/DOCX layout is not implemented.
- **The corpus is not de-conflicted for you.** Byte-identical uploads are
  skipped, but two policies that disagree — a four-tier classification scheme in
  one and a five-tier scheme in another — are both retrieved and both cited. The
  agent reports what it found; reconciling the corpus is a human job.
