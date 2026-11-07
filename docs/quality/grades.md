# Quality grades

Each cleanup round grades each layer, using the layers in
[layers.md](../generated/layers.md). Every round uses the same five measures
and the same thresholds, so one round can be compared with the next. The
thresholds are set in `harness/grades.py`:

```bash
uv run poe cov       # the suite with coverage; writes .coverage.json
uv run poe grades    # the table below
```

A grade is a measurement, not a target. The words under each table say what
the letter stands for and where the gap is, so the next round can check
whether it closed.

## Round 5: 2026-11-07, after plans 026 to 035 (plan 036)

Measured on the working tree of plan 036. 2,401 tests passed and none failed;
the 197 browser tests are not part of the coverage run. Statement coverage of
`src/` and `harness/` together is 93% (round 4: 92%).

| Layer | Modules | Lines | Coverage | Over 400 | Suppressions | Duplicated blocks | Docstrings |
|---|---|---|---|---|---|---|---|
| foundation | 17 | 4231 | A (99%) | B (1) | A (0) | A (0) | A (96%) |
| integrations | 26 | 7441 | A (92.1%) | D (6) | D (10) | C (2) | A (97%) |
| records | 14 | 4495 | A (95.9%) | C (3) | D (10) | A (0) | A (91%) |
| answering | 14 | 2363 | A (90.7%) | B (1) | C (4) | A (0) | A (100%) |
| operations | 14 | 5417 | A (96.4%) | C (3) | C (7) | A (0) | A (99%) |
| interfaces | 12 | 3070 | A (94.5%) | B (1) | B (3) | A (0) | B (82%) |

Plans 026 to 035 added products' data, the team's feedback in three parts,
consistency, retention, and the debts. Most new code went into new, small
modules rather than into the large ones:

- **foundation** gained `product_prompts`, `chat_running` and `reading` (and
  counts `src` itself). Coverage went from 98.7% to 99%.
- **integrations** gained `migration_steps` (TD-046) and others. Suppressions
  went from 9 to 10: one more broad `except`, with its reason.
- **records** gained `retention` and `search_plans`. Suppressions went from
  7 to 10, all a broad `except` with its reason, in the retention pass and the
  answer saver. Docstrings went from 89% to 91%.
- **answering** went from B to A on coverage, 87.7% to 90.7%, and from C to
  B on size: `graph/nodes.py` (385 lines) is under the limit, after the
  product scope, the kept searches and the query parser moved to modules of
  their own.
- **operations** gained `lists`, `questionnaire`, `assistant_cards`,
  `assistant_stopped`, `fill_audit` and others. Coverage went from 92.9% to
  96.4%. The same three modules are over 400, all smaller than at round 4:
  `assistant.py` 1,524 to 1,386, `tools.py` 1,376 to 1,144, `service.py`
  614 to 469.
- **interfaces**: `api.py` went from 1,296 to 1,178 lines. Docstrings 80% to
  82%.

`poe gc` found the round 1 candidates, two new duplicates and one
suppression without a reason. The `lists`/`tools` duplicate is now one
helper, and the migrations' is history that is not edited. OVERSIZE went from
16 to 15.

The gaps that remain, in order of size:

- the oversized modules (TD-006);
- the suppressions in integrations and records, each with its reason;
- `api.py`'s undocumented names.

## Round 4: 2026-10-06, after M7 (plan 025)

Measured on the working tree of plan 025: 1,861 tests passed and none failed.
The 13 browser tests are not part of the coverage run. Statement coverage of
`src/` and `harness/` together is 92% (round 2: 91%). The docstring column
includes the docstrings this round added.

| Layer | Modules | Lines | Coverage | Over 400 | Suppressions | Duplicated blocks | Docstrings |
|---|---|---|---|---|---|---|---|
| foundation | 13 | 3616 | A (98.7%) | B (1) | A (0) | A (0) | A (95%) |
| integrations | 23 | 7059 | A (91.3%) | D (6) | D (9) | C (2) | A (97%) |
| records | 12 | 3814 | A (95.8%) | C (3) | C (7) | A (0) | B (89%) |
| answering | 10 | 2166 | B (87.7%) | C (2) | C (4) | A (0) | A (100%) |
| operations | 6 | 4087 | A (92.9%) | C (3) | C (6) | A (0) | A (100%) |
| interfaces | 11 | 2789 | A (93.6%) | B (1) | B (3) | A (0) | B (80%) |

M7 (plans 019 to 024) added products. To make room it moved code out of the
largest modules, so most of what changed is where code lives:

- **foundation.** It gained `roles` and `schemas`, the model-output schemas
  moved out of `models.py`. `models.py` (329 lines) is under the limit now,
  which leaves `chunking.py` as the one module over 400. Over 400 went from C
  to B.
