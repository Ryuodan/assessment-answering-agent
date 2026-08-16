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

Four things are worth calling out:

**Documents are converted by Docling.** Every upload is posted to the hosted
Docling service (`POST /v1/convert/file`) and comes back as Markdown with tables
intact, which is what keeps a question next to the answer cell that belongs to
it. If Docling is unreachable the loader falls back to local pdfplumber /
python-docx extraction, so an upload never fails purely because a container is
down — set `DOCLING_FALLBACK_LOCAL=false` if you would rather it failed loudly.

**Previous answers are indexed as question/answer pairs, not as prose.** An LLM
pass pulls each answered row out of a completed assessment and stores the
question and answer together. A new question then matches on question wording,
and the answer your organisation actually gave travels with it. This is what
makes the output sound like you rather than like a policy document.

**Every answer is reviewed before you see it.** A second model call checks each
claim against the retrieved sources and can send the question back for one more
retrieval round with a differently-worded query. Answers that stay ungrounded,
or that land below the confidence threshold, come back flagged rather than
silently accepted — the failure mode that matters in compliance work is a
confident wrong answer, not a missing one.

**Not knowing is a valid answer.** When the knowledge base does not cover a
question, the agent says so and scores itself low instead of inventing a
certification you do not hold.

---

## Setup

```bash
conda activate assessment_env      # created during setup, Python 3.11
pip install -e ".[dev]"

cp .env.example .env               # then set GROQ_API_KEY
```

The only credential you need is a Groq key. Embeddings come from
`https://ds.t2.sa/text_embed/`, which needs no key.

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
| `REVIEW_CONFIDENCE_THRESHOLD` | `0.6` | Below this, an answer is flagged for review |
| `TOP_K_PRIOR_ANSWERS` | `5` | Previous answers retrieved per question |

---

## Tests

```bash
pytest                # offline: loaders, routing, fan-out, failure containment
pytest -m live_ai     # opt-in: real Groq and embedding calls, costs tokens
```

---

## Layout

```
src/
  config.py       settings, read once from .env
  models.py       domain models + structured LLM output schemas
  llm.py          Groq factory, with recovery for Groq's tool_use_failed
  embeddings.py   BGE-M3 via the OpenAI embeddings protocol
  documents.py    PDF/DOCX text extraction, tables kept as rows
  docling_client.py  the hosted Docling conversion service
  extraction.py   text -> questions, text -> Q/A pairs
  knowledge.py    Chroma store for guidelines and prior answers
  prompts.py      every prompt
  graph/          LangGraph state, nodes and wiring
  service.py      the orchestration the API and CLI share
  api.py          FastAPI app
  cli.py          command line
  static/         the web interface
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
