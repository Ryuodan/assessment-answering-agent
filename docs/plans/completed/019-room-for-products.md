# Plan 019: Room for products

**Status:** completed

## Goal

Milestone M7 (plan 018) adds products, a new role, and their routes and
migrations. Every module they would go into is at its size ceiling:
`api.py` (2036 lines), `store.py` (475) and `identity.py` (615). ARCH-SIZE
only lets a ceiling come down.

This plan makes room by moving code that already exists, with no change in
behaviour:

- the sign-in dependencies and the Access panel's routes out of `api.py`, into a new `src/routes/` package;
- the schema migrations out of `store.py`, into `src/migrations.py`.

It is TD-006's first real split.

## Acceptance criteria

- [x] `src/routes/auth.py` holds `current_user`, `current_admin` and `user_payload`; `src/routes/admin.py` holds the eight `/api/admin/*` routes, their request models and `_refuse_last_admin`. Their text is unchanged except for the decorator (`@router`), the payload function's public name and the return annotations.
- [x] `src/migrations.py` holds `MIGRATIONS` and `_team_the_answer_memory`. `store.MIGRATIONS` still resolves, and the store applies function migrations from the new module.
- [x] The generated OpenAPI contract is byte-identical, and the upgrade tests and error snapshots pass unchanged.
- [x] Both new modules have a layer: `src.routes.*` interfaces, `src.migrations` integrations. `api.py`'s ceiling is lowered, and `store.py` leaves the size allow-list.
- [x] `uv run poe check` passes.

## Plan

1. Save the current `openapi.json`. Move the code with one-off scripts that cut it by its definitions.
2. Include the admin router where its routes were defined.
3. Give the new modules their layers. Regenerate the docs, compare the contract, lower the ceilings, and run the gate.

## Progress log

- 2026-10-06: Moved:
  - 33 lines of dependencies and 148 lines of admin routes went from `api.py` to `src/routes/`;
  - 273 lines of migrations and 70 of `_team_the_answer_memory` went from `store.py` to `src/migrations.py`.

  `store._apply_schema` now looks function migrations up with `getattr(migrations, step)` instead of `globals()`. ruff removed three imports the move left unused.
- 2026-10-06: `poe gen`: `openapi.json` is byte-identical to the copy saved before the move. `errors.md` and `layers.md` changed only in where an error is raised and the new modules. `api.py` went from 2036 to 1862 lines, and `store.py` from 475 to 132, so it leaves the size allow-list (17 oversized modules remain, TD-006).
- 2026-10-06: mypy reported 9 old errors as new, because they had changed file: every moved route returned a bare `dict`. They were fixed (`dict[str, Any]`), not re-baselined, and the baseline went from 283 to 274. The covering tests (store, team isolation, identity, the API's identity routes, characterization, access codes, web, errors): 211 passed.
- 2026-10-06: `uv run poe check` passes (1,812 tests, 6 browser tests). Plan complete.

## Decision log

- 2026-10-06: The router is included at the place its routes were defined, not at the end of `api.py`. FastAPI lists routes in the order they are registered, so this keeps the OpenAPI contract and `docs/generated/api.md` byte-identical, which makes the move checkable. (Claude)
- 2026-10-06: The `/admin` page route stays in `api.py`. It renders the workbench through `api._page`, and moving it would mean moving the page helper too, for no gain in this plan. (Claude)
