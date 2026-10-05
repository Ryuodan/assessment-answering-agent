# Architecture

How the code is organised **today**, as measured in the Phase 0 survey
(2026-10-05), and how a request moves through it. The target layers, and the
`arch` rule that enforces their import directions, are chosen in plan 003;
until then this document describes rather than prescribes. Known violations
are tracked in [tech-debt.md](docs/plans/tech-debt.md) (TD-007, TD-019).

## The parts

| Group | Modules | What they own |
|---|---|---|
| Entry points | `src/api.py`, `src/cli.py`, `scripts/`, `eval/` | HTTP (FastAPI, 70 operations, 5 pages), the command line, operational scripts, evaluation |
| Orchestration | `src/tools.py`, `src/service.py`, `src/agents/assistant.py` | the operations the UI and the chat assistant share (`tools`); ingestion, answering and document access (`service`); the conversational agent and its tools (`assistant`) |
| Answering pipeline | `src/graph/`, `src/prompts.py`, `src/extraction.py`, `src/verification.py`, `src/relevance.py`, `src/rerank.py`, `src/rewrite.py` | LangGraph: plan, retrieve, rerank, draft, review, finalize; question extraction; mechanical checks; rewording |
| Knowledge | `src/knowledge.py`, `src/chunking.py`, `src/documents.py`, `src/docling_client.py`, `src/embeddings.py`, `src/lexical.py`, `src/answer_memory.py`, `src/memory.py` | the Chroma index per team, document conversion and chunking, embeddings, BM25, the answer memory and its conflict sweep |
| Forms | `src/forms/`, `src/agents/excel_agent.py` | reading a customer's .xlsx/.docx questionnaire, deciding where answers go, writing them back into a copy |
| Persistence and identity | `src/store.py`, `src/identity.py`, `src/credentials.py`, `src/events.py`, `src/runs.py`, `src/batches.py`, `src/conversations.py`, `src/preferences.py`, `src/storage.py` | SQLite (schema and migrations in `store`), users, teams, sessions, the event log, saved runs, questionnaires, chats, preferences and skills, per-person storage limits |
| Output | `src/export_pdf.py`, `src/export_docx.py`, `src/formatting.py` | PDF and Word exports (Arabic shaping in PDF), the Markdown subset answers use |
| Foundation | `src/config.py`, `src/models.py`, `src/llm.py`, `src/organisation.py`, `src/progress.py` | settings (the only reader of the environment), domain and LLM-output models, the Groq client factory, organisation profile, run progress |
| Browser | `src/static/` | the workbench (`index.html`), chat, memory and preferences pages, and the shared answer card (`cards.js`, `cards.css`) |

Each IO or framework library has, mostly, one owner: FastAPI in `api`, the
Groq SDK in `llm`, Chroma in `knowledge`, pdfplumber in `documents`, SQLite in
`store`. The exceptions are `python-docx` (four modules) and `langchain_core`
(seven); see TD-019.

## Dependency directions, as they are

Broadly top-down: entry points import orchestration, orchestration imports the
pipeline, knowledge, forms and persistence, and everything imports the
foundation. Where the code goes against that (most of these are imports inside
functions, which hide them from a reader):

- `knowledge` and `answer_memory` import each other.
- `forms.xlsx` and `forms.llm_layout` import each other.
- `forms.reading` imports `agents.excel_agent`, which imports `forms`.
- `storage` imports `service`.
- `rewrite` imports `graph.state` (for `order_evidence`).
- `export_docx` imports `forms.xlsx_package`.
- `agents.assistant` imports `store`, `service` and `tools` directly.

## How a request flows

**Indexing a policy.** `POST /api/knowledge/guidelines` saves the upload
(`service.save_upload`), then `service.ingest` converts it (`documents`, which
calls Docling, or reads Arabic visual-order PDFs locally), chunks it
(`chunking`), embeds and stores it (`knowledge.add_guideline`). A completed
questionnaire indexed as previous answers goes through `extraction` to
question/answer pairs, `knowledge.add_prior_answers`, and
`answer_memory.adopt_file`.

**Answering a questionnaire.** `POST /api/forms` saves the file and calls
`tools.open_form`, which reads it (`forms.reading`, by default the guarded
agent strategy) into a `Batch` of questions with write targets; nothing is
answered yet. `POST /api/forms/{id}/answer` calls `tools.answer`, which calls
`service.answer_questions`, which runs the LangGraph pipeline once per question
(`graph/workflow.py`): plan the searches, retrieve, rerank, draft, review, and
either retry retrieval with a refined query or finalize with confidence and
citations. Answers are saved on the batch (`batches.save_answers`) and an event
is recorded. `POST /api/forms/{id}/fill` writes the ready answers into a copy
of the customer's own file (`forms.xlsx` / `forms.docx`).

**Talking to the assistant.** `POST /api/chat` loads or starts a
`Conversation` and calls `assistant.say`, which runs a tool-calling agent whose
tools are thin wrappers over `tools` (open a form, answer, revise, fill, search,
...), then stores the turn.

**Every request** is authenticated by `api.current_user` (a session cookie, or
open local mode when no users exist); administrator routes add
`api.current_admin`. Unhandled errors become a generic 500 with the detail in
the log.

## External services

Groq (chat model, ME-Central-1 region), a BGE-M3 embedding endpoint, Docling
(document conversion, normally on `localhost:8092`, with a local fallback),
optionally LangSmith or a local Phoenix collector for traces, and a HuggingFace
download for the optional reranker. Data-residency and secret handling are in
[SECURITY.md](SECURITY.md).

## Where state lives

| What | Where | Written by |
|---|---|---|
| users, teams, sessions, events, runs, questionnaires, chats, preferences | SQLite at `DB_PATH` (`data/app.db`) | `store` and the modules above it |
| uploaded and filled files, extracted text | `data/` (per team, per person) | `service`, `tools`, `storage` (which also deletes old files over a person's limit) |
| the policy corpus and the answer-memory vectors | Chroma at `CHROMA_DIR` (`chroma_db/`) | `knowledge`, `answer_memory` |
| evaluation sets and history | `eval/`; the house set and answer memory only sealed in git (`eval/sealed/`, plaintext gitignored) | `eval/`, `scripts/`; `eval/vault.py` seals and unlocks |

All of `data/` and `chroma_db/` is gitignored. Tests redirect every path to a
temporary directory (`tests/conftest.py`).