- **integrations.** It gained `migrations`, `scoped_knowledge` and
  `vector_names`. `store.py` went from 475 to 132 lines when the migrations
  left it, so six modules are over 400 instead of seven; still D. Coverage
  went from 90.6% to 91.3%.
- **records.** It gained `products` and `memory_sweep`. Coverage went from
  95.1% to 95.8%, and docstrings from 87% to 89%. The same three modules are
  over 400; `answer_memory.py` is smaller, 836 lines.
- **answering.** Unchanged apart from retrieval asking for the product's
  store.
- **operations.** It gained `search`, `selection` and
  `agents/assistant_prompt`. All three of the layer's large modules are still
  over 400, but smaller than at round 1:
  - `assistant.py` went from 1,742 to 1,524 lines;
  - `tools.py` from 1,487 to 1,376;
  - `service.py` from 741 to 614.
- **interfaces.** It gained `src/routes/`, eight modules. They took the
  assistant, Access panel, sign-in, knowledge, memory and products routes out
  of `api.py`, which went from 2,036 to 1,296 lines.

  Docstrings went from D (59%) to B (80%). This round documented the 27 public
  names in `src/routes/`, `cli.py` and `web.py` that had none, among them the
  six Access panel routes and two chat routes from round 1's list. `api.py`
  itself still has 27 without one: 11 routes, 15 request models and
  `lifespan`. It is at its size ceiling, and the formatter adds a blank line
  after a class docstring, so they wait for its next split.

`poe gc` found the round 1 candidates and nothing new: 4 TEST-ONLY and 2
DUPLICATE, all decided in plan 008. OVERSIZE went from 18 to 16, with
`store.py` and `models.py` now under the limit.

The gaps that remain, in order of size:

- the oversized modules (TD-006);
- `api.py`'s undocumented names;
- `extraction.py` (44%) and `docling_client.py` (62%) coverage.

## Round 3: 2026-10-06, after M6 (plan 015)

M6 changed `eval/`, `scripts/` and tests, not `src/`. The only change to
`src/` since round 2 is the `TYPE_CHECKING` import in `src/prompts.py`
(TD-018). Coverage was therefore not re-measured: the coverage column is
round 2's run, and the other columns are measured on the current tree.

| Layer | Modules | Lines | Coverage | Over 400 | Suppressions | Duplicated blocks | Docstrings |
|---|---|---|---|---|---|---|---|
| foundation | 11 | 3517 | A (98.7%) | C (2) | A (0) | A (0) | A (95%) |
| integrations | 20 | 6920 | A (90.6%) | D (7) | D (9) | C (2) | A (97%) |
| records | 10 | 3467 | A (95.1%) | C (3) | C (7) | A (0) | B (87%) |
| answering | 10 | 2164 | B (87.5%) | C (2) | C (4) | A (0) | A (100%) |
| operations | 3 | 3970 | A (92.8%) | C (3) | C (6) | A (0) | A (100%) |
| interfaces | 3 | 2387 | A (91.4%) | B (1) | B (3) | A (0) | D (60%) |

No grade moved. The gaps written under round 1 stand, in order of size:

- the oversized modules of operations and integrations (TD-006);
- the 17 undocumented routes in `api.py`;
- `extraction.py` and `docling_client.py` coverage.

None of them can be closed by cleanup alone: each is a split or a test-writing
plan.

## Round 2: 2026-10-06, after M4 and M5 (plan 012)

Measured on the working tree of plan 012: 1,792 tests passed and none failed;
the five browser tests are not part of the coverage run. Statement coverage
of `src/` and `harness/` together is 91% (round 1: 89%).

| Layer | Modules | Lines | Coverage | Over 400 | Suppressions | Duplicated blocks | Docstrings |
|---|---|---|---|---|---|---|---|
| foundation | 11 | 3512 | A (98.7%) | C (2) | A (0) | A (0) | A (95%) |
| integrations | 20 | 6920 | A (90.6%) | D (7) | D (9) | C (2) | A (97%) |
| records | 10 | 3467 | A (95.1%) | C (3) | C (7) | A (0) | B (87%) |
| answering | 10 | 2164 | B (87.5%) | C (2) | C (4) | A (0) | A (100%) |
| operations | 3 | 3970 | A (92.8%) | C (3) | C (6) | A (0) | A (100%) |
| interfaces | 3 | 2387 | A (91.4%) | B (1) | B (3) | A (0) | D (60%) |

What changed since round 1:

- **interfaces.** Coverage went from B (86.4%) to A (91.4%), because
  `cli.py` went from 0% to 66% with the `doctor` and `inspect` tests
  (plan 010). Docstrings are still D: the 17 route functions in `api.py`,
  which wait for that module to be split.
