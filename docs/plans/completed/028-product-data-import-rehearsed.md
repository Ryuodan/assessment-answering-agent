# Plan 028: The products' clean data, imported into a copy and tested

**Status:** completed

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

- [x] `scripts/product_data.py` writes a final fact sheet:
  - it has no DRAFT banner and claims no team review;
  - it refuses a product with no kept facts;
  - it names the file as the citation should read.
- [x] A contamination check compares the kept facts and pairs with the evaluation's house set. It reports test ids and item ids only and finds no leak; any leak is dropped from the import.
- [x] A typing sheet lists every kept pair by memory, ready to copy into "Add an answer". It holds no sources, notes or customer names, and stays outside the repository.
- [x] The import is rehearsed on a copy of the local data over HTTP. The four fact sheets are uploaded and the 49 pairs added by the same route the memory page uses. The repository's `data/`, `chroma_db/` and `.env` are untouched (hashes before and after).
- [x] With the data in place, the following are checked and recorded with numbers:
  - product answers use their product's facts;
  - no product sees another's material;
  - General answers on unrelated topics keep their sources;
  - a product chat answers from its product;
  - the memory and library pages show the right entries;
  - deleting a product removes its sheet, file and answers and leaves its questionnaires and chats read-only.
- [x] `uv run poe check` passes. The roadmap's M8 row and the deploy steps for production are updated.

## Plan

1. Final fact sheets and the contamination check in `scripts/product_data.py`, with tests.
2. Export the typing sheet and the four final fact sheets into the clean-data folder.
3. Copy the local data and start the app on the copy. Record the baseline answers to probe questions.
4. Upload the sheets, add the pairs, and run the conflict sweep.
5. Re-ask the probes and check each point above. Then delete a product.
6. Record the results here, and write the production steps.

## In production, after the deploy

Done by a lead or an administrator in the running app, in this order. The files
are in the clean-data folder's `for import/`, outside this repository.

1. **Memory corrections.** Re-apply plan 026's memory corrections on the memory
   page (TD-036): forget the entries matching MEM-0035, MEM-0519 and MEM-0400,
   and move MEM-0397 to RICH. Match each by its question, because production's
   ids may differ.
2. **Fact sheets.** On the workbench's Knowledge base panel, choose each product
   in turn and upload its sheet as our own document: Ole5, RICH and Availo. Then
   choose Shared and upload the T2 sheet. Msegat has none.
3. **Answers.** On the memory page, for each sheet of "Kept answers to add by
   hand.xlsx", choose that memory and add each row with Add an answer, pasting
   the question and the answer as they are. Mark the Added column as you go.
   There are 49 rows: Ole5 4, RICH 27, Availo 1, Shared 17.
4. **Conflicts.** Run Check for conflicts on the memory page. Expect a few older
   shared answers to be marked replaced; the rehearsal saw 3.
5. **Spot checks.** Ask two or three questions per product, on the workbench
   with the product chosen, and one in a product chat. Each should cite its
   product's sheet.

## Progress log

- 2026-10-19: plan written. It runs after plan 027's fixes, which it depends on: TD-037 for the chat, TD-039 for deletion and the previous-answer collision for the pairs.
- 2026-10-19: steps 1 and 2.
  - **The script** (`scripts/product_data.py`) gained three things. The final fact sheet has no banner, no ids and no review claim, and the draft has no review claim either. A batch with no kept facts gets no sheet. The new `contamination` command checks the kept items and `typing` writes the typing sheet. `tests/test_product_data.py` has 26 tests, 3 of them new.
  - **Contamination:** 135 house-set cases against 119 kept items (70 facts, 49 pairs) found 0 leaks.
  - **The files** are in the clean-data folder's `for import/`:
    - four sheets: Ole5 (12 facts), RICH (27), Availo (1) and T2 (30). Msegat was refused, with no kept facts;
    - the typing sheet, with 49 answers: Ole5 4, RICH 27, Availo 1, Shared 17.
  - **Customer names:** a scan of all five files for words from the delivered files' names found none. Only generic and technical words matched.
