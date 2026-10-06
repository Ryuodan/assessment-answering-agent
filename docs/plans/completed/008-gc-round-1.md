# Plan 008: Cleanup round 1

**Status:** completed

## Goal

The first garbage-collection round, after milestone M3 (60 commits in the
repository). It does two things. First, it gives the round tools that later
rounds can reuse: `poe gc` lists the candidates, `poe grades` grades each
layer, and `poe arch-lower` lowers the size ceilings. Second, it acts on what
those tools find. Whatever the round leaves alone is either recorded with its
reason or handed to the user. Rounds that use the same tools and thresholds
can be compared.

## Acceptance criteria

- [x] `uv run poe gc` lists the candidates of seven kinds (unused, test-only, duplicate, suppression without a reason, oversize, stale doc path, TODO), one per line in the form `KIND path:line: what`.
- [x] Each candidate is either acted on or recorded here with a reason. A choice that belongs to the user goes into tech-debt.md as a question.
- [x] No `noqa` or `type: ignore` remains without a reason beside it.
- [x] Every size ceiling in the allow-list equals its module's current length. `poe arch-lower` does this, and a test shows that it never raises a ceiling.
- [x] `uv run poe grades` grades each layer on coverage, size, suppressions, duplication and docstrings. The first round's grades, with each layer's gaps written out, are in [grades.md](../../quality/grades.md).
- [x] `uv run poe check` passes.

## Plan

1. Write `harness/gc.py` and run it.
2. Clear the suppressions without a reason: one per-file ignore for E402 with its reason, and a reason on every other suppression.
3. Delete the definitions that nothing uses. Remove the duplicated blocks where a helper does not grow an oversized module.
4. Add `--lower-ceilings` to `harness/arch.py` with a test, then lower the ceilings.
5. Write `harness/grades.py`, grade round 1 and record the gaps.
6. Regenerate docs, run the gate, and close the plan.

## Progress log

- 2026-10-06: `harness/gc.py` written; `poe gc` added (not a gate). First run: 7 UNUSED, 4 TEST-ONLY, 6 DUPLICATE, 58 SUPPRESS, 18 OVERSIZE, 3 STALE-PATH, 0 TODO.
- 2026-10-06: Suppressions cleared, 58 → 0:
  - 48 `# noqa: E402` comments in `scripts/` and `tests/conftest.py` were replaced by a per-file ignore in `pyproject.toml`, with its reason: scripts put the repository root on `sys.path` before importing `src`, and the test configuration sets environment variables before `src.config` is imported.
  - The other 10 now carry a reason.
- 2026-10-06: Six unused definitions deleted: `batches.detail_of`, `forms/docx._blocks`, `forms/reading.by_sheet`, `forms/xlsx._has_arabic`, `identity.team_members`, `models.QueryPlan`. `ruff` then removed two imports that were left unused (`Table`, `Part`). This resolves the rest of TD-010.
- 2026-10-06: Four duplicated blocks became helpers, with behaviour unchanged:
  - `api._save_assessment`, the upload preamble shared by two routes.
  - `api._export_options`, the export options and the "nothing to export" refusal shared by two routes. `docs/generated/errors.md` now names it as where `nothing_to_export` is raised.
  - `chunking.piece`, one table piece.
  - `tools._working_copy`, the answer to change.

  The covering tests passed (322).
- 2026-10-06: Stale paths: two in the README were fixed (`src/tools` → `src/tools.py`, `src/rewrite` → `src/rewrite.py`). The third was an abbreviated path (`...`), which `gc` now skips.
- 2026-10-06: `harness/arch.py --lower-ceilings` (`poe arch-lower`) added, with a test that lowers a ceiling that shrank and leaves alone one that grew. Lowered 7 ceilings: `api.py` 2045 → 2036, `tools.py` → 1487, `chunking.py` → 1094, `forms/xlsx.py` → 935, `identity.py` → 615, `forms/docx.py` → 492, `models.py` 430 → 421. `arch: ok`.
- 2026-10-06: `harness/grades.py` (`poe grades`) added. `poe cov` also writes `.coverage.json` (gitignored) for it. Round 1 graded in [grades.md](../../quality/grades.md).
- 2026-10-06: The reason written after `type: ignore[assignment]` in `llm.py` was not in mypy's `# type: ignore[code]  # reason` form, so mypy rejected the comment; rewritten. That also fixed one baseline error (285 → 284 in `harness/mypy-baseline.txt`).
- 2026-10-06: Left after the round: 2 DUPLICATE (see the decision log), 18 OVERSIZE (each on the allow-list at its current length; splitting them is work for the plans that touch them), 4 TEST-ONLY (kept), and 1 UNUSED (`documents.load_url_text`, a question for the user as TD-032).

## Decision log

- 2026-10-06: `forms/xlsx.py:478` and `forms/xlsx_package.py:298` share the same 8 lines that copy a merged range. They are left as they are. A shared helper would have to live in one of the two modules, and both are over the size limit. Fixing it belongs with splitting `xlsx_package.py`. (Claude)
- 2026-10-06: `store.py:216` and `store.py:325` are two schema migrations with the same steps. This is intended, since a migration that has shipped is never edited. (Claude)
- 2026-10-06: Kept the test-only definitions:
  - `answer_memory.forget_sync` and `store.reset_connection` are test hooks.
  - `identity.is_allowed` and `store.database_size` are kept because tests pin their semantics, which the app relies on through other paths.

  (Claude)
- 2026-10-06: `documents.load_url_text`, with `docling_client.convert_url`, is the only way to ingest a document from a URL, and nothing calls it. Whether the product should keep URL ingestion is the user's call (non-negotiable 2), so it is TD-032 and has not been deleted. (Claude)
- 2026-10-06: Grades use fixed thresholds, written in `harness/grades.py`. Rounds are only comparable if the thresholds stay the same. Changing them needs a decision and a re-grade of the earlier rounds. (Claude)
- 2026-10-06: `uv run poe check` passes. Plan complete.
