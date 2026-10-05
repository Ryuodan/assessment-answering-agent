# Overview for newcomers

Read [DESCRIPTION.md](DESCRIPTION.md) first for what the product is for. This
page gives the vocabulary, the main flows, and where to look next.

## Vocabulary

| Term | Meaning | In the code |
|---|---|---|
| knowledge base | the team's indexed policies and standards, chunked and embedded | `src/knowledge.py`, Chroma, one collection per team |
| answer memory | answers people wrote or approved, reused for similar questions | `src/answer_memory.py`, `src/memory.py` |
| questionnaire / batch | an uploaded customer file, the questions read from it, and their answers | `src/batches.py`, `src/forms/` |
| write target | where in the customer's file an answer or a status goes | `src/forms/model.py` |
| run | one answering pass over a list of questions, saved with its evidence | `src/runs.py` |
| evidence / citation | the chunks an answer was drafted from, and the clauses it names | `src/models.py`, `src/graph/` |
| conversation | a chat with the assistant | `src/conversations.py`, `src/agents/assistant.py` |
| team / person | teams share a knowledge base and memory; a person owns their questionnaires, runs and chats | `src/identity.py` |
| skill / preference | how a person wants answers worded, applied as rewording | `src/preferences.py`, `src/rewrite.py` |

## The main flows

1. **Index policies** in the workbench; they become the team's knowledge base.
2. **Open a questionnaire**: the file is read into questions and write targets;
   correct the reading if needed.
3. **Answer**: each question goes through the pipeline (plan searches,
   retrieve, rerank, draft, review, finalize) and comes back with confidence,
   citations and flags.
4. **Review and approve**: approved answers enter the answer memory.
5. **Fill**: the ready answers are written into a copy of the customer's file.

[ARCHITECTURE.md](../../ARCHITECTURE.md) traces these through the modules.

## Running it

```bash
uv sync --inexact                               # the environment, from uv.lock
cp .env.example .env                            # then set GROQ_API_KEY
uv run python -m uvicorn src.api:app --reload   # http://127.0.0.1:8000
uv run python -m scripts.dev_server             # open mode over a scratch database
uv run poe check                                # the gate
```

Always start tools as `python -m <tool>`: see decision D-008 in
[decisions.md](../design/decisions.md).

## How quality is measured

`eval/` scores answers two ways: against facts a correct answer must state
(`eval/golden_set.json`) and against what the team actually wrote (the house
set, sealed in git: `uv run poe eval-unlock` first, see
[SECURITY.md](../../SECURITY.md#sealed-eval-data)). The README's [Evaluation](../../README.md#evaluation) section has the
method and the history of measurements; TD-014 in
[tech-debt.md](../plans/tech-debt.md) notes what the method still lacks.

## Where the history is

The README is the project's design history: why each part works the way it
does, with the measurements that decided it. It is being reorganised into
`docs/` (roadmap milestone M4). Until then, read it by section rather than
end to end; its headings are a good index.
