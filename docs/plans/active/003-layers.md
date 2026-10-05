# Plan 003: Layers and their enforcement

**Status:** active

## Goal

Every module in `src/` belongs to one named layer, chosen for what this system
does, and the `arch` check enforces two things about them: a module imports
only from its own layer or the layers below it, and each IO or framework
library is imported only by the layer that owns it. Today the dependency
directions exist only as a description in ARCHITECTURE.md, and the survey
found cycles and upward imports hidden inside functions (TD-007) and libraries
spread across layers (TD-019). With the rule in place a new upward import or a
library used from the wrong place fails `check` with a FIX line; the existing
ones are allow-listed against their TD items and can only be removed. This is
the first block of milestone M3; the error hierarchy, structured logging and
validated boundaries are later plans.

## Acceptance criteria

- [ ] `harness/layers.toml` defines the layers in order and assigns every module in `src/` to exactly one; a module assigned to none fails (ARCH-LAYER, with the FIX naming the file to edit).
- [ ] ARCH-LAYER fails when a module imports a module of a higher layer, whether at module level or inside a function, and when anything in `src/` imports `eval`, `scripts`, `harness` or `tests`.
- [ ] ARCH-OWNER fails when a module imports an owned library (FastAPI, Groq, Chroma, SQLite, the document libraries, LangGraph, ...) from outside the layers that own it.
- [ ] Every existing violation is on the allow-list with a TD item; an entry that no longer matches a violation fails (ARCH-ALLOW).
- [ ] Each rule has a test with a failing example.
- [ ] `docs/generated/layers.md` is generated from `harness/layers.toml` (layers, their modules, the libraries they own) and a test fails when it is stale; ARCHITECTURE.md explains the layers and why they are drawn there, and links to it.
- [ ] The choice of layers is recorded as a decision; `uv run poe check` passes.

## Plan

1. This plan; roadmap.
2. `harness/layers.toml` and the import scanner; measure the violations of the proposed layering before committing to it.
3. ARCH-LAYER and ARCH-OWNER in `harness/arch.py`, allow-list entries, rule tests.
4. `docs/generated/layers.md`, ARCHITECTURE.md, decision, TD updates; `check`; close.

## Progress log

- 2026-10-05: Plan written; the user asked to proceed with plan 003 without reviewing its text first.
- 2026-10-05: Before this plan's work, TD-024 was measured and fixed as the user asked (commit `2334e02`); not part of this plan.
- 2026-10-05: Step 2. `harness/layers.toml` (six layers, 22 owned libraries) and `harness/layers.py`. Measured against the code before adopting it: 2 upward imports (`knowledge` -> `answer_memory`, `storage` -> `service`) and 5 ownership exceptions (`config` -> `phoenix`, `openinference`; `service` -> `docx` on three lines), all already known (TD-007, TD-009, TD-019). `forms.reading` -> `agents.excel_agent`, an upward import in the survey's reading, is within one layer here.
- 2026-10-05: Step 3. ARCH-LAYER and ARCH-OWNER wired into `harness/arch.py` with 5 allow-list entries; stale entries fail as ARCH-ALLOW. 13 rule tests in `tests/harness/test_layers.py`. Two corrections on the way: the existing arch tests' trees have no layers file, so the rule now applies only where one exists (and a test requires it here); and `package.*` did not cover the package itself, which a test tree exposed.
- 2026-10-05: Step 4. `docs/generated/layers.md` from `harness/layers.toml` and the allow-list (stale-checked by the existing generated-docs test, and required by the docs check). ARCHITECTURE.md rewritten around the layers, with the reasons marked as Claude's; D-012; TD-007, TD-009, TD-019 updated; GP-19 and GP-20; CLAUDE.md.
- 2026-10-05: The first full `check` failed: 12 tests in `tests/harness/test_docs.py`, because adding `docs/generated/layers.md` to the required documents made their minimal tree incomplete (1698 passed, 12 failed). The fixture now builds its tree from `docs.REQUIRED`, so a new required document cannot break those tests again.

## Decision log

- 2026-10-05: M3 is split into several plans so each can be verified on its own; this one only adds checks and documentation and changes no application code. Fixing the allow-listed violations is follow-up work. My choice.
- 2026-10-05: Lazy imports count as dependencies, and imports guarded by `TYPE_CHECKING` count too: a type-only import of a higher layer is still coupling. My choice.
- 2026-10-05: The layers live in a TOML file read by the check and rendered into `docs/generated/layers.md`, rather than in a table inside ARCHITECTURE.md parsed by the check: the data and the prose change for different reasons. My choice.
