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

This page is the introduction: setup, running, limits. How each part works,
why, and what was measured: [Read more](#read-more).

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
uv sync --inexact                   # create .venv from uv.lock: dev tools and every optional extra
uv pip install <package>            # note: `uv pip`, and there is no `pip` inside .venv
```

Then:

```bash
cp .env.example .env                # then set GROQ_API_KEY
```

The only credential you need is a Groq key. Embeddings come from a
self-hosted BGE-M3 service that speaks the OpenAI embeddings protocol
(`EMBEDDING_BASE_URL`; see `src/embeddings.py`), so the text of every indexed
document, and every search, is sent to that host.

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
uv run python -m uvicorn src.api:app --reload
```

Open <http://127.0.0.1:8000>. Upload guidelines, then submit a new assessment. The document library opens original
PDFs and shows the extracted text used by the agent. Results are editable inline and download
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
uv run python -m src.cli guidelines policies/*.pdf
uv run python -m src.cli answers completed/2024-vendor-review.docx
uv run python -m src.cli answer new-assessment.docx --out filled.json
uv run python -m src.cli answer new-assessment.docx --language ar
uv run python -m src.cli stats
```

### API

Every operation, grouped by path, with what it does:
[docs/generated/api.md](docs/generated/api.md), generated from the app by
`uv run poe gen`. Request and response shapes are in
[openapi.json](docs/generated/openapi.json), and the error codes in
[errors.md](docs/generated/errors.md).

Interactive docs at `/docs`.

---

## Configuration

Everything lives in `.env`; `.env.example` lists every setting. What each
one does, its type and its default: [docs/generated/settings.md](docs/generated/settings.md),
generated from `src/config.py`, the only place settings are read.

---

## Tests

```bash
uv run python -m playwright install chromium  # once per machine: the gate's browser tests need it
uv run poe check                            # the gate: format, lint, types, architecture, docs, the offline suite, the browser tests
uv run python -m pytest -m live_ai          # opt-in: real Groq and embedding calls, costs tokens
uv run python -m scripts.selfcheck          # checks the wiring, not just the units
```

What `check` enforces, and why: [CLAUDE.md](CLAUDE.md) and
[golden-principles.md](docs/harness/golden-principles.md).

---

## Layout

Every module of `src/`, its layer, and what it is (from its docstring):
[docs/generated/layers.md](docs/generated/layers.md). How a request flows
through them: [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Limits

- **Arabic sentences containing Latin runs can arrive out of order.** A
  displaced list marker is repaired at ingestion — `…؟ وما .25` becomes
  `25. …؟ وما`, which is what stabilised question extraction from 27-or-28 to a
  reliable 28. But where an embedded acronym splits an Arabic sentence, the
  segments around it can still be transposed by the converter, and repairing
  that reliably would mean reconciling two independent extractions of the same
  page. Arabic questions containing Latin acronyms are the ones to check.
- **Scanned PDFs are read with OCR, and only through Docling.** A PDF with no
  usable text layer has OCR turned on for it (`DOCLING_OCR_AUTO`, on by
  default); `DOCLING_DO_OCR=true` forces OCR on every document. The local
  fallback has no OCR at all, so without Docling a scanned PDF is rejected with
  an explanatory error rather than silently indexed empty.
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
- **Answers are written back into Excel and Word questionnaires only.** `fill`
  writes the confirmed answers into a copy of an uploaded .xlsx, .xlsm or .docx
  questionnaire. A PDF questionnaire can be answered, and its answers exported
  as JSON, CSV, PDF or Word, but nothing is written into the PDF itself.
- **The corpus is not de-conflicted for you.** Byte-identical uploads are
  skipped, but two policies that disagree — a four-tier classification scheme in
  one and a five-tier scheme in another — are both retrieved and both cited. The
  agent reports what it found; reconciling the corpus is a human job.
- **The answer memory is de-conflicted, and only that far.** Two remembered
  answers that open with opposite verdicts are found and raised for a person;
  two that differ in a number, a period or a scope are not. The sweep compares
  verdicts, because widening it to "these two say different things" would put
  every ordinary rewording in front of a reviewer.
- **One process owns the Chroma directory.** The local client is not built to
  share a persist directory: a second process reading while the first writes
  fails with `Error finding id`. Run one uvicorn worker, and do not run the
  ingest scripts against a directory a live server is writing to.

---

## Read more

The design history that used to follow here, with its measurements, is in
`docs/`, moved as it was written:

| Topic | Document |
| --- | --- |
| How a question becomes an answer: the pipeline, reasoning output, language, embeddings, page numbers, our policy versus the law | [docs/design/answering.md](docs/design/answering.md) |
| Reading a questionnaire, answering it, writing the answers back, and holding back anything unconfirmed | [docs/design/questionnaires.md](docs/design/questionnaires.md) |
| The chat assistant | [docs/design/assistant.md](docs/design/assistant.md) |
| The answer memory | [docs/design/answer-memory.md](docs/design/answer-memory.md) |
| Preferences and skills | [docs/design/preferences.md](docs/design/preferences.md) |
| Signing in, teams, access, and facing a network | [docs/design/access.md](docs/design/access.md) |
| Tracing with LangSmith or Phoenix | [docs/operations/tracing.md](docs/operations/tracing.md) |
| Where the time goes, what a request costs, the storage limit | [docs/operations/time-cost-storage.md](docs/operations/time-cost-storage.md) |
| Evaluation, and what the measurements changed | [docs/measurements/evaluation.md](docs/measurements/evaluation.md) |
| Decisions, architecture, security | [decisions.md](docs/design/decisions.md), [ARCHITECTURE.md](ARCHITECTURE.md), [SECURITY.md](SECURITY.md) |
