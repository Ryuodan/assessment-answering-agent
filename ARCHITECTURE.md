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
| 1. foundation | settings, domain types, prompts, pure text rules; reads configuration and nothing else | `config`, `models`, `schemas`, `prompts`, `formatting`, `chunking`, `verification` |
| 2. integrations | everything that talks to something outside the process: the model provider, the embedding host, Docling, SQLite, Chroma, and the customer's PDF, Word and Excel files | `llm`, `embeddings`, `documents`, `store`, `knowledge`, `export_pdf`, `forms/` |
| 3. records | what the system remembers about people and their work | `identity`, `events`, `runs`, `batches`, `conversations`, `answer_memory`, `storage` |
| 4. answering | turning a question into a grounded answer | `graph/`, `extraction`, `relevance`, `rewrite`, `forms/reading.py`, `agents/excel_agent.py` |
| 5. operations | the use cases the web interface, the command line and the chat assistant share | `service`, `search`, `selection`, `tools`, `fill_audit`, `agents/assistant.py` |
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

`python -m src.cli inspect fills [--team T]` reads the event log and the answers
as they are today, and changes nothing (`src/fill_audit.py`, plan 029). It lists
the fills that wrote answers the review gate holds back: before plan 029 every
Workbench fill did (TD-052), and since then a fill records it. An answer held
today and unchanged since the fill was certainly written; one saved after the
fill is reported as unknown. It also lists answers whose approval was withdrawn
before plan 029 and that the gate still lets through (TD-053).

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
`current_admin`), and `routes/admin.py` the Access panel's routes.
`routes/forms.py` holds filling a questionnaire, the first of its routes to
move (plan 029); the rest follow with plan 029's Stage 1. A router is
included where its routes used to be defined, so the routes are registered,
and the OpenAPI contract is ordered, as before. The SQLite schema's
migrations are in `src/migrations.py`, applied by `src/store.py`.

## Products and roles

A team's products (plan 020, milestone M7) are rows in `products`, managed
by `src/products.py` and served by `src/routes/products.py` and the
`/products` page. Each has a knowledge base and an answer memory of its
own beside the team's shared ones (plans 021 to 023, design in
[plan 018](docs/plans/completed/018-products.md)). Roles are in `src/roles.py`:
`manages_products` says who may change a team's products (its leads, and any
administrator). `SEED_PRODUCTS` adds the first products once, recorded in the
`seeds` table.

A product's knowledge base is a Chroma collection of its own
(`vector_names.collection_for(team, product)`), beside the team's shared one,
which is untouched. `src/scoped_knowledge.py` chooses between them:
`own_store` is where an upload or a removal goes, and `store_for` is what
answering for a scope searches. For General that is the shared store itself;
for a product it is a `ScopedStore`, which embeds the query once and lists
the product's hits before the shared ones. The knowledge routes
(`src/routes/knowledge.py`) take an optional `product`. A product's files are
kept in its own folder (`Settings.product_upload_dir`, `src/uploads.py`).
Removing a product document deletes its file; a shared document's file stays.

A product's answer memory is the team's `memory_entries` rows that carry its
id (`product_id`, `''` for the shared memory), indexed in that product's
collection. The disagreement sweep (`src/memory_sweep.py`) searches only an
entry's own memory, so supersession and conflicts never cross memories.
`answer_memory.move` moves an entry between memories. The memory routes
(`src/routes/memory.py`) read and teach one memory at a time, Shared by
default.

A questionnaire and a chat are each for a product or General
(`form_batches.product_id`, `conversations.product_id`; `''` is General).
`products.chosen` checks that a product asked for is the caller's team's.

The product is fixed when the questionnaire is opened or the chat starts
(D-018). `products.refuse_change` refuses any other product with 409
`product_locked`.

- **Answering.** `tools.open_form` takes the product. The questionnaire's
  product goes through `service.answer_questions`, or the whole-document flow, into the
  graph's state. There `retrieve` asks `scoped_knowledge.store_for` for it.
