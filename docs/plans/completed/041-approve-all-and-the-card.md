# Plan 041: Approve all, and the answer card redrawn

**Status:** completed 2026-11-08

## Goal

The user's request: "after second thought lets add the Approve all button, but make it with a confirmation, and not stored into the answer-memory. Also A friend of mine took a look on the answers cards (the review stage at chat and workbench) and said that it is confusing, overwhelming and overall bad UX/UI, so lets redesign them to solve these issues. Also you can redesign any page that seems like it."

What was wrong with the card, read from screenshots of a realistic review:

- The reason an answer was held was said three times: the chips, "Not going into the file yet", "Why this is flagged". "Why the confidence is low" made a fourth.
- Up to six coloured boxes on one card, so nothing stood out. The answer, the thing being judged, was the least prominent.
- The actions were small words above the answer, in three different places, and Approve looked like the others. A failed answer offered an Approve the server always refuses.
- Above the first card: four tiles, the length and skills, a notice, five tabs, the counts twice, and a line of keys. The finished Answer step stayed open as well.

## Acceptance criteria

- [x] Approve all, on the Workbench and in the chat's answers panel, with the number of answers it would approve.
- [x] It asks first, in the page: how many, that they go in under the person's name though nobody read them one by one, that they are not added to the answer memory, and how many failed questions stay. Cancel has the focus.
- [x] It approves only the answers the confirmation counted that are still held back and have words to write. Confident, failed, blank, set-aside and already-approved answers are left alone.
- [x] Nothing it does reaches the answer memory, whoever wrote the words. Each approval is on the record, marked `bulk`.
- [x] A card is: status and why in one line, the question, the answer, the sources, then Approve and Edit. Only the status is coloured.
- [x] The reasoning, the checks, the draft before rewording and the question's kind are behind "Why this answer".
- [x] Full or Brief for one answer, Leave blank, Set aside and Remove are behind "More", which closes on Esc or a click elsewhere.
- [x] A card offers only what can be done: no Approve with no answer, "Try this question again" first on a failed one, "Write an answer" on a blank one, "Include it again" on one set aside.
- [x] Above the cards: the counts in one line of text, beside the length and skills. The tabs and the bar stay, with empty tabs drawn quieter. The keys' line moves below the cards. The step's duplicate count goes.
- [x] The Answer step folds to one line once every question has a card.
- [x] English and Arabic, light and dark, wide and phone. `uv run poe check` passes.

## Plan

1. `questionnaire.approve_held` (`tools.py` is at its size ceiling) and `POST /api/forms/{id}/approve-all`, with tests.
2. The card in `cards.js` and `cards.css`, the shared confirmation, Approve all on both pages.
3. What is above the cards, the Answer step's fold, the Arabic.
4. The tests that pinned the old layout, new ones for the new one, docs, the gate.

## How to test it yourself

Open a questionnaire on the Workbench and answer it, or attach one in the chat. Each card now reads top to bottom: status, question, answer, sources, Approve and Edit. Click "Why this answer" for the reasoning, "More" for the rest. Click "Approve all": the dialog says how many, and that they are not added to the answer memory. Cancel changes nothing. Confirm, and they move to "Done by a person"; the Answer memory page has no new entries.

## Progress log

- 2026-11-08: done as above. The Knowledge base, Answer memory and Products pages were looked at with the same eye and left alone: each is one job, and reads as one. Preferences is long and opens with two boxes explaining the panels below them; not changed, and offered to the user. On a phone the top bar's six links took a quarter of the screen and stayed there; it now scrolls away on the Workbench, and the review's bar stays.
- 2026-11-08: TD-083 recorded: a failed question counts as answered until the page is drawn again from the server.

## Decision log

- 2026-11-08: Approve all exists, with a confirmation, and writes nothing to the answer memory. This reverses plan 033's "There is no Approve all". (The user.)
- 2026-11-08: it approves what is under Needs review, not every answer. The others go into the file anyway, so an approval would change nothing for them but put a name on answers nobody read, and fill "Done by a person" with them. (Mine; the user can overrule it.)
- 2026-11-08: the ids the confirmation counted are sent, and the server takes only those, so an answer that changed in between is not swept up. (Mine.)
- 2026-11-08: the confirmation's sentence "under your name" is said plainly, as the record will say it. (Mine.)
- 2026-11-08: sources stay on the card rather than behind "Why this answer": checking a source is what a review is. The two-colour scheme and its key went; whether a source is a policy or a previous answer is said when it is opened. (Mine.)
- 2026-11-08: the confidence percentage stays on the card, small, because the team asked to see it. (Mine.)
- 2026-11-08: a question's place reads "Security, row 3", not "Security!3". (Mine.)
- 2026-11-08: the chat's assistant still refuses "approve all of them". The button is a person pressing it, and confirming. (Mine.)
