# Execution plans

Every non-trivial piece of work gets a plan: `active/NNN-slug.md` while it is
being done, moved to `completed/` when every acceptance criterion is met and
`uv run poe check` passes. A small change needs no plan.

- [roadmap.md](roadmap.md): milestones, and which plans serve each.
- [tech-debt.md](tech-debt.md): known problems (TD-001, ...), their impact and the fix.
- [active/](active/): plans in progress.
- [completed/](completed/): finished plans, kept as the record of what was done and measured.

## Rules

- Update the plan's logs as you go, in the same commit as the work.
- Name the plan in the commit subject: `Plan 007: <what this commit does>`.
- Promote a lasting decision from a plan's decision log to
  [decisions.md](../design/decisions.md).
- Record failed and rejected attempts, with their numbers. Mark your own
  reasoning as yours; never write a number or reason nobody gave.
- A plan is done when every criterion is checked, `check` passes and the
  affected docs are updated. Then set its status to `completed`, move it to
  `completed/`, and update the roadmap.

`uv run poe docs` checks every plan for the sections below and for a status
that matches its folder.

## Template

```markdown
# Plan NNN: <title>

**Status:** active

## Goal

One paragraph: the capability that will exist when this is done, and why it matters.

## Acceptance criteria

- [ ] Observable, testable outcome.

## Plan

1. Ordered step, small enough to verify on its own.

## Progress log

- YYYY-MM-DD: what was done, what was verified (with numbers), what is next.

## Decision log

- YYYY-MM-DD: the decision, the alternatives, why, and who decided.
```
