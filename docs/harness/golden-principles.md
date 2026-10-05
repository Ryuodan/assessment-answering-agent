# Golden principles

The rules this repository holds itself to, each with what enforces it. "Review"
means no check exists yet: a person or agent must catch it. When a review rule
is broken a second time, turn it into a check or a test and update this table.
The philosophy behind them is in [PRINCIPLES.md](PRINCIPLES.md).

| ID | Rule | Enforced by |
|---|---|---|
| GP-01 | Done means `uv run poe check` passes. Never report work as done with a failing or skipped check. | `check` (all tasks); review for the reporting |
| GP-02 | Python is ruff-formatted. | `fmt` |
| GP-03 | Lint is clean. | `lint` |
| GP-04 | No new type errors; the mypy baseline only shrinks. | `types` (TYPES-NEW, TYPES-FIXED) |
| GP-05 | A module in `src/` has at most 400 lines; allow-listed exceptions only shrink. | `arch` ARCH-SIZE |
| GP-06 | No `print` in `src/` outside `src/cli.py`; use logging. | `arch` ARCH-PRINT |
| GP-07 | Configuration is read only in `src/config.py`. | `arch` ARCH-ENV |
| GP-08 | Every setting is listed in `.env.example`, and nothing else is. | `arch` ARCH-ENVEX |
| GP-09 | No secrets in tracked files. | `arch` ARCH-SECRET; review for logs |
| GP-10 | Every doc is reachable from `CLAUDE.md`, and every link resolves. | `docs` DOCS-LINK, DOCS-ANCHOR, DOCS-ORPHAN |
| GP-11 | Every plan has the required sections and a status matching its folder. | `docs` DOCS-PLAN |
| GP-12 | Generated docs are produced by `uv run poe gen`, never edited by hand, never stale. | `test` (`tests/harness/test_generated.py`) |
| GP-13 | Tests never touch the real database, index, uploads or `.env`. | partly `tests/conftest.py` (`isolated_storage`); review for the rest (TD-011) |
| GP-14 | Behaviour changes only behind tests: refactors are preceded by characterization tests, and a suspected bug is recorded in tech-debt.md, not fixed silently. | partly `test` (`tests/characterization/`: questionnaire reading and filling, the answering pipeline with its prompts, fixture chunking, exports); review for paths not yet pinned |
| GP-15 | Tools run as `python -m <tool>`, never through `.venv` launchers. | `test` (`tests/harness/test_tasks.py`) |
| GP-16 | Customer data never enters git in plaintext. | `arch` ARCH-SEALED for the sealed eval sets; `.gitignore` and review for everything else |
| GP-17 | A commit doing a plan's work names the plan in its subject, and updates the plan's logs in the same commit. | review |
| GP-18 | Records are honest: every number in a doc was measured or given by someone named; Claude's own reasoning is marked as such; rejected attempts are recorded with their numbers. | review |
| GP-19 | Imports go down the layers of `harness/layers.toml`, never up, and every module has a layer. | `arch` ARCH-LAYER |
| GP-20 | An IO or framework library is imported only by the layer that owns it. | `arch` ARCH-OWNER |
