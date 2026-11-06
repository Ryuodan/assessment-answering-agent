# Plan 030: The team's feedback, part 2: knowledge-base page, honest confidence, answers as cards in the chat

**Status:** active

## Goal

The second round of the team's feedback (plan 029 has the first). When it is
done:

- **The Workbench is about questionnaires.** The knowledge base is managed on a
  page of its own.
- **The confidence shown agrees with what happens to the answer.** An answer held
  for review never shows "High".
- **A question answered in the chat shows the drafted answer word for word,** as
  the Workbench shows it: the same card, with its status, confidence and the
  clauses it cites.

The user tests this round before the next.

## Confidence today, and what "honest" changes

How an answer's confidence is made today (`src/graph/nodes.py`, `src/verification.py`):

1. **The score.** The drafter rates its own answer, and a second model call, the
   reviewer, rates it too. The score is the lower of the two.
2. **The checks.** Five of them can hold an answer for review:
   - an answer that cites clauses its sources do not hold;
   - one that holds only part of a split source;
   - one that rests only on our previous answers;
   - one the reviewer did not find grounded in its sources;
   - one whose sources disagree with what we said before.

   Only the first two lower the score, to 0.5. The others set "needs review"
   and leave the score as rated.
3. **The gate.** An answer is held back from the customer's file when it is
   flagged or its score is 0.60 or less (`REVIEW_CONFIDENCE_THRESHOLD`). Held
   answers go in only when a person edits or approves them, or uses "Write them
   in anyway".

How reliable is it? These figures come from evaluation runs already on file, so
no new model calls were made. They compare each answer with what the team
actually wrote, on questionnaires the system never saw. The held-out set had 135
questions; the two dev-split runs from plan 027 had 82 each:

| | held-out set | dev split, after plan 027 |
|---|---|---|
| **Released** to the file | 72: 4.79 of 5 agreement, 1 contradiction (1%) | 47: 4.81, 1 (2%) |
| Held, low score | 44: 3.61, 9 contradictions (20%) | 24: 2.88, 9 (38%) |
| **Held by a check, showing 0.85 or more** | 17: 4.18, 2 contradictions (12%) | 8: 4.38, 1 (12%) |

So **the decision is reliable**: what the gate releases contradicts the team 1 to
2 times in 100, and what it holds 17 to 29 times in 100. **The number is not.**
One held answer in eight shows "High confidence 85%+", and those contradict the
team about ten times as often as released ones. A reviewer who sorts or trusts by
the number is misled exactly where it matters.

What this plan changes:

- **A held answer's score is capped.** When a check holds an answer, its score
  is capped at the review threshold, so it can never show above "needs review".
  The reviewer saying "not grounded" caps it at 0.3, the range the reviewer's own
  instructions give for an ungrounded answer (`prompts.py`).
- **The decision does not move.** These answers are already held, so the same
  answers are released and held as today. Only the number they show changes. A
  characterization test pins that the release decision is identical before and
  after.
- **The status comes first** on the card: "Will be written", or "Needs review",
  with the reason as a chip ("Sources disagree", "Not backed by our documents",
  "Only from previous answers", "Partial source", "Low confidence"). Colour
  follows the status, not the score.
- **One threshold.** The page reads it from the server instead of a hard-coded
  0.6, and every comparison uses the same rule.

What it does not change: the same question can still get a different score, or
even a different decision, on another run (three NAC runs gave 0.86, 0.20 and
0.65). That is the consistency work of a later round, by reusing answers a person
has confirmed. Confidence is a model's rating checked by a second model and by
rules, not a probability. Its value is in the release decision, which is measured
above.

## Acceptance criteria

Knowledge-base page:

- [ ] A Knowledge base page holds what the Workbench's step 1 held:
  - adding documents, with the "ours or external" question and the Shared-or-product choice;
  - each knowledge base's list, with view, remove and clear, and plan 029's confirmations;
  - the document library.
- [ ] Every page header links to it. It works under the server's `/assessment/` prefix.
- [ ] The Workbench opens on the questionnaire. One line says what the answers draw on, for example "Answers from 63 shared documents and 12 for Msegat", and links to the page.
- [ ] Citations still open their clause from the Workbench and the chat.

Honest confidence:

- [ ] An answer held by a check never shows a score above the review threshold; one the reviewer found not grounded shows 0.3 at most.
- [ ] The release decision is unchanged for every answer. A test on recorded pipeline results proves it.
- [ ] The card shows the status first, with the reason as a chip and the colour by status. The page takes the threshold from the server.

Answers as cards in the chat:

- [ ] A question answered in the chat shows the drafted answer word for word, as a card, with its status, confidence and the clauses it cites. These are the cited clauses, not the top six found.
- [ ] The assistant's own words around the card do not restate the answer.
- [ ] The card is kept with the reply and drawn again when the conversation is reopened. Arabic answers read right to left.

All:

- [ ] Every change has a test that fails without it. `uv run poe check` passes. The docs are updated: ARCHITECTURE.md, decisions, tech-debt, evaluation.md for confidence, and the generated docs.
- [ ] A "How to test it yourself" section covers each item.

## Plan

1. Build the three items in parallel, each in its own branch with disjoint files where possible.
2. Review the merged change adversarially, then fix what the review finds.
3. Run `uv run poe check`, update the docs and the test notes, and commit.
4. The user tests. Their findings go into this plan's log.

## Progress log

- 2026-11-06: plan written. The confidence figures above were computed from the evaluation results on file: `eval/results/heldout_full.json`, `collision_before.json` and `collision_after.json`. No model calls were made.

## Decision log

- 2026-11-06, by the user: this round is the knowledge-base page, honest confidence and answer cards in the chat. The user asked for the confidence mechanism to be explained and shown to be reliable; that is the section above.
- 2026-11-06, Claude, on defaults the user has not decided (each can be reversed):
  - The page is "Knowledge base" at `/knowledge`.
  - Who may remove or clear shared documents is unchanged (any member).
  - The chat's knowledge-base drawer stays, with a link to the page; replacing it with the link is for later.
  - A held answer's score is capped at the threshold, and at 0.3 when the reviewer found it not grounded.
  - Chat cards for questions asked in the chat are read-only: they have no questionnaire to approve into.
