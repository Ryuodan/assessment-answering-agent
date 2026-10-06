# Roadmap

Milestones in the order they are planned. Each names the plans that serve it;
a plan number without a file has not been written yet.

| Milestone | What it gives us | Plans | Status |
|---|---|---|---|
| M1 Foundations | `uv run poe check`, the docs layout and its check, `arch` v0, generated docs, characterization tests | [001](completed/001-foundations.md) | done 2026-10-05 |
| M2 Confidential eval data sealed | `eval/house_set.json` and `eval/answer_memory.json` encrypted in the repo, usable after an unlock with the key from `.env` | [002](completed/002-seal-eval-data.md) | done 2026-10-05 |
| M3 Architecture and invariants | layers chosen for this domain, import rules and library ownership in `arch`, one error hierarchy, structured logs, validated boundaries | [003](completed/003-layers.md), [004](completed/004-error-hierarchy.md), [005](completed/005-structured-logging.md), [006](completed/006-test-isolation.md), [007](completed/007-validated-boundaries.md) | done 2026-10-06 |
| M4 README reorganised | the README's design history moved into `docs/` (decisions, design notes, measurements) and the README cut to an introduction | [009](completed/009-readme-reorganised.md) | done 2026-10-06 |
| M5 Legible system | request IDs in logs and errors, diagnostic CLI commands, browser tests for the main flows | not numbered | planned |
| M6 Trustworthy evaluation | dev and held-out splits, noise measured first, contamination test, item-by-item comparison (TD-014) | not numbered | planned |

A garbage-collection round, as its own plan, follows each milestone or about
40 commits, whichever comes first.

| Cleanup round | After | Plan | Status |
|---|---|---|---|
| 1 | M3 | [008](completed/008-gc-round-1.md) | done 2026-10-06 |
