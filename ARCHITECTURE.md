# Architecture

How the code in `src/` is layered, why the lines are drawn where they are, and
how a request moves through it. The layers are defined in
`harness/layers.toml` and enforced by `uv run poe arch` (ARCH-LAYER,
ARCH-OWNER); [docs/generated/layers.md](docs/generated/layers.md) lists every
module's layer and is regenerated from that file. Decision: D-012 in
[decisions.md](docs/design/decisions.md).

## Layers

Six layers, lowest first. A module may import modules of its own layer and of
any layer below it, never above, including from inside a function.

| Layer | What it holds | Examples |
|---|---|---|
| 1. foundation | settings, domain types, prompts, pure text rules; reads configuration and nothing else | `config`, `models`, `prompts`, `formatting`, `chunking`, `verification` |
| 2. integrations | everything that talks to something outside the process: the model provider, the embedding host, Docling, SQLite, Chroma, and the customer's PDF, Word and Excel files | `llm`, `embeddings`, `documents`, `store`, `knowledge`, `export_pdf`, `forms/` |
| 3. records | what the system remembers about people and their work | `identity`, `events`, `runs`, `batches`, `conversations`, `answer_memory`, `storage` |
| 4. answering | turning a question into a grounded answer | `graph/`, `extraction`, `relevance`, `rewrite`, `forms/reading.py`, `agents/excel_agent.py` |
| 5. operations | the use cases the web interface, the command line and the chat assistant share | `service`, `tools`, `agents/assistant.py` |
| 6. interfaces | how people and programs reach the system | `api`, `cli` |

Why these lines (Claude's reasoning, recorded as D-012):

- **Integrations sit low, under records and answering**, because both of those
  are built on them: a run is saved in SQLite, an answer is drafted by a model
  over a Chroma search. Keeping every outside system in one layer is what lets
  the layers above be tested with fakes (the suite already does this for the
  vector store and the model).
- **Reading a questionnaire is split by whether a model decides.** The rules
  that read a sheet and write a cell (`forms/`) are deterministic file
  handling, so they are integrations. Choosing a strategy and letting an agent
  explore the workbook (`forms/reading.py`, `agents/excel_agent.py`) is
  answering, as the `agents` package's own docstring argues.
- **Records sit below answering**, not beside it: the answer memory feeds the
  drafter, and the pipeline must never be needed to read what was saved.
- **Operations is the only layer that composes everything**, which is why the
  chat assistant lives there with `tools`: its tools are the same operations
  the web interface calls.

Each IO or framework library is owned by one layer (ARCH-OWNER): FastAPI by
interfaces; the model, embedding, Chroma, SQLite and document libraries by
integrations; LangGraph by answering; LangChain's agent framework by answering
and operations; `pydantic_settings` by `src/config.py` alone. Libraries used
everywhere as plain types (pydantic, LangChain's message and document classes)
are deliberately not owned.

**Exceptions allowed today**, each against a tech-debt item and listed in
[layers.md](docs/generated/layers.md): `knowledge` imports `answer_memory` and
`storage` imports `service`, the upward halves of two cycles (TD-007); `config`
starts the Phoenix tracing libraries (TD-009); `service` renders Word previews
with python-docx itself (TD-019). Not caught by the layers, because both ends
are in one layer: `forms.xlsx` and `forms.llm_layout` import each other
(TD-007).

## Errors

Every error the application raises on purpose is an `AppError` from
`src/errors.py` (D-013): a message written for a person, a stable `code`, and an
HTTP status. Lower layers raise them; only `src/api.py` turns them into a
response, in one handler, always as `{"detail": <message>, "code": <code>}`.
FastAPI's own errors and the catch-all 500 answer in the same shape. The text of
an internal exception goes to the log, never to the response. Every class and
code: [docs/generated/errors.md](docs/generated/errors.md). ARCH-ERROR keeps
new exceptions inside the hierarchy.

## Boundaries

Data from outside becomes a typed, validated model where it arrives: request
bodies, settings, the organisation profile, Docling's responses, model output,
records read back from SQLite. The inventory, with the gaps that remain, is
[docs/design/boundaries.md](docs/design/boundaries.md); ARCH-JSON stops new raw
JSON decoding.

## Logs and request IDs

Application code logs events, not sentences (D-014): `logger = get_logger(__name__)`,
then `logger.info("storage.files_removed", person=email, files=3)`. `src/logs.py`
writes them as text or one JSON object per line (`LOG_FORMAT`), adds the request
ID to every record made during a request, and redacts configured secrets and
key-shaped strings from every line. `src/web.py` assigns the ID (or keeps a
well-formed `X-Request-ID` from a proxy), returns it in the `X-Request-ID`
header and in every error body, and logs each request once as `http.request`
with its route template. To follow a failure: take `request_id` from the error
the person saw and run `python -m src.cli inspect request <id>`, which prints
that request's lines from `SERVER_LOG_PATH`. Modules not yet converted
(TD-028) still log prose, but their lines carry the ID too.

`python -m src.cli doctor` checks an installation without changing it: the
interpreter, the env file, whether the secrets are set (never their values),
storage and the database, and with `--network` one request to each remote
service. Each failure prints a FIX line (`src/diagnostics.py`, plan 010).

## The browser

`src/static/` holds the workbench (`index.html`), the chat, memory and
preferences pages, and the shared answer card (`cards.js`, `cards.css`). They
talk to `src/api.py` over HTTP only.

`tests/browser/` drives them in headless Chromium (Playwright, plan 011): the
app runs in a thread of the test process, so the suite's fixtures (temporary
storage, faked model calls) apply to it, and a page that raises a JavaScript
error fails its test. `uv run poe browser` runs them; the gate includes them.

## Where the routes live

`src/api.py` builds the app and still defines most routes. Routes grouped by
area are moving into `src/routes/` as they change (plan 019, TD-006):
`routes/auth.py` holds the dependencies every route uses (`current_user`,
`current_admin`), and `routes/admin.py` the Access panel's routes. A router is
included where its routes used to be defined, so the routes are registered,
and the OpenAPI contract is ordered, as before. The SQLite schema's
migrations are in `src/migrations.py`, applied by `src/store.py`.

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
