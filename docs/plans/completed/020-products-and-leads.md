# Plan 020: Products and the team lead

**Status:** completed

## Goal

A team has products (the cybersecurity team starts with Availo, Msegat,
Ole5, RICH and SouqT2). A new role, the team lead, manages them for their
own team, alongside administrators: add, rename, recolour, describe, delete.

Deleting a product shows a coloured warning that its documents and
remembered answers will be deleted, and needs "confirm" typed, in the page
and in the API alike. Everyone on the team can see the products.

This plan gives products their records, their routes and their page. Their
knowledge bases, answer memories and selection come in plans 021 to 023
(plan 018).

## Acceptance criteria

- [x] Roles are `member`, `lead` ("Team lead") and `admin`, defined in `src/roles.py`. The Access panel can give and change the lead role. Demoting the last administrator to any other role is refused, as demoting to member already was.
- [x] Migration 11 adds a `products` table and a `seeds` table. A database at version 10 upgrades and keeps its data.
- [x] `src/products.py` lists, gets, adds, edits and deletes a team's products. Validation:
  - a name has 1-40 characters after trimming, and is unique per team regardless of case, Arabic included;
  - a colour is `#RRGGBB`, or the next one from the palette when left out;
  - a description has at most 200 characters.

  The refusals are `AppError`s with codes: `product_not_found` 404, `product_name_taken` 409 (a new `Conflict` class), `confirmation_required` 400.
- [x] `/api/products` (GET, POST), `/api/products/{id}` (PATCH, DELETE with `confirm=confirm`):
  - anyone on the team may list;
  - the team's leads and any administrator may change;
  - an administrator may name another team with `team`.

  Every change records an event.
- [x] `SEED_PRODUCTS` (empty in `.env.example`, with the five as its example; set in the user's `.env`) adds its products to the default team once. A product deleted afterwards is not re-added by a restart.
- [x] A Products page (`/products`), linked from every page's header. Members see the list; leads and administrators also see add, edit and delete. Delete opens a dialog with a coloured warning naming what will be lost, and the delete button stays disabled until "confirm" is typed.
- [x] Tests:
  - unit, for products, roles and seeding;
  - API, a permissions matrix and every refusal;
  - migration upgrade;
  - browser, a lead adds a product and deletes it through the dialog, and a member sees no controls.
- [x] `api.py` and `identity.py` are no longer than before (the page helper moves to `src/routes/pages.py`). `uv run poe check` passes.

## Plan

1. Write `src/roles.py` and point `identity` at it. Update the last-administrator check and the Access panel's role choices.
2. Add migration 11; the `Conflict`, `ProductNotFound` and `ProductNameTaken` errors; and `src/products.py`, with seeding.
3. Move the page helper to `src/routes/pages.py`. Add `src/routes/products.py` (API and page), include it, and seed at startup.
4. Write `products.html`, and add the header links.
5. Write the tests, then the docs (ARCHITECTURE, SECURITY, D-016, generated). Run the gate and close the plan.

## Progress log

- 2026-10-06: Roles:
  - `src/roles.py` (foundation) holds `MEMBER`, `LEAD`, `ADMIN`, `ROLES`, `LABELS` and `manages_products`. `identity` imports the constants, so it shrank from 615 to 612 lines.
  - The last-administrator check in `routes/admin.py` now refuses any role but admin. Before, it refused only "member", so the last administrator could have been demoted to lead.
  - The Access panel offers "Team lead".
- 2026-10-06: Records:
  - migration 11 (`products`, with a unique index on `(team_id, name COLLATE NOCASE)`, and `seeds`);
  - `Conflict` (409), `ProductNotFound` and `ProductNameTaken` errors, and three product events;
  - `SEED_PRODUCTS` in `src/config.py` and `.env.example`;
  - `src/products.py` (records), which goes through `store` rather than `sqlite3`. ARCH-OWNER caught the first draft importing it directly; `store.IntegrityError` was added for that.

  On a scratch database, the five products seed once with five colours; a deleted one stays deleted after a re-seed; "  rich " is refused as `product_name_taken`.
- 2026-10-06: Routes and page:
  - The page helper moved from `api.py` to `src/routes/pages.py`, unchanged. `tests/test_pages.py` read `api._fingerprint` and now reads it from `pages`. The moved static-files handler gained its type annotations (mypy baseline 274 -> 272).
  - `src/routes/products.py` serves the API and `/products`. `api.py` includes it and seeds at startup; it went from 1862 to 1811 lines.
  - `products.html` shows the list for everyone. Leads and administrators also get add, edit and delete. Delete opens a dialog with a red warning naming what will be lost, and its button stays disabled until "confirm" is typed. Every page's header links to it.
- 2026-10-06: Tests:
  - `tests/test_products.py`: 14 tests, all passing on the first run. They cover the records, case-insensitive and Arabic uniqueness, validation codes, the confirmation word, seeding once, the role rule, an upgrade from version 10, the API's permissions matrix, a lead against an administrator across teams, giving the lead role and refusing to demote the last administrator, and the page being served.
  - `tests/test_pages.py` now covers `/products` (22 tests).
  - `tests/browser/test_products_page.py`: 2 tests. A lead adds Availo and deletes it; the warning's colour is the page's error colour, compared exactly in whichever theme is on; the button stays disabled until "confirm". A member sees the list and no controls.
- 2026-10-06: Checked by eye in the open-mode dev server (scratch database), in both themes. The first look found the list's Delete links drawn as solid red buttons: the dialog button's style also matched them. It now applies to the dialog button only. `SEED_PRODUCTS` was appended to the user's `.env`, as decision 6 said, without the file being read or printed.

- 2026-10-06: The first full gate failed one test: `tests/test_eval_history.py` holds `.env.example` to the code defaults, and the template had the five names where the code default is empty. The template now has an empty value with the five as a commented example, which keeps organisation-specific names out of the code (TD-015). The user's `.env` sets them.

- 2026-10-06: `uv run poe check` passes (1,829 tests, 8 browser tests). Plan complete.

## Decision log

- 2026-10-06: The role is `lead`, shown as "Team lead". The user left the name to Claude, among "Manager" and "Leader": "Team lead" says the person belongs to the team and leads it, which is what the role allows. (Claude)
- 2026-10-06: "Seeded once" is recorded in a `seeds` table, not inferred from the rows. Inferring it, as `ALLOWED_EMAILS` does from `added_by`, would re-add all five products on the next restart if someone deleted all five. (Claude)
