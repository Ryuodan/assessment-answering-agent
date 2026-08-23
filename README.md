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
each question is split into two to four searches, one per thing it asks,
phrased the way a policy would state it and covering both languages for the key
concept. Set `QUERY_EXPANSION=false` to retrieve on the question's own wording
alone.

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
| `GET` | `/api/documents` | List uploaded and bundled trial documents |
| `GET` | `/api/documents/{origin}/{category}/{name}/file` | View the original file |
| `GET` | `/api/documents/{origin}/{category}/{name}/preview` | Preview PDF or DOCX in the browser |
| `GET` | `/api/documents/{origin}/{category}/{name}/text` | View extracted text |
| `POST` | `/api/assessments/answer` | Answer a new assessment |
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

## Configuration

Everything lives in `.env` (see `.env.example`). The values you are most likely
to change:

| Setting | Default | Notes |
| --- | --- | --- |
| `GROQ_CHAT_MODEL` | `openai/gpt-oss-120b` | Used for extraction, drafting and review |
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

Two things worth knowing before reading the numbers. Roughly 1.5 points of
movement on a set this size is noise — the drafter runs at temperature 0.2 and
the judge has its own variance — so differences smaller than that should be
decided on the per-case pattern, not the total. And the reranker adds about 30
seconds per question on CPU, so that pass takes an extra twenty minutes or so.

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
