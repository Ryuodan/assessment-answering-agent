# Plan 009: README reorganised

**Status:** completed

## Goal

The README was 3,327 lines. It held the product's introduction, its setup,
and its whole design history with the measurements behind each decision. Its
reference tables (API, settings, module layout) had drifted from the code.

After this plan:

- The README is an introduction: what the product is, setup, running, tests
  and limits, with a map to the rest.
- The design history lives in topic documents under `docs/`, moved as it was
  written.
- The reference tables are generated from the code, so they cannot drift again.
- The README's known errors are corrected: TD-001 to TD-005 and TD-025.

This is D-006, decided by the user.

## Acceptance criteria

- [x] The README is under 250 lines: the introduction, Setup, Running, Configuration, Tests, Layout, Limits, and a Read more table linking every moved document.
- [x] Every moved section is in exactly one document under `docs/design/`, `docs/operations/` or `docs/measurements/`. A script checks that every non-blank line of the old README is present unchanged. Only heading levels and link targets may differ.
- [x] `uv run poe docs` passes: every link and anchor resolves, including the ones re-pointed from `SECURITY.md`, `docs/project/overview.md` and `CLAUDE.md`, and no document is orphaned.
- [x] The README's API, settings and module tables are replaced by generated documents:
  - `docs/generated/api.md` (new), covering all 70 operations.
  - `docs/generated/settings.md`.
  - A module table per layer in `docs/generated/layers.md` (new).
- [x] TD-001, TD-002, TD-003, TD-004 (except the agent's permission file), TD-005 and TD-025 are resolved in tech-debt.md, each with what changed.
- [x] `uv run poe check` passes.

## Plan

1. Split the README by heading: each moved section runs to the next heading of its level or higher. Re-point the links: re-base relative links on the new folder, and make README anchors follow their heading.
2. Verify the move against the README at HEAD, line by line.
3. Generate `api.md`, and the module table in `layers.md`. Move the README's notes on settings into the comments in `src/config.py` that `settings.md` reads.
4. Correct the README: Setup (TD-001), Running and CLI (`uv run python -m`, D-008), the bundled trial documents (TD-004), Limits (TD-002), and the house set's size (TD-025).
5. Update the documents that pointed into the README. Run the gate and close the plan.

## Progress log

- 2026-10-06: Split done by a one-off script; the README went from 3,327 lines to 212. The new documents:

  | Document | Lines | Moved sections |
  |---|---|---|
  | `docs/design/answering.md` | 551 | How it works; A reasoning model's thinking is not the answer; A tool call in the model's own dialect; Language handling; Our policy, or a law we are subject to; One embedding per query; Page numbers |
  | `docs/design/questionnaires.md` | 580 | Filling in a questionnaire; Nothing unconfirmed reaches the customer's file |
  | `docs/design/assistant.md` | 419 | Talking to it |
  | `docs/design/answer-memory.md` | 178 | The answer memory |
  | `docs/design/preferences.md` | 121 | Preferences and skills |
  | `docs/design/access.md` | 241 | Signing in, and what gets remembered; Facing a network |
  | `docs/operations/tracing.md` | 225 | Tracing |
  | `docs/operations/time-cost-storage.md` | 149 | Where the time goes; Cost of a request; Keeping storage within a limit |
  | `docs/measurements/evaluation.md` | 580 | Evaluation |

  The script changed seven links:
  - one inside the moved text;
  - three in the README's settings table, which was replaced later in this plan;
  - three in `SECURITY.md` and `docs/project/overview.md` that pointed at README anchors.
- 2026-10-06: First run failed: "#### How it works" under Tracing has the same name as the top-level "How it works", and both claimed the same lines. Fixed by matching only headings of level 2 or 3, outside a section already claimed. A second run gave four documents whose only section had the document's own title, so its anchor became `#tracing-1`. In those, the section's heading is now the title.
- 2026-10-06: Verified against `HEAD:README.md`: all 2,779 non-blank lines are present unchanged, ignoring heading level and link targets.
- 2026-10-06: Generated docs added and extended:
  - `docs/generated/api.md` is new. It covers all 70 operations; 53 have a docstring and 17 show FastAPI's derived summary.
  - `layers.md` now has a "Module | What it is" table per layer, from each module's docstring. All 56 modules have one.
  - Notes for 7 settings that had no comment moved into `src/config.py`.

  The README's settings table had drifted: it gave `TOP_K_GUIDELINES` as 5 and `MAX_EVIDENCE_CHUNKS` as 14, where the code has 8 and 38.
- 2026-10-06: README corrections:
  - TD-001: embeddings are a remote service.
  - TD-002: the OCR and write-back limits.
  - TD-004: the trial documents are gone. The empty `demo` extra is removed from `pyproject.toml`, and `uv lock --offline` changed only `provides-extras`.
  - Commands use `uv run python -m` (D-008), and the Tests section runs the gate.
  - TD-025: the evaluation document says 135, re-measured on the unlocked file (135 cases, 5 questionnaires; only counts were read).
- 2026-10-06: `poe gc` reported three stale paths, all inside plan records: the alternative not taken here, and the README's old spellings quoted in plan 008. Plans are records of the tree as it was, so `gc` no longer reads them for stale paths.
- 2026-10-06: `uv run poe check` passes (1,783 tests). Plan complete; milestone M4 done.

## Decision log

- 2026-10-06: Topic documents follow the parts of the product (answering, questionnaires, assistant, memory, preferences, access), plus operations and measurements. The alternative was one `docs/design/history.md`. It would have moved the problem rather than solved it: a 2,800-line file that nobody can navigate. (Claude)
- 2026-10-06: Moved text is not edited, apart from one correction (TD-025). The design notes are a record: rewriting them while moving them would make the move impossible to verify and would lose who measured what. Their own staleness is a separate job. (Claude)
- 2026-10-06: The README's API, settings and Layout tables were replaced by generated documents, not moved. They were references that had already drifted (46 of 70 operations; wrong defaults). Their hand-written notes were kept where a generator reads them: setting comments in `src/config.py`, and route and module docstrings. (Claude)
- 2026-10-06: `.claude/settings.json` was left as it is (TD-004). It is the agent's permission list; an agent should not edit its own permissions, even to remove entries. (Claude)
