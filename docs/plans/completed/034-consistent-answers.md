# Plan 034: The same question gets the same answer more often, without copying

**Status:** completed 2026-11-07

## Goal

The team's feedback: "the same question gives different answers". Plan 029 measured it. In three identical NAC runs, the "Yes" held, but the wording, the sources and the confidence varied.

The user chose to keep drafting every time rather than return earlier answers word for word. So consistency comes from three changes to how an answer is drafted:

- **The same searches.** A question's search plan is remembered, so the same question finds the same sources.
- **Confirmed answers first.** An earlier answer to the same question is always among the sources, first, and the drafter keeps its position and facts unless our policy now says otherwise.
- **No invented names.** The drafter does not claim a technology or product named in the question, such as "NAC", unless a source names it.

Each is measured: 12 questions, three runs each, before and after, and then the held-out evaluation.

## Acceptance criteria

- [x] **No invented names:** the drafter and the reviewer are told not to claim a technology, product or programme from the question unless a source names it.
- [x] **Same question:** an earlier answer whose question is the same words (ignoring case, punctuation and digits' script) is kept in the sources, first, beyond the cap on earlier answers, and marked PREVIOUS ANSWER TO THIS SAME QUESTION. The drafter keeps its position and facts unless OUR POLICY says otherwise.
- [x] **Same searches:** the search plan is stored per question, language and product, and reused. A plan that failed is not stored.
- [x] Measured on the 12 questions, three runs each, before and after each step: the same decision, the same verdict, cited sources in common, and wording in common.
- [x] The held-out evaluation is run after, and compared with the runs on file.
- [x] Every change has a test that fails without it. `uv run poe check` passes. The docs are updated: decisions, evaluation.md, tech-debt and ARCHITECTURE.md.

## Plan

1. Measure the baseline. (Done.)
2. No invented names, and the same question first. Measure.
3. The same searches, once plan 033's server work has made room in the migrations (TD-046). Measure.
4. The held-out evaluation. Docs. Commit. The user tests.

## Progress log

- 2026-11-07: the baseline, at `9df3b3b`, on a copy of the local data, General, 12 questions × 3 runs. The questions were plan 029's NAC and SLA questions in English and Arabic, and eight general ones.

  | | baseline |
  |---|---|
  | same held/released decision in all 3 runs | 9 of 12 |
  | same verdict (yes/no/statement) | 11 of 12 |
  | cited sources in common between runs | 0.72 |
  | wording in common between runs | 0.41 |
  | confidence spread (max − min) | 0.13 |

  - NAC flipped between held and released. One run claimed "T2 implements Network Access Control (NAC)", a name no source uses.
  - The incident-response plan question flipped too. One run's searches found the regulator's ECC guide instead of our incident policy, and it was held.
  - Only 2 of the 695 remembered answers repeat a question word for word, so "the same question" will mostly help when a questionnaire comes back.

- 2026-11-07: step 2, no invented names and the same question first.
  - `formatting.same_wording` and `Evidence.asked`. `select_evidence` keeps an earlier answer to the same words first, beyond the cap. `format_sources_block` marks it PREVIOUS ANSWER TO THIS SAME QUESTION.
  - Two rules were added to the drafter's prompt and one to the reviewer's. The two characterization snapshots that pin the prompt were re-recorded, and only those lines changed.
  - 12 new unit tests; their module does not import without the change.
  - Measured the same way:

    | | baseline | step 2 |
    |---|---|---|
    | same decision | 9 of 12 | 11 of 12 |
    | same verdict | 11 of 12 | 12 of 12 |
    | cited sources in common | 0.72 | 0.71 |
    | wording in common | 0.41 | 0.45 |
    | confidence spread | 0.13 | 0.03 |

  - NAC no longer flips between held and released. One of three English runs still writes "Network Access Control (NAC)"; the other two write "network access controls", as the sources do.
  - The sources are as varied as before. That is the searches, which step 3 holds still.
  - 36 runs a side is a small sample: some of the gain may be noise.
- 2026-11-07: step 3, the same searches.
  - What was built:
    - `src/search_plans.py` (records) keeps a plan per team, product, language and folded wording, in migration 16's `search_plans`.
    - `src/graph/kept_searches.py` is how `nodes.plan` uses it: a kept plan is used again, and a plan is kept only when the planner returned queries.
    - `REUSE_SEARCH_PLANS` (default true) switches it off.
    - Retention deletes plans unused for `RETENTION_DAYS`, since they hold the question's words.
  - For room, `_parse_queries` moved unchanged to `src/graph/query_text.py`; `nodes` imports it under its old name.
  - 6 new tests. The one that pins reuse fails on the old `plan`; the others pin the store and what must not change.
  - The measurement ran in rounds, every question's first run before its second, as a question asked again comes after the first time:

    | | baseline | step 2 | step 3 |
    |---|---|---|---|
    | same decision | 9 of 12 | 11 of 12 | 11 of 12 |
    | same verdict | 11 of 12 | 12 of 12 | 12 of 12 |
    | cited sources in common | 0.72 | 0.71 | **0.88** |
    | wording in common | 0.41 | 0.45 | **0.57** |
    | confidence spread | 0.13 | 0.03 | 0.05 |

  - The incident-response question now cites the same sources run after run (0.42 to 0.93), and NAC's Arabic run cites identical ones.
  - What still varies is the drafter's wording (temperature 0.2) and the reviewer's judgement. One question, about leavers, was held once at 0.6.
- 2026-11-07: the held-out evaluation, the dev split (82 questions, 3 questionnaires).
  - It ran before (`9df3b3b`, a scratch checkout) and after (`4ddaee9`), each on its own copy of the local data, so the kept search plans and the migrations never touched the real database. The hashes of `data/app.db` and `chroma_db/chroma.sqlite3` were unchanged.

    | dev split | before | after |
    |---|---|---|
    | agreement with the team | 83.7 | 82.2 |
    | form | 95.1 | 97.6 |
    | released (will be written) | 43 | 48 |
    | contradictions among the released | 1 | 1 |
    | held for review | 39 | 34 |
    | contradictions among the held | 8 | 10 |

  - Against the noise baseline (`compare_runs --noise`): 2 cases better, 4 worse, 7 moved within noise, 69 the same.
  - The −1.5 in agreement is within the 4 points identical runs differ by (evaluation.md). So is the total number of contradictions, which was 11 and 8 between identical runs.
  - The safety measure held: one contradiction among the released answers both times, with 5 more answers released.
  - Only counts and case ids were read from the sealed house set.
- 2026-11-07: an adversarial review of plans 033 and 034 together. It checked the timestamps (all `store.utcnow()`), migrations 15 and 16 on an older database, the `[n]` citations, the owner checks and the keyboard review, and found them sound. Fixed, each with a test in `tests/test_review_033_034.py` that fails without the fix:
  - **The same words are not always the same question.** "If yes, please provide details." under Encryption lent its kept searches to the same words under Access control (reproduced), and its earlier answer was put first, marked SAME QUESTION, whatever its score.
    - `formatting.asks_on_its_own`: a follow-up, or anything of fewer than four words, is never matched by its words alone.
    - A kept plan is keyed by the planner too (its prompt and model) and by the question's section.
  - **A chat turn about a questionnaire deleted while it ran was lost**: its save failed on the foreign key (reproduced). `conversations.save` now saves it without the questionnaire.
  - **Kept plans outlived what wrote them.** They are cut to today's `MAX_SEARCH_QUERIES`, a one-line reply is not kept as a plan, and a new planner prompt or model plans again.
  - **The evaluations read and wrote kept plans**, so the house set's wording would have reached `data/app.db`. The `eval` package turns `REUSE_SEARCH_PLANS` off for every runner.
  - **With the reranker's order, the same question's earlier answer was cut.** It is now kept before the cut.
  - **Deleting a questionnaire left its questions' wording in the kept plans.** It takes them now.
  - **The retention pass deleted what was opened after it listed it.** It checks last use again first.
  - Recorded rather than fixed: TD-078, a file removed under a new read of the same file.
- Also while merging: `tools.answer` passes `product_id` only for a product again, as General's call always was. Two tests pinned it.
- 2026-11-07: tested end to end at the user's request ("Test the system from A to Z and make sure it is ready to be used"): plan 035's A-to-Z run, the real app and model on a copy of the local data, 20 of 20 steps passed, with no page or server errors. Plan complete.

## Decision log

- 2026-11-07, by the user: no verbatim reuse. Build the same searches, confirmed answers first, and no invented names, each measured.

## How to test it yourself

On your local copy. Start the app with `uv run python -m uvicorn src.api:app --reload` and open http://127.0.0.1:8000.

1. On the Workbench, choose General, type "Do you have a documented incident response plan, and how often is it tested?" and answer it. Then Close, type the same question again, and answer it again. Both answers cite the same clauses: the second was searched with the first's plan.
2. Ask "Do you implement Network Access Control (NAC) to restrict unauthorised devices?". The answer says what our policies say, "network access controls", and does not claim a product called NAC unless a source names it.
3. Approve an answer to a question on the Workbench. Then answer a questionnaire with the same question, word for word. The earlier answer is first among the card's sources, and the new answer keeps its position.
4. Optional: set `REUSE_SEARCH_PLANS=false` in `.env` and restart. The same question is then planned afresh each time, as before.
