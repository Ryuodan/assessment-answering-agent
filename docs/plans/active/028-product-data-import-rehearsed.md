# Plan 028: The products' clean data, imported into a copy and tested

**Status:** active

## Goal

Plan 026 cleaned the products' raw data into kept facts and answer pairs. None
of it has been imported anywhere, so nobody has seen the system answer with
it. This plan prepares the import, rehearses it on a copy of the local data the
way it will be done in production after the deploy, and tests the whole system
with the data in place: answers, isolation between products, the shared
knowledge, the pages, and deleting a product.

The way in is the user's decision (2026-10-19):

- the fact sheets are uploaded into each knowledge base through the workbench;
- the 49 kept answer pairs are typed in on the memory page ("Add an answer");
- there is no import feature and no server script;
- production gets the data after the deploy, and the user's local data stays as
  it is.

## Acceptance criteria

- [ ] `scripts/product_data.py` writes a final fact sheet:
  - it has no DRAFT banner and claims no team review;
  - it refuses a product with no kept facts;
  - it names the file as the citation should read.
- [ ] A contamination check compares the kept facts and pairs with the evaluation's house set. It reports test ids and item ids only and finds no leak; any leak is dropped from the import.
- [ ] A typing sheet lists every kept pair by memory, ready to copy into "Add an answer". It holds no sources, notes or customer names, and stays outside the repository.
- [ ] The import is rehearsed on a copy of the local data over HTTP. The four fact sheets are uploaded and the 49 pairs added by the same route the memory page uses. The repository's `data/`, `chroma_db/` and `.env` are untouched (hashes before and after).
- [ ] With the data in place, the following are checked and recorded with numbers:
  - product answers use their product's facts;
  - no product sees another's material;
  - General answers on unrelated topics keep their sources;
  - a product chat answers from its product;
  - the memory and library pages show the right entries;
  - deleting a product removes its sheet, file and answers and leaves its questionnaires and chats read-only.
- [ ] `uv run poe check` passes. The roadmap's M8 row and the deploy steps for production are updated.

## Plan

1. Final fact sheets and the contamination check in `scripts/product_data.py`, with tests.
2. Export the typing sheet and the four final fact sheets into the clean-data folder.
3. Copy the local data and start the app on the copy. Record the baseline answers to probe questions.
4. Upload the sheets, add the pairs, and run the conflict sweep.
5. Re-ask the probes and check each point above. Then delete a product.
6. Record the results here, and write the production steps.

## Progress log

- 2026-10-19: plan written. It runs after plan 027's fixes, which it depends on: TD-037 for the chat, TD-039 for deletion and the previous-answer collision for the pairs.
- 2026-10-19: steps 1 and 2.
  - **The script** (`scripts/product_data.py`) gained three things. The final fact sheet has no banner, no ids and no review claim, and the draft has no review claim either. A batch with no kept facts gets no sheet. The new `contamination` command checks the kept items and `typing` writes the typing sheet. `tests/test_product_data.py` has 26 tests, 3 of them new.
  - **Contamination:** 135 house-set cases against 119 kept items (70 facts, 49 pairs) found 0 leaks.
  - **The files** are in the clean-data folder's `for import/`:
    - four sheets: Ole5 (12 facts), RICH (27), Availo (1) and T2 (30). Msegat was refused, with no kept facts;
    - the typing sheet, with 49 answers: Ole5 4, RICH 27, Availo 1, Shared 17.
  - **Customer names:** a scan of all five files for words from the delivered files' names found none. Only generic and technical words matched.

## Decision log

- 2026-10-19, by the user: the pairs are typed by hand; the import is tested on a copy now and done in production after the deploy; local data is unchanged.
- 2026-10-19, Claude: the final sheet keeps one heading per topic and one line per fact, without the internal `[F-xxx]` ids, so that they never appear in an answer. The batch file keeps the order and ids for tracing a fact back.