- **integrations.** Gained one module, `diagnostics.py`. It arrived without
  docstrings on five of its public functions, which took the layer from 96%
  to 91%. They were added in this round, and the layer is now at 97%. Its
  coverage is 83%; the untested lines are the network probe paths that need a
  live service.
- **Everything else** is as in round 1. M4 changed documents and M5 added
  tests, so neither moved the size, suppression or duplication counts. The
  gaps written under round 1 stand.

`poe gc` found the same candidates as at the end of round 1 and nothing new.
The round fixed three places where wording still pointed at the README for
text that plan 009 had moved: `SECURITY.md`, `docs/project/overview.md`, and
a comment in `scripts/dev_server.py`.

## Round 1: 2026-10-06, after M3 (plan 008)

Measured on the working tree of plan 008: 1,779 tests passed. The one failure
was `errors.md`, which was stale at the time and has since been regenerated.
Statement coverage of `src/` and `harness/` together is 89%.

| Layer | Modules | Lines | Coverage | Over 400 | Suppressions | Duplicated blocks | Docstrings |
|---|---|---|---|---|---|---|---|
| foundation | 11 | 3485 | A (98.7%) | C (2) | A (0) | A (0) | A (94%) |
| integrations | 19 | 6730 | A (90.9%) | D (7) | D (9) | C (2) | A (96%) |
| records | 10 | 3467 | A (95.1%) | C (3) | C (7) | A (0) | B (87%) |
| answering | 10 | 2164 | B (87.5%) | C (2) | C (4) | A (0) | A (100%) |
| operations | 3 | 3970 | A (92.8%) | C (3) | C (6) | A (0) | A (100%) |
| interfaces | 3 | 2338 | B (86.4%) | B (1) | B (3) | A (0) | D (60%) |

The gaps, layer by layer:

- **foundation.** Well tested and documented. Two modules are over the size
  limit:
  - `chunking.py` has 1,094 lines.
  - `models.py` has 421 lines.

  `chunking.py` holds the layer's one real piece of logic, and it is the module
  to split first.
- **integrations.** This layer has the most debt, in three places:
  - **Size.** Seven of its nineteen modules are over 400 lines: `forms/xlsx.py`,
    `forms/xlsx_package.py`, `forms/docx.py`, `knowledge.py`, `export_pdf.py`,
    `documents.py` and `store.py`.
  - **Suppressions.** Nine, in `knowledge.py` (3), `llm.py` (3) and
    `documents.py` (2). Each now has a reason; most are broad `except` clauses
    at service boundaries.
  - **Duplication.** Two blocks:
    - A merged-range copy appears in both `forms/xlsx.py` and
      `forms/xlsx_package.py`. It is left until `xlsx_package.py` is split.
    - Two migrations in `store.py` repeat each other. This is intended.

  Coverage is high overall but weak at the edges:
  - `docling_client.py` is at 61%. Its error paths and URL conversion
    (TD-032) are untested.
  - `llm.py` is at 75%. Groq's recovery paths are reached only by live calls.
- **records.** Three modules are over the limit: `answer_memory.py`,
  `identity.py` and `preferences.py`.

  Seven suppressions, five of them in `answer_memory.py`.

  Missing docstrings are concentrated in `preferences.py` (`Preferences`,
  `Skill`, three skill functions) and in `answer_memory.py` (six public
  functions).

  `access_codes.py` is at 68% coverage. The writes to the terminal are not
  exercised, because tests have no terminal.
- **answering.** Fully documented. Two modules are over the limit: `graph/nodes.py`
  (406 lines) and `agents/excel_agent.py`.

  Coverage is the gap:
  - `extraction.py` is at 43%. Question extraction from text is mostly
    exercised through fakes that replace it.
  - `forms/reading.py` and `agents/excel_agent.py` are both at 85%.
- **operations.** All three modules are over the limit:
  - `agents/assistant.py` has 1,742 lines.
  - `tools.py` has 1,487 lines.
  - `service.py` has 741 lines.

  Three modules hold 3,970 lines between them. These are the layer's real
  problem; coverage (93%) and docstrings (100%) are not.
- **interfaces.**
  - **Docstrings.** 42 public names in `api.py` have none: most of them are
    request models and 17 are route functions. Those 17 routes therefore
    appear in the OpenAPI contract under a summary FastAPI generates from the
    function name ("Admin Add User").
  - **Coverage.** `cli.py` is at 0%: no test runs the command line.
  - **Size.** `api.py`, at 2,036 lines, is the largest module in `src/`.

  All three gaps point the same way: split `api.py` into routers by area, each
  route with its docstring.

What changed in this round is recorded in
[plan 008](../plans/completed/008-gc-round-1.md).
