# Plan 039: Do Arabic and English get the same answer?

**Status:** completed 2026-11-08

## Goal

The team's feedback said the SLA question "produced different responses in Arabic versus English". Plan 030 took out the chat's rewording, which was the cause plan 029 found. Plan 034 measured each language against itself. Nobody had compared the two languages. The user asked for that check, and only the check.

## Acceptance criteria

- [x] The same questions are answered in English and in Arabic, including the team's NAC and SLA questions, on a copy of the local data.
- [x] Each language is run twice, so a difference between the languages can be told from a difference between two runs.
- [x] Every pair is read for substance: the same position and the same facts.
- [x] The hashes of the real `data/app.db` and `chroma_db/chroma.sqlite3` are the same after.
- [x] The result is in `docs/measurements/evaluation.md`, and what it found is recorded for the user. Nothing in the product is changed.
- [x] TD-080, the flaky Workbench search test that stopped the gate passing, is fixed, with a test that fails without the fix.
- [x] `uv run poe check` passes.

## Plan

1. A copy of `data/` and `chroma_db/`, and the hashes of the real ones.
2. Ten questions, English and Arabic, two rounds, General, through `answer_one_question`: 40 answers.
3. Compare within each language and across them. Read every pair.
4. Write it up.

## Progress log

- 2026-11-08: run at `6fbffd4`, on a copy, 40 answers, no failures. The real database and index hashed the same after. The probe and its report are outside the repository, as plan 034's were. The result is in [evaluation.md](../../measurements/evaluation.md#arabic-versus-english-plan-039).
  - All ten questions say the same thing in both languages, read pair by pair. The SLA question, the one the team reported, now gives immediate response and resolution within 2 hours in both.
  - The one difference between the languages in what happens to an answer: the business continuity answer was held in both Arabic runs and written in both English runs.
  - Found on the way: TD-082. The incident-response question's English searches found the regulator's guide and not our own policy, and the kept search plan repeated that.
- 2026-11-08: the gate failed twice in a row, on TD-080's test and nothing else, so TD-080 was fixed. The cause was the file list arriving between typing and Enter. A new test forces that order; it failed on the old page with "1 passage(s)" and no Enter pressed.

## Decision log

- 2026-11-08: only the check, no fixes; the other two gaps from the team's feedback (technical terms on screen, delete buttons beside routine ones) are not worth doing now. (The user.)
- 2026-11-08: fix TD-080 before committing, after it failed the gate twice. (The user.) The change keeps a search again on a change of scope when words were already in the box, as the Workbench's tests pin. (Mine.)
- 2026-11-08: General only, ten questions, two runs each: the size of one round of plan 034. The agreement was judged by reading, because a word-level comparison across two languages says nothing. (Mine.)
