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

**Every answer is reviewed before you see it.** A second model call checks each
claim against the retrieved sources and can send the question back for one more
retrieval round with a differently-worded query. Answers that stay ungrounded,
or that land below the confidence threshold, come back flagged rather than
silently accepted — the failure mode that matters in compliance work is a
confident wrong answer, not a missing one. A mechanical check runs alongside it:
any clause the prose names must appear in the evidence that answer actually
cited, either inside the chunk's clause range or verbatim in its text.

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
as JSON or CSV (UTF-8 with a BOM, so Excel opens Arabic correctly).

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
| `GROQ_CHAT_MODEL` | `minimaxai/minimax-m2.7` | Used for extraction, drafting and review |
| `DOCLING_BASE_URL` | `http://localhost:8092` | Docling host root; clear it to use the local loaders only |
| `DOCLING_DO_OCR` | `false` | Turn on for scanned documents — much slower |
| `DOCLING_FALLBACK_LOCAL` | `true` | Use pdfplumber/python-docx when Docling is unreachable |
| `EXTRACTED_TEXT_DIR` | `./data/extracted` | Cache for document text shown in the interface |
| `GROQ_BASE_URL` | `https://api.me-central-1.groqcloud.com` | ME-Central-1 region; clear it for `api.groq.com` |
| `MAX_ANSWER_ATTEMPTS` | `2` | Draft/review rounds per question |
| `MAX_CONCURRENT_QUESTIONS` | `4` | Raise carefully — Groq rate limits apply |
| `QUERY_EXPANSION` | `true` | Split a multi-part question into one search per part |
| `HYBRID_SEARCH` | `false` | Fuse a BM25 pass with the dense search — see Evaluation |
| `RERANKER_ENABLED` | `false` | Cross-encoder reranking; downloads ~2.3 GB on first use |
| `DOCLING_DO_OCR` | `false` | Force OCR on every document — normally unnecessary |
| `DOCLING_OCR_AUTO` | `true` | Turn OCR on by itself for a PDF with no text layer |
| `MAX_ANSWER_ATTEMPTS` | `3` | Draft/review rounds per question |
| `REVIEW_CONFIDENCE_THRESHOLD` | `0.6` | Below this, an answer is flagged for review |
| `TOP_K_GUIDELINES` | `8` | Guideline chunks retrieved per search query |
| `TOP_K_PRIOR_ANSWERS` | `5` | Previous answers retrieved per question |
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
| minimax-m2.7 | **on** | 70.5% | **63.1%** | 5 |
| gpt-oss-120b | **on** | **74.8%** | 57.0% | 5 |

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

**`k=8` / `attempts=3` is not established.** On the old 49-policy corpus,
raising top-k with query expansion measured +6.5. On this corpus the same
change measured 3.3 points *against*, which is near enough to noise in the
other direction that neither claim should be leaned on. The reranker's size
makes it the lever that matters either way.

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
  verification.py mechanical checks on a drafted answer
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

- **Scanned PDFs need OCR turned on.** Set `DOCLING_DO_OCR=true` to read them;
  with OCR off (the default) a PDF with no text layer is rejected with an
  explanatory error rather than silently indexed empty. The local fallback has
  no OCR at all.
- **Answers are drafts.** Anything flagged `needs_review` — and ideally
  everything else — should be read by a person before the form is submitted.
- **Filled forms are not written back into the original file.** Output is JSON
  or CSV; re-injecting answers into the source PDF/DOCX layout is not implemented.
- **The corpus is not de-conflicted for you.** Byte-identical uploads are
  skipped, but two policies that disagree — a four-tier classification scheme in
  one and a five-tier scheme in another — are both retrieved and both cited. The
  agent reports what it found; reconciling the corpus is a human job.
