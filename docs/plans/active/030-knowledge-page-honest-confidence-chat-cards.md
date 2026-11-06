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

- [x] A Knowledge base page holds what the Workbench's step 1 held:
  - adding documents, with the "ours or external" question and the Shared-or-product choice;
  - each knowledge base's list, with view, remove and clear, and plan 029's confirmations;
  - the document library.
- [x] Every page header links to it. It works under the server's `/assessment/` prefix.
- [x] The Workbench opens on the questionnaire. One line says what the answers draw on, for example "Answers from 63 shared documents and 12 for Msegat", and links to the page.
- [x] Citations still open their clause from the Workbench and the chat.

Honest confidence:

- [x] An answer held by a check never shows a score above the review threshold; one the reviewer found not grounded shows 0.3 at most.
- [x] The release decision is unchanged for every answer. A test on recorded pipeline results proves it.
- [x] The card shows the status first, with the reason as a chip and the colour by status. The page takes the threshold from the server.

Answers as cards in the chat:

- [x] A question answered in the chat shows the drafted answer word for word, as a card, with its status, confidence and the clauses it cites. These are the cited clauses, not the top six found.
- [x] The assistant's own words around the card do not restate the answer.
- [x] The card is kept with the reply and drawn again when the conversation is reopened. Arabic answers read right to left.

All:

- [x] Every change has a test that fails without it. `uv run poe check` passes. The docs are updated: ARCHITECTURE.md, decisions, tech-debt, evaluation.md for confidence, and the generated docs.
- [x] A "How to test it yourself" section covers each item.

## Plan

1. Build the three items in parallel, each in its own branch with disjoint files where possible.
2. Review the merged change adversarially, then fix what the review finds.
3. Run `uv run poe check`, update the docs and the test notes, and commit.
4. The user tests. Their findings go into this plan's log.

## Progress log

- 2026-11-06: plan written. The confidence figures above were computed from the evaluation results on file: `eval/results/heldout_full.json`, `collision_before.json` and `collision_after.json`. No model calls were made.

- 2026-11-06: built in three parallel branches, merged into main.
  - **Knowledge-base page** (`7f13571`): `src/static/knowledge.html` at `/knowledge`, served by `routes/knowledge.py`. The Workbench opens on "1 Load a questionnaire", with the summary line. 8 browser tests moved to the page and 11 are new.
  - **Honest confidence** (`0daf3c9`, `49af535`, `c4388ab`):
    - `verification.held_confidence` and `held_by_score`, used by every comparison;
    - the drafter's conflict check moved into `assess`;
    - `review_threshold` added to the session;
    - the status-first card.
    - Re-recording the snapshots changed exactly two capped scores (0.9 to 0.6 for sources that disagree; 0.8 to 0.3 for not grounded).
    - On the evaluation runs on file: 0 decisions changed, and 19 held answers on the held-out set lost a score of 0.75 or more.
  - **Answer cards in the chat** (`f8938c6`): `src/agents/assistant_cards.py`, `direct_answers` on the reply, and `Cards.renderReadOnly`. 10 unit tests and 5 browser tests. The model-facing text changed, so the paid assistant evaluation should be run again (not run).
  - The merge had one conflict, in `cards.js`'s list of exports, where both sides were kept. `uv run poe check` passed on the merge: 2,265 tests and 132 browser tests.
- 2026-11-06: an adversarial review of the merged change. Fixed:
  - **The chat's reason for a held answer** contradicted its card. "Low confidence" was given to the model for an answer held by "sources disagree" or "only previous answers". Both the note to the model and the stopped-turn text now use `assistant_stopped.held_because`, which gives the card's reasons. 2 tests, failing before.
  - **`inspect fills` judged past fills by today's rule.** It dropped an unflagged answer at exactly the threshold, which fills until plan 030 wrote. It now judges them by the gate they ran under. The test that pinned the omission is inverted.
  - **The "nothing changes" claims** in `selection.py` and D-024 now state the one difference. An unflagged answer at exactly the threshold is now held, the safe side; only a withdrawn approval (TD-053) or a changed threshold can leave one.
  - **A stopped turn** no longer restates answers its cards show. It says how many it drafted, "shown below". 7 tests that pinned the old relay were changed deliberately.
  - **The chat's drawer button** is "Documents", so the bar no longer has two controls both called "Knowledge base".
  - **"Add documents"** on the new page can be reached with the keyboard. 1 browser test, failing before.
  - **The signed-out session shape's comment** is true again.
  - Recorded rather than fixed: TD-071.

