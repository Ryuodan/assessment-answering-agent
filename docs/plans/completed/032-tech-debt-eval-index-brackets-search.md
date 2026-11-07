# Plan 032: Three items of plan 031's tech debt: the evaluation's index, empty brackets, earlier answers in search

**Status:** completed 2026-11-07

## Goal

The user's decisions on the tech debt plan 031 recorded:

- **TD-072:** the assistant's evaluation never writes the real index.
- **TD-073:** an answer never shows "()" where a source number was removed.
- **TD-074:** search shows the team's earlier answers, and filtering by a file finds that file's passages.
- **TD-066** is left as it is, by the user's decision.

## Acceptance criteria

- [x] `scripts/eval_assistant.py` searches a scratch copy of the index, removed afterwards, unless `CHROMA_DIR` is set. A test shows a write to the copy leaves the original as it was.
- [x] Brackets left empty, or holding only commas, "and" or "see", go with the numbers, in English and Arabic. Brackets with words in them stay, and so does text with no number in it.
- [x] The Workbench's search gives earlier answers a share of its results and marks each "previous answer". The assistant's `search_policies` reads what it read before.
- [x] The file filter is applied inside each store's search, before its cut.
- [x] Every change has a test that fails without it. `uv run poe check` passes. Tech debt and ARCHITECTURE updated.

## Plan

1. TD-073 and TD-072 first, each behind a test that fails without it.
2. TD-074: the share for earlier answers in `src/search.py`, the file filter in the store, and the Workbench's mark. Make room in `src/knowledge.py` first.
3. Run `uv run poe check`, update the docs, commit.

## Progress log

- 2026-11-07: built and tested.
  - TD-072 in `scripts/eval_assistant.py` (`_use_a_scratch_index`).
  - TD-073 in `src/formatting.py` (`_LEFT_EMPTY`). The 52 characterization tests pass unchanged.
  - TD-074 in `src/search.py` (`earlier_answers`, a share for each kind in each knowledge base), `src/knowledge.py` (`source_name` in `search`, `search_types` and `text_search`), `src/api.py` and the Workbench's results. The unused `lexical_search` was removed, so `knowledge.py` is 26 lines shorter.
  - New tests failed before their change: 5 on the brackets, 4 on search, 2 on the evaluation's index, 1 browser test on the "previous answer" mark. One guard test pins the assistant's lookups.
- 2026-11-07: tested end to end at the user's request ("Test the system from A to Z and make sure it is ready to be used"): plan 035's A-to-Z run, the real app and model on a copy of the local data, 20 of 20 steps passed, with no page or server errors. Plan complete.

## Decision log

- 2026-11-07, by the user: fix TD-072, TD-073 and TD-074; TD-066 is fine as it is.
- 2026-11-07, Claude, on defaults the user has not decided (each can be reversed):
  - The share for earlier answers is for a person's search only. The assistant's `search_policies` is meant for what the documents say, and its evaluation was measured on that.
  - Earlier answers and guidelines share a person's search evenly, and what one does not use the other takes.

## How to test it yourself

1. On the Workbench, open Search and look for something the team has answered before, such as "penetration test". Among the results are passages marked "previous answer", after the policies.
2. Choose one file in the file filter and search again: that file's passages are listed, even ones that rank below other files'.
3. Answers drafted from now on have no "()" or "(,,,)" where the drafter cited a source inline.
