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
