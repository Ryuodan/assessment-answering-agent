# assessment-answer: map for agents

Answers security and compliance questionnaires (vendor reviews, third-party
risk, privacy attestations) in English and Arabic, from the team's indexed
policies and its own past answers, and writes them back into the customer's
file. Python 3.11, FastAPI, LangChain/LangGraph, Groq, Chroma, SQLite.
What and why: [DESCRIPTION.md](docs/project/DESCRIPTION.md).

This file is a map. Detail lives in the documents it links to.

## Commands

```bash
uv sync --inexact                               # environment from uv.lock: dev tools and every optional extra (D-009)
uv run poe check                                # THE gate: fmt, lint, types, arch, docs, test
uv run poe fmt | lint | types | arch | docs | test   # one task
uv run poe format                               # apply formatting
uv run poe types-baseline                       # drop fixed errors from the mypy baseline
uv run poe gen                                  # regenerate docs/generated/
uv run poe snapshots                            # re-record characterization snapshots; review the diff
uv run poe cov                                  # line coverage per module (measured, not gated)
uv run python -m pytest tests/test_x.py -x      # one test file
uv run python -m uvicorn src.api:app --reload   # the app on :8000
```

Always `python -m <tool>`; never a bare `pytest` or `uvicorn` (D-008).

## Where things are

| Need | Go to |
|---|---|
| What the product is | [docs/project/DESCRIPTION.md](docs/project/DESCRIPTION.md), [overview](docs/project/overview.md) |
| How the code is organised, how a request flows | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Secrets, sensitive data, access model | [SECURITY.md](SECURITY.md) |
| Why things are the way they are | [decisions.md](docs/design/decisions.md); design history in [README.md](README.md) |
| Current work | [docs/plans/active/](docs/plans/README.md), [roadmap](docs/plans/roadmap.md) |
| Known problems | [tech-debt.md](docs/plans/tech-debt.md) |
| The rules and what enforces each | [golden-principles.md](docs/harness/golden-principles.md), [PRINCIPLES.md](docs/harness/PRINCIPLES.md) |
| Plan template and rules | [docs/plans/README.md](docs/plans/README.md) |
| API contract, settings catalogue (generated) | [openapi.json](docs/generated/openapi.json), [settings.md](docs/generated/settings.md) |

## Code map

| Path | What it is |
|---|---|
| `src/api.py`, `src/cli.py` | entry points: HTTP (70 operations, 5 pages) and command line |
| `src/tools.py`, `src/service.py` | operations shared by the UI and the assistant; ingestion, answering, documents |
| `src/agents/` | the chat assistant; the Excel-reading agent |
| `src/graph/` | the answering pipeline: plan, retrieve, rerank, draft, review, finalize |
| `src/knowledge.py`, `chunking.py`, `documents.py`, `embeddings.py` | the knowledge base: conversion, chunks, vectors |
| `src/answer_memory.py`, `memory.py` | approved answers, reused and checked for conflicts |
| `src/forms/` | reading customer questionnaires, writing answers back |
| `src/store.py`, `identity.py`, `batches.py`, `runs.py`, `conversations.py` | SQLite, users and teams, saved work |
| `src/config.py`, `models.py`, `llm.py`, `prompts.py` | settings, data models, the model client, every prompt |
| `src/static/` | the browser pages |
| `harness/` | the checks behind `poe` (not application code) |
| `eval/`, `scripts/` | evaluation; operational scripts (some write the real index) |
| `tests/` | offline suite; `tests/harness/` tests the checks; `tests/characterization/` pins today's behaviour |

## Non-negotiables

1. `uv run poe check` passes before anything is called done. If something
   fails or was skipped, say so, with the output.
2. Humans steer. Product behaviour, trade-offs, and what to keep or drop are
   the user's calls: propose options with a recommendation, then wait.
3. No silent behaviour change. Refactor only behind characterization tests;
   record a suspected bug in tech-debt.md and fix it only with approval.
4. Tests and checks never touch real data or the real `.env`; use temporary
   directories and fixtures. Do not run scripts that write the real Chroma index
   unless asked.
5. Never commit `.env`, `data/`, `chroma_db/` or customer files; never print a
   secret. See [SECURITY.md](SECURITY.md).
6. Configuration only through `src/config.py`; every setting in `.env.example`.
7. Allow-lists and baselines only shrink. A new violation is fixed, not listed.
8. Generated docs come from `uv run poe gen`; never edit them by hand.
9. A lesson that matters goes into the repo (a test, a check, a doc), not
   only into chat.

## Definition of done

- Every acceptance criterion of the plan is met and checked off.
- `uv run poe check` passes.
- Affected docs are updated (ARCHITECTURE, decisions, tech-debt, generated).
- The plan's progress and decision logs are updated in the same commit as the
  work; the commit subject names the plan ("Plan 007: ...").
- A finished plan moves to `docs/plans/completed/` and the roadmap is updated.