## Decision log

- 2026-11-06, by the user: this round is the knowledge-base page, honest confidence and answer cards in the chat. The user asked for the confidence mechanism to be explained and shown to be reliable; that is the section above.
- 2026-11-06, Claude, on defaults the user has not decided (each can be reversed):
  - The page is "Knowledge base" at `/knowledge`.
  - Who may remove or clear shared documents is unchanged (any member).
  - The chat's knowledge-base drawer stays, with a link to the page; replacing it with the link is for later.
  - A held answer's score is capped at the threshold, and at 0.3 when the reviewer found it not grounded.
  - Chat cards for questions asked in the chat are read-only: they have no questionnaire to approve into.

## How to test it yourself

On your local copy. Start the app with `uv run python -m uvicorn src.api:app --reload` and open http://127.0.0.1:8000.

### The Knowledge base page

1. Open the Workbench. The first step is "1 Load a questionnaire"; the knowledge-base tools are gone from it. Under the product box: "Answers from N shared documents · Manage".
2. Choose a product, say Msegat. The line reads "Answers from N shared documents and M for Msegat" (or "and none for Msegat"). Choose "General (shared policies only)": only the shared count.
3. With Msegat chosen, click "Manage". The Knowledge base page opens on Msegat, and the address ends with `?product=…`. Reload: it stays on Msegat. Choose "Shared, for every product": the address drops `?product=`.
4. Add a PDF: drop it on Guidelines (or press Tab to the "Drop PDF or DOCX files here" box and press Enter), pick "Ours" or "A requirement we are subject to", and click "Index guidelines". It is listed under "What is indexed".
5. Click "remove" beside a shared document: the same question as before, which you can cancel. "Remove every policy document" asks with the count.
6. Every page's header has "Knowledge base" between Workbench and Answer memory. In the chat, the drawer button is now "Documents", and its drawer has "Manage on the Knowledge base page".
7. On the Workbench, open an answered questionnaire and click a citation, then "open document": the clause and the document still open there. Search still works.

### Honest confidence

1. Answer a questionnaire on the Workbench. Every card now starts with a coloured strip:
   - "Will be written" for answers going into the file;
   - "Needs review", with chips saying why, for example "Sources disagree", "Not backed by our documents", "Only from previous answers" or "Low confidence".
2. On a card drafted from now on, a "Needs review" score is never above 60%, and 30% at most when the chip is "Not backed by our documents". "High confidence" appears nowhere on a card. Answers stored before this change keep their old number (TD-068), but now under a "Needs review" strip.
3. The "Needs review" tab and the "N will be written · N need review" line count the same answers as before for the same questionnaire. Nothing moved between them.
4. Approve a held answer: the strip turns to "Done by a person". Leave one blank: "Left blank", with no percentage.
5. A question typed on the Workbench with no file shows "Ready to use" instead of "Will be written", because it goes into no file.

### Answers as cards in the chat

1. On the Assistant page, choose a product (or General), type "Do we encrypt customer data at rest?" and send.
2. Under the assistant's one-line reply, a card shows:
   - the answer word for word;
   - its strip ("Ready to use" or "Needs review" and why) and its percentage;
   - the clauses it cites.

   The reply does not repeat the answer.
3. Click a source chip on the card: the clause opens. The card has no Approve, Edit, Leave blank or ✕.
4. The sources line under the reply counts only the clauses the answer cites.
5. Ask the same question in Arabic in a new chat: the card reads right to left.
6. Open another conversation, then this one again from the list: the card is drawn again. A conversation from before this change opens as it did.
7. If an answer needs review, the assistant's sentence gives the same reason as the card's chip.
