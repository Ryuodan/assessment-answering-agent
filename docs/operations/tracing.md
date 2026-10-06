# Tracing

Recording what a run did: LangSmith, and Phoenix on this machine.

Moved from the README (plan 009); the text is as it was written there, with links re-pointed.

Every LLM call, retrieval and graph step can be recorded as a trace, to either
of two places: **Phoenix on this machine**, or **LangSmith in the cloud**. Both
are off by default. If you are here to watch the thing work, skip to
[Phoenix](#the-same-traces-without-the-border-crossing-phoenix) — it is local,
and the section below is the reason that matters.

LangSmith is **off by default and should stay off until the data question is
settled**, because switching it on is a decision about data residency rather
than about observability.

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

## The same traces without the border crossing: Phoenix

[Arize Phoenix](https://docs.arize.com/phoenix) is an OpenTelemetry collector
with a UI that understands LLM spans, and it runs wherever you run it. That
single fact answers the objection above: the traces never leave the machine, so
there is no region to choose and no transfer to justify. It is the sensible
default for developing against this corpus, and LangSmith is the one to think
twice about.

Two pieces, deliberately separate: the **collector** (Phoenix itself, a server
with its own database and UI) and the **exporter** (two packages inside this
app that send it spans). The collector does not belong in the dependency set of
the application it watches, and it could not live there anyway — **the Phoenix
server needs Python 3.12 or newer**, and this application runs on 3.11. `uv`
handles that without you managing a second environment by hand.

### Once per machine

1. **Install the exporter into this app's `.venv`.** `uv pip`, not `pip` — the
   `.venv` is built by uv and has no pip of its own:

   ```bash
   uv pip install -e ".[phoenix]"
   ```

2. **Install the collector as a standalone tool, on Python 3.12.** uv downloads
   the interpreter if you do not have one, keeps Phoenix in an isolated
   environment of its own, and puts a `phoenix` command on your `PATH`:

   ```bash
   uv tool install --python 3.12 arize-phoenix
   ```

   (No install at all: `uvx --python 3.12 --from arize-phoenix phoenix serve`
   does the same each time from uv's cache. With Docker:
   `docker run -p 6006:6006 arizephoenix/phoenix:latest`.)

3. **Switch the exporter on** in `.env`:

   ```bash
   PHOENIX_TRACING=true
   PHOENIX_ENDPOINT=http://localhost:6006/v1/traces
   PHOENIX_PROJECT=assessment-answer
   ```

### Every time

1. **Start Phoenix first**, in its own terminal, and leave it running:

   ```bash
   phoenix serve
   ```

   It is ready when it prints `Phoenix is up and running` — open
   <http://localhost:6006>.

2. **Start the app** in a second terminal, from this directory, the usual way:

   ```bash
   .venv/Scripts/python.exe -m uvicorn src.api:app --reload
   ```

   Look for this line in its log — if it is not there, nothing is being traced
   (see *When it does not work* below):

   ```
   INFO  src.config: Phoenix tracing is ON — project 'assessment-answer' to http://localhost:6006/v1/traces. ...
   ```

3. **Use the app** as normal, then go to <http://localhost:6006> →
   **assessment-answer**. Spans are sent in batches, so a trace can take a few
   seconds to appear after the answer does.

   - **Traces** — one per question (`answer[12]`) and one per chat turn
     (`assistant[<conversation>]`). Click one for the span tree: `plan →
     retrieve → rerank → draft → review → finalize`, every `ChatGroq` call with
     its prompt, output and token counts.
   - **Sessions** — a whole questionnaire run, or a whole conversation, grouped.
   - The CLI, `scripts/` and the eval harness are traced too, with no extra
     step. An eval run is thousands of spans; that is fine, but it is why a
     project name per experiment (`PHOENIX_PROJECT=eval-precedence`) is worth
     setting.

4. **Stop** with Ctrl+C in each terminal. Set `PHOENIX_TRACING=false` when you
   are done — the app does not need Phoenix to run, it just warns while it
   cannot reach one.

### When it does not work

| What you see | Why, and what to do |
|---|---|
| No `Phoenix tracing is ON` line | `.env` still says `false`, or the app is not reading this directory's `.env` — start it from this directory. |
| `PHOENIX_TRACING is on but the tracing packages are not installed` | Step 1 of *Once per machine*, into this `.venv`. |
| `Transient error … Failed to establish a new connection … while exporting span batch`, then `Failed to export span batch due to timeout, max retries or shutdown` | Phoenix is not running, or not on the port in `PHOENIX_ENDPOINT`. Start it; the warnings stop on their own. Those spans are lost, the answers are not. |
| `phoenix serve` fails with `mutable default <class 'mappingproxy'>` | Phoenix was installed on Python 3.11. `uv tool install --python 3.12 --reinstall arize-phoenix`. |
| Port 6006 already in use | Set `PHOENIX_PORT=6007` before `phoenix serve` (`$env:PHOENIX_PORT=6007` in PowerShell), and change `PHOENIX_ENDPOINT` to match. |
| The app runs but no traces appear from the test suite | Correct — the suite never traces, whatever `.env` says. |
| `phoenix: command not found` | uv's tool directory is not on `PATH`: run `uv tool update-shell` and open a new terminal. |

### Clearing it out

Phoenix keeps everything under `PHOENIX_WORKING_DIR` — `%USERPROFILE%\.phoenix`
by default on Windows (`~/.phoenix` elsewhere) — in a SQLite file. Delete a
project in the UI, or stop Phoenix and delete that directory, to remove every
trace. `uv tool uninstall arize-phoenix` removes the collector.

### How it works

`config.start_phoenix_tracing()` is the bridge, and it is a different mechanism
from the LangSmith one rather than a second destination for it. LangSmith is
read out of the environment by LangChain itself, so switching it on is a matter
of publishing variables; Phoenix is OpenTelemetry, and something in the process
has to build a tracer provider and patch LangChain to emit spans into it. Like
the other bridge it runs at import of `src.config`, so the API, the CLI, the
eval harness and the scripts are all covered without each remembering to ask.

The imports live inside the function and a missing package is a warning, not a
crash: `PHOENIX_TRACING=true` without the extra installed is a plausible
mistake, and an application that refuses to start because its *observability* is
missing has the priority backwards. Same for the collector being down — the
exporter drops the spans in a background thread and answering carries on.

**What you get.** Everything the LangSmith naming above buys, because it is the
same metadata: a two-question run produced 38 spans, root spans named
`answer[1]` and `answer[2]`, the graph steps as their own spans (`plan`,
`retrieve`, `rerank`, `draft`, `review`, `finalize`, `route_after_review`), six
`ChatGroq` LLM spans carrying 35,221 tokens between them. The chat agent traces
too, with its tool calls as `tool` spans — `answer_directly`, `open_questionnaire`
and the rest.

One addition earns its keep here. `trace_config` also puts the batch id in
`metadata["session_id"]`, which is the name the OpenInference convention
reserves for it, so Phoenix groups the hundred and eighty-three questions of one
questionnaire into **one session** instead of a hundred and eighty-three
unrelated traces. LangSmith reads `run_id` and ignores the other; Phoenix reads
`session_id` and ignores the other; both are cheap.

Retrieval shows up as the `retrieve` step with its evidence in the span, not as
OpenInference `retriever` spans with one document each — the store is called
directly rather than through a LangChain `Retriever`, so there is nothing for
the instrumentation to hook. Phoenix's document-level relevance evals want the
latter; if that becomes worth having, the place to emit them is
`KnowledgeStore.search`.

> **Local is not the same as harmless.** A trace holds the prompt, and the
> prompt holds the policy text and the customer's questionnaire. Phoenix keeps
> them in its own store — `PHOENIX_WORKING_DIR`, a SQLite file by default — with
> no sign-in in front of it and none of this application's team scoping. Treat
> that directory as another copy of the corpus: keep it off shared machines,
> and delete it when you are done debugging.
