# Plan 017: The user's decisions on TD-020, TD-033 and TD-034

**Status:** completed

## Goal

On 2026-10-06 the user decided three open questions:

- remove the commented-out local embeddings (TD-020);
- replace the drafting prompt's style example, which was a team answer to a benchmark question (TD-033);
- give embedding requests a large timeout, tested and set from measurement, because adding a large file to the knowledge base can take a long time (TD-034).

This plan carries them out and records how each was checked.

## Acceptance criteria

- [x] `src/embeddings.py` has no commented-out code. Nothing refers to it any more, including the README and the `langchain_huggingface` ownership entry.
- [x] The prompt's example is a sentence in no benchmark text; `KNOWN` is empty, and `poe eval-contamination` finds 0 leaks. The characterization snapshots change only in that sentence.
- [x] `EMBEDDING_TIMEOUT` exists, is documented in `.env.example` and the generated settings, and reaches both the sync and async clients. A test shows that a host that never answers fails the request, where the old client waited for ever. The default comes from measured latencies.
- [x] `uv run poe check` passes.

## Plan

1. TD-020: delete the block, and update its references.
2. TD-033: choose an invented sentence, check it against every benchmark text, replace it, empty `KNOWN`, and re-record the snapshots and review the diff.
3. TD-034: check the client's real timeout. Measure the host's latency per request with synthetic text. Add the setting and the tests, and check the test against the old code.

## Progress log

- 2026-10-06: TD-020: 21 commented lines deleted from `src/embeddings.py`. Also removed: the README sentence that offered them as an offline alternative, and `langchain_huggingface` from `harness/layers.toml`, which nothing imports. `sentence-transformers` stays, because the reranker uses it.
- 2026-10-06: TD-033: the example is now "Removable media is blocked on company laptops". Before the change, it and two of its fragments were checked on normalised text against all 135 house-set pairs, the 698 answer-memory pairs and the 42 golden-set questions: 0 matches. `KNOWN` is now empty. `poe eval-contamination`: 135 cases, 0 leaks. `poe snapshots` changed 3 lines in 2 pipeline snapshots, each the old example sentence becoming the new one. Effect on answers: not measured (a paid dev run; see the decision log).
- 2026-10-06: TD-034: the built client's timeout is `None` on both the sync and async clients, so it waits for ever. TD-034's first account (OpenAI defaults, up to 30 minutes) was wrong, and is corrected in place. Latency was measured straight against the host, one request at a time, with generated English and Arabic text and nothing from customers:
  - a one-line query took 0.26 to 34 s;
  - a 64-chunk batch of 1,200-character chunks took 37 to 70 s.

  An earlier attempt with the application's own client sat for over 10 minutes with no reply, and was stopped.
- 2026-10-06: `EMBEDDING_TIMEOUT` (default 300 s) was added to `src/config.py` and `.env.example`, and is passed to the client. `tests/test_embeddings_client.py` has 3 tests: the timeout reaches both clients, the default, and a local server that accepts and never replies. The last fails in 2.9 s with a 0.5 s timeout after three connection attempts. On the old code the same test was still waiting at 40 s and was killed.
- 2026-10-06: The first type check failed: mypy does not accept `timeout`, which is an alias, so the client is now given `request_timeout`, the field's own name; the tests passed both ways. `uv run poe check` passes (1,812 tests, 6 browser tests). Plan complete.

## Decision log

- 2026-10-06: 300 s per request, about four times the slowest batch measured (70 s). The user asked for a large limit, so that slow ingestion is not cut off. The cost is that a stalled host now holds a request for about 15 minutes (three attempts) before failing it, where before it held it for ever. Answering's query embeddings share the setting; the interactive search keeps its own 10 s bound. (Claude)
- 2026-10-06: The new prompt example's effect on answers was not measured. That needs a dev-split run compared with the plan 014 runs (`scripts/compare_runs.py --noise eval/results/noise_baseline.json`). It is a paid run the user has not asked for, and a one-sentence change to an example is expected to be within the noise measured in plan 014. (Claude)