- **The drafter.** Evidence from the product's knowledge base carries its
  `product_id`. When any does, `prompts.format_sources_block` marks it FOR THIS
  PRODUCT and says it takes precedence over the shared material. A General
  questionnaire's prompt is unchanged.
- **Approval.** A hand-written answer is remembered in the questionnaire's
  memory.
- **The chat.** A chat's product is chosen with its first message:
  - an upload in the chat is opened for it;
  - `search_policies` searches the product's knowledge base beside the shared
    one and marks the product's own clauses FOR THIS PRODUCT;
  - `answer_directly` drafts with it;
  - the prompt names the product (`agents/assistant_prompt.py`).

  A turn's searches and their budget are in `agents/assistant_turn.py`. What a
  stopped turn says is in `agents/assistant_stopped.py`, and the quotation check
  is in `agents/assistant_quotes.py`.
- **Deletion** (D-019). Deleting a product, behind a counted warning
  (`GET /api/products/{id}/deletion`), removes:
  - its collection, its folder, and its files from before the folder existed;
  - its memory entries.

  Its questionnaires and chats keep its id and become read-only. The name they
  are labelled with is kept in `deleted_products`. `products.refuse_deleted`
  and the store guard in `scoped_knowledge` refuse writes with 409
  `product_deleted`.
- **The pages** (plan 024). The choice is made in two places:
  - a coloured chip beside the chat box (`chat.html`), which can be changed
    until the first message;
  - a Product selector at the top of the workbench's questionnaire panel
    (`index.html`), fixed while a questionnaire is open. Close questionnaire
    frees it.

  `Cards.productBadge` (`cards.js`) puts a product's name, in its colour, on
  the chats and questionnaires in the lists, and on an answer's sources that
  came from the product's own knowledge base.

## How a request flows

**Indexing a policy.** `POST /api/knowledge/guidelines` saves the upload
(`service.save_upload`), then `service.ingest` converts it (`documents`, which
calls Docling, or reads Arabic visual-order PDFs locally), chunks it
(`chunking`), embeds and stores it (`knowledge.add_guideline`). A completed
questionnaire indexed as previous answers goes through `extraction` to
question/answer pairs, `knowledge.add_prior_answers`, and
`answer_memory.adopt_file`.

**Answering a questionnaire.** `POST /api/forms` saves the file and calls
`tools.open_form`, for a `product` or General. That reads it (`forms.reading`, by default the guarded
agent strategy) into a `Batch` of questions with write targets; nothing is
answered yet. `POST /api/forms/{id}/answer` calls `tools.answer`, which calls
`service.answer_questions`, which runs the LangGraph pipeline once per question
(`graph/workflow.py`): plan the searches, retrieve, rerank, draft, review, and
either retry retrieval with a refined query or finalize with confidence and
citations. Answers are saved on the batch (`batches.save_answers`) and an event
is recorded. `POST /api/forms/{id}/fill` writes the ready answers into a copy
of the customer's own file (`forms.xlsx` / `forms.docx`). An answer is ready
when `selection.ready_to_write` says so: a person confirmed it, or it is neither
flagged nor under `REVIEW_CONFIDENCE_THRESHOLD`. The rest are held back and
listed with their reasons, and written only when the request says
`include_unreviewed` (the Workbench's "Write them in anyway"). The Workbench
also names them (`unreviewed_ids`): the held answers the person was shown, so an
answer held since stays out; the response says how many went in
(`written_anyway`). The `file_filled` event records how many the gate held
(`held_back`), whether they were written anyway (`include_unreviewed`), and
which (`written_anyway`); events from before plan 029 have neither key.

**Talking to the assistant.** `POST /api/chat` (`src/routes/chat.py`) loads a
`Conversation`, or starts one for the `product` sent, and calls
`assistant.say`. That runs a tool-calling agent whose
tools are thin wrappers over `tools` (open a form, answer, revise, fill, search,
...), then stores the turn.

**Every request** is authenticated by `routes.auth.current_user` (a session cookie, or
open local mode when no users exist); administrator routes add
`routes.auth.current_admin`. Unhandled errors become a generic 500 with the detail in
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