- 2026-10-20: steps 3 to 5, the rehearsal, at commit `e9c0529`.
  - **Setup:** a copy of the local data under `%TEMP%\r028`; the app on port 8120; test accounts only.
  - **27 probe questions:** 12 General (6 on topics the shared items add, 6 unrelated), 6 Ole5, 6 RICH, 3 Availo. Asked before and after the import, with no failures.
  - **The import, through the app's own routes:**
    - the four sheets were uploaded into their knowledge bases: 3, 3, 1 and 6 chunks;
    - the 49 pairs were added with "Add an answer": Ole5 4, RICH 27, Availo 1, Shared 17; all 49 returned 200;
    - the conflict sweep marked 3 older shared answers replaced (MEM-0294, MEM-0309, MEM-0335) and raised no new conflict.
  - **After the import:**
    - all 14 product probes used their product's sheet, and none had evidence from another product;
    - all 6 shared-topic General probes used the T2 sheet or a new shared answer;
    - of the 6 unrelated General probes, the top source by score was unchanged 6/6 and the top three 4/6, with no imported material in their evidence. In the order the drafter listed its evidence, the first item changed in 2 of 6. Each probe was asked once per phase, so run-to-run variation is not ruled out;
    - mean confidence went from 0.69 to 0.89;
    - all 20 targeted answers agree with their fact (read by hand). Four baseline answers had contradicted the kept facts: Ole5's single sign-on, Ole5's customer penetration tests, sharing Ole5's penetration test report, and a shared continuity certification.
  - **Chat:**
    - an Ole5 chat's direct answer used Ole5's sheet (TD-037);
    - a search-only request searched once and quoted three passages word for word;
    - a General chat used shared material only.
  - **Excel:** a two-question form opened for RICH read 2 questions, with no reminder or stopped round in the log.
  - **Pages:**
    - the memory page listed every memory with the counts the API gives, and its "Added by hand" filter showed exactly the typed pairs;
    - the library listed each sheet once, with its product's badge;
    - the delete dialog counted the product's documents, file and answer;
    - a member had no Delete button.
  - **Deleting Availo** (it had one questionnaire and one chat by then):
    - its folder, collection and remembered answer went; 1 file removed, none left;
    - every other scope was unchanged, digest for digest;
    - its questionnaire and chat stayed listed and read-only, with seven writes refused with 409 `product_deleted`;
    - fill and download worked.
  - **Live data:** the hashes of `data/app.db` and `chroma_db/chroma.sqlite3` were identical before and after. No file in `data/`, `chroma_db/` or `.env` changed during the rehearsal (the verifier's modification-time check). The copy was deleted.
  - **Findings:**
    - **The RICH hosting provider.** RICH answers name the hosting provider, which plan 026 held as unconfirmed. They did so before the import too. The source is two existing shared answers, MEM-0332 and MEM-0503, which plan 026 left shared "until the team says". This is for the user to decide.
    - **A false quotation note.** In the search-only chat, a reply whose three quotations were word for word got the paraphrase note, and its quotation marks stayed. Offline, the stored reply against the real chunks finds nothing unfound, so the trigger was not reproduced. The note is now added only when the reply actually holds the words flagged (TD-049).
    - **Docling** was unreachable, so the sheets were converted by the local loader. Production converts with Docling, and its chunk counts may differ.
    - **Vector residue.** Deleting a product left its vector-index folder on disk: vectors only, no text (TD-051).
    - **Excel.** The two-question form was read by the agent, not the rules, with readings to check: the agent-versus-rules tie is TD-043's open question.
    - **Search.** A product-scoped search showed the Availo sheet but not Availo's remembered answer, which the drafter did use. Not investigated.
    - **Wording.** The chat's refusal reused the questionnaire's wording about a filled file. Now fixed.
    - **Replaced answers.** Typing the shared pairs marked 3 existing shared answers replaced. Production will do the same unless its memory differs.
- 2026-10-20: an independent verifier re-derived every check from the raw evidence.
  - **Confirmed:** the import, product isolation, the pages, the deletion and the unchanged live data.
  - **Corrected:** the baseline contradictions (4, not 3) and the definition behind the unrelated-probe figure, both above.
  - **Found no customer name** in the 42 evidence files.

## Decision log

- 2026-10-19, by the user: the pairs are typed by hand; the import is tested on a copy now and done in production after the deploy; local data is unchanged.
- 2026-10-19, Claude: the final sheet keeps one heading per topic and one line per fact, without the internal `[F-xxx]` ids, so that they never appear in an answer. The batch file keeps the order and ids for tracing a fact back.
