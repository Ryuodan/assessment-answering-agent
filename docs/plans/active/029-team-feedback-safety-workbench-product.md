# Plan 029: The team's feedback, part 1: safety fixes, Workbench relief, product choice

**Status:** active

## Goal

The team used the deployed system for two weeks and sent feedback on the
interface and the answers (2026-11-05). We checked each point against the code,
the running app and a small paid test, and found one problem the team did not
report: the Workbench's Fill writes held-back answers into the customer's file.

This plan does the first three steps of the agreed order. When it is done:

- nothing reaches a customer's file that the review gate holds back unless a
  person says so;
- a person's work on the Workbench survives a reload, a re-upload and a long
  run;
- reviewing goes straight to the answers that need it;
- a questionnaire or a chat is never for General by accident.

Each item can be tested by the user in the browser. The user tests this plan
before the next round starts.

## The feedback, checked

Recorded without customer names. The analysis and its evidence stay in the
session's scratchpad; this is what it found.

- **Home is the chat; upload is hidden.** True. Decision below: the chat stays home.
- **The Workbench opens on knowledge-base admin.** True: the whole first screen is knowledge-base tools.
- **The chat shows no confidence; answers differ between chat and Workbench.**
  - Partly true. The chat shows confidence on questionnaire answers, not on typed questions.
  - The chat model rewrites the drafted answer. In one Arabic test, the rewrite contradicted a correct draft.
- **Product defaults to General and sometimes resets.** True, and reproduced.
- **Review is slow: big cards, no filter, no bulk approval.**
  - The slowness and the missing filter are true.
  - "Edit then Approve" is not needed to fill.
  - "Approve all" would release only the held answers, the risky half, under a person's name.
- **Answers lost after a refresh.** Partly true.
  - File questionnaires are saved but not reopened.
  - A re-upload creates an empty copy.
  - Typed and PDF lists are lost.
  - A run's answers are saved only at its end, and a large run outlasts the proxy's 15 minutes.
- **The same question gives different answers.**
  - NAC: true. In three runs the "Yes" held, but the wording and the confidence varied.
  - SLA: the Arabic and English answers differed in the chat only.
- **English-only interface, technical terms, delete buttons beside routine ones.** True.
- **Not reported by the team:** the Workbench's Fill sends `include_unreviewed: true` on every click (TD-052).

## Acceptance criteria

Stage 0, safety fixes:

- [x] **0.1** Filling from the Workbench writes only what the gate allows. Held answers are reported with their count and reasons, and written only through "Write them in anyway". The FILE_FILLED event records whether the gate was bypassed and how many answers were held. A read-only command lists the questionnaires filled with held answers before the fix.
- [x] **0.2** Withdrawing an approval puts back the answer's review flag and reasons as they were before the approval.
- [x] **0.3** Removing a shared knowledge-base document, or clearing a knowledge base, on the Workbench asks first and says what is affected.
- [x] **0.4** Forgetting a chat asks first and names it. The control is a real button that can be reached with the keyboard and is not nested in another button.
- [x] **0.5** Edit on a Brief card edits the brief text that is shown.

Stage 1, Workbench relief:

- [ ] **1.1** Reloading the page reopens the open questionnaire. "Or pick up" lists every questionnaire of the person, most recently used first.
- [ ] **1.2** Uploading a file the person already has as a questionnaire offers to open it, or to start fresh.
- [ ] **1.3** A "Needs review" filter with counts shows first the answers the gate holds back, plus failed ones. A fixed bar keeps Fill and the counts in reach.
- [ ] **1.4** Each answer is saved as it finishes. A second run on a questionnaire that is still being answered is refused. Reopening it shows the progress.
- [ ] **1.5** Leaving the page with an unsaved answer or unsaved typed answers asks first.

Stage 2, product choice:

- [ ] **2** The Workbench and the chat start with no product chosen. General is one of the choices, and reading a questionnaire or starting a chat waits for a choice. "Last used" fills the choice in one click and is never preselected. The chosen product shows as a label.

All stages:

- [ ] Every fix has a test that fails without it. `uv run poe check` passes. Tech-debt, ARCHITECTURE.md, decisions and the generated docs are updated.
- [ ] Each item has a "How to test it yourself" note for the user.

## Plan

1. Design each stage against the code (three read-only designers).
2. Settle the contracts between the server and the pages, then write them here.
3. Build. Server-side work and the chat page can go in parallel; the Workbench page comes after the server work it uses.
4. Review each change adversarially, fix, merge, and run `uv run poe check`.
5. Update the docs, the tech-debt records and the user's test notes, and commit.
6. The user tests. Their findings go into this plan's log.

## Progress log

- 2026-11-05: the feedback was checked by six readers, a synthesis and a critic. The user chose the scope of this round, and three designers started.
- 2026-11-05: the three designs are ready (in the session's scratchpad). No item needs a database migration.
  - Room in modules at their size ceilings comes from behaviour-neutral moves:
    - `length_of` and `written_text` move to `selection.py`;
    - the questionnaire routes move to `src/routes/forms.py`;
    - `in_house_style` moves to `src/styling.py`;
    - the Word preview moves to `src/docx_preview.py`, which resolves TD-019.
  - The build goes stage by stage, each stage reviewed and fixed before the next starts.
- 2026-11-05, Stage 0 build:
  - `length_of` and `written_text` moved into `selection.py`, behaviour unchanged (164 existing tests pass).
  - 0.1 and 0.5, server side. `fill` records what the gate held (`held_back`) and whether "Write them in anyway" was used (`include_unreviewed`); the "nothing written" message names held answers (TD-054); an empty brief is refused (TD-055). 4 unit tests, each failing on the old code. `tools.py` ceiling 1,373 to 1,366. New debt found: TD-056 to TD-058.
  - 0.1b, the read-only audit: `python -m src.cli inspect fills [--team T] [--json]` (`src/fill_audit.py`, operations layer). It lists the fills that wrote held answers (certain when the answer is unchanged since the fill, unknown when it was saved after) and the approvals withdrawn before the fix that still pass the gate. 11 tests in `tests/test_fill_audit.py`, one of them proving that the audit changes no row.
  - 0.2: an approval keeps the review flag and reason it replaced (`before_approval` in the answer's JSON, no migration); withdrawing restores them, and rewording an approved answer withdraws it the same way (TD-053 resolved). 9 tests: 7 unit (5 failing on the old code), 1 API, 1 browser (failing on the old code). `poe gen` added the field to openapi.json; `poe snapshots` added `"before_approval": null` to the two pipeline snapshots and nothing else. `tools.py` ceiling 1,366 to 1,365. New debt found: TD-059 (putting back the draft of an approved answer releases it).
  - 0.1, the Workbench page: Fill sends `include_unreviewed: false` (the request opens the gate only for an exact `true`); the held answers are counted, listed under "Which, and why" with their reasons, and written only through "Write them in anyway", whose confirm counts them; afterwards the first line says how many unconfirmed answers went in. TD-052 resolved. 2 browser tests, both failing on the old page.
  - 0.3: removing a shared document on the Workbench asks first and says that every questionnaire and chat, General and every product, stops using it, and that its file stays. "Remove every policy document" counts them. The chat drawer asks the same question, from one wording in `cards.js` (`Cards.removalQuestion`, `Cards.clearQuestion`). A product's document keeps today's wording. 3 browser tests, all failing on the old pages.
  - 0.4: each conversation in the chat's history is two sibling buttons, the conversation and Forget (✕, named "Forget “title”" for screen readers). Forget asks first, names the conversation and its time, says it cannot be recovered and that its questionnaire and answers are kept; a failed delete says so under the list. The ✕ shows on hover, on keyboard focus, and always on touch screens. 3 browser tests in `tests/browser/test_chat_history.py`, all failing on the old page; the history width test and the five tests that read the rows pass unchanged.
  - 0.5, the pages: the card's hook is now `Cards.shownAnswer(item, index) -> { text, which }`. The editor opens on the text the card shows (the brief on a brief card) and says which back to the page, which saves that one. An emptied brief is not sent: it comes back, with a note pointing to Leave blank. Both pages. 4 browser tests (3 on the Workbench, 1 in the chat), all failing on the old pages.
  - The first full `poe check` failed once in the browser task: the existing product-removal test in `test_knowledge_scope.py` timed out, and passed on its own and in a second full browser run. The cause was a race in the Workbench, older than this plan: the page's first, shared, knowledge request could come back after the product's and replace the list under a selector that said the product (TD-060). It also made 0.3's count wrong, so the Workbench now drops an answer for a knowledge base the selector has left. 1 browser test, failing on the old page. D-020 records the review-gate choices of 0.1 and 0.2.
  - Stage 0 done, waiting for review and the user's test. `uv run poe check`: every task passed (fmt, lint, types, arch, docs, rules 94, test 2,159 passed and 2 skipped, browser 53). Stage 0 added 38 tests: 24 unit and API, 14 browser.

## Decision log

- 2026-11-05, by the user: the chat stays the home page. Its upload is to be made more obvious, in a later round. The Workbench becomes the questionnaire front door, redesigned in a later round.
- 2026-11-05, by the user: this round is the safety fixes, the Workbench relief and the product choice. Each is tested by the user before the next round.
- 2026-11-05, by the user, on product choice: there is no silent General. General stays a deliberate choice, with a one-click "last used".
- 2026-11-05, Claude, on defaults the designs proposed and the user has not yet seen. Each can be reversed after the user's test.
  - **0.1:**
    - The fill event records what the gate held, and whether "Write them in anyway" was used.
    - The "nothing written" message says that answers are held back, when they are.
    - A read-only command (`inspect fills`) lists the questionnaires filled with held answers before the fix. The user decides what to tell the team.
  - **0.1, after the review of Stage 0:**
    - "Write them in anyway" writes only the held answers it listed and counted. An answer held after that list was made (an approval withdrawn, a question answered) stays out and is offered again. The first line says how many went in, as the server counted them.
    - `inspect fills` lists an answer cleared after a fill, and a fill of a questionnaire that is gone, as unknown, rather than leaving them out.
  - **0.2:**
    - An approval keeps the review flag and reasons it replaced, and a withdrawal restores them.
    - Rewording follows the same rule.
    - Answers released by a withdrawal before the fix are listed, not repaired.
    - After the review of Stage 0: approving one of those answers records what the review's own rule says, not the flag the old withdrawal cleared, so withdrawing that approval holds it back again.
  - **0.3 and 0.4:** they ask first. Who may remove shared documents, and an Undo for forgetting a chat, are for a later round.
  - **TD-060, fixed during the build without asking first:** the Workbench drops a knowledge-base list that arrives for a scope the selector has left, and forgets the count of "Remove every policy document" until the chosen list arrives. Why now: the late list made an existing gate test fail at random, and made 0.3's count name another knowledge base. The chat drawer's same race (`loadSources`) is recorded and waits for approval.
  - **0.5:** an empty brief is refused.
  - **1.1:**
    - "Last use" means last change (`form_batches.updated_at`).
    - Every questionnaire is listed, up to 500, in a scrolling list.
    - A `?q=` link opens only for its owner.
  - **1.2:**
    - The same file means the same bytes as one of this person's questionnaire files still on disk.
    - It is checked before the file is read. A match on another product is offered with its badge, and "Start fresh" stays one click away.
  - **1.3:**
    - The tabs are Needs review (the default when it has anything), Will be written, Done by a person, Blank or set aside, and All.
    - "Write them in anyway" appears only after Fill.
    - The question list folds once answers exist.
  - **1.4:**
    - One run at a time per questionnaire, held in the server's memory (one process serves).
    - A run carries on after a reload or a timeout, as today.
    - Reopening shows the answers saved so far and a counter.
  - **1.5:** warn only, never save half-typed text automatically.
  - **2:**
    - "Last used" is derived from the person's own saved questionnaires and chats; nothing new is stored.
    - A new chat started from a product chat suggests that product without choosing it.
    - Close questionnaire and Clear all go back to "choose…".
    - In the chat, a file can be attached before choosing; only Send waits.
    - Reading any file waits for a product, and the Read button names it.
    - A team with no products still chooses General explicitly.
    - The server is unchanged: scripts and the API can still answer as General without saying so (a tech-debt item).

## How to test it yourself

Use a local copy of the app, not the server the team uses. Each item says what to do and what you should see.

### 0.1 Fill keeps back the answers nobody has confirmed

1. Open the Workbench. Upload a questionnaire, click Read, then Answer.
2. Look at the cards. Some should say "needs review" or show a low confidence, with "Not going into the file yet." (A real run usually has several.)
3. Click "Fill the original file". You should see "N answer(s) were held back…", a "Which, and why" line and a "Write them in anyway" button.
4. Click "Which, and why". Each held question is listed with its number, the start of its text and the reason it was held.
5. If anything was written, click "Download the filled file" and open it. The held questions are empty, or keep what the file already had.
6. Click "Write them in anyway". A question asks first and counts them. Click Cancel: nothing changes. Click the button again and OK: the first line says "Wrote … including N answer(s) nobody has confirmed". Download again: those cells are now filled.
7. Answers can change after Fill. Click Approve on two held cards, then Fill: the panel says 2 fewer were held back. Click "Approved ✓" on one of those two cards to withdraw it. Now click "Write them in anyway": the question still counts the answers in the list, and after OK the first line says that many went in. The card you withdrew was not in the list, so it is not written: the panel says "1 answer(s) were held back" and offers "Write them in anyway" for it alone.

### 0.1b Which files were already filled with held answers

For whoever runs the server, in the app's folder:

1. Run `uv run python -m src.cli inspect fills` (add `--team <team>` for another team). It changes nothing.
2. It lists each fill that wrote answers the review gate holds back. Older Workbench fills say "before the fix"; the fill from step 6 above says "4 written anyway" (the number it wrote).
3. Under each fill: how many held answers are unchanged since the fill (these certainly went into that file), and how many were saved or cleared after it (unknown). A fill of a questionnaire that is no longer on the server is listed too, as "questionnaire no longer on the server": what it wrote is not known.
4. At the end: answers whose approval was withdrawn before the fix and that still go into the file as if confident. Open each on the Workbench, and edit or approve it. If you approve one and then withdraw the approval, it is held back again ("needs review"), and the command no longer lists it.

### 0.2 Withdrawing an approval holds the answer back again

1. On the Workbench, open a questionnaire with a card marked "needs review", ideally one with a high confidence beside it.
2. Click Approve. The card says "Approved ✓", and its "Not going into the file yet." note goes.
3. Click "Approved ✓" to withdraw. The message says "It will be held back until somebody edits or approves it". The card shows "needs review" and the same reason as before.
4. Fill the file. That question is under "Which, and why".
5. Reload the page and reopen the questionnaire from "Or pick up": still held.
6. Approve it again, then reword it (for example "make it shorter"). It comes back held.
7. Edit a card's text yourself, Approve it, then withdraw: it still goes into the file, because a person wrote it.

### 0.3 Removing from the shared knowledge base asks first

Use a local copy, not the team's data.

1. On the Workbench, step 1, with the knowledge base set to "Shared, for every product", click "remove" beside a document. A question names the document, says that every questionnaire and chat (General and every product) stops using it, and that its file stays on the server. Click Cancel: it is still listed.
2. Click "Remove every policy document". The question says how many ("the 1 policy document", "all 12 policy documents"). Click Cancel. Change the selector to a product and click it again at once, before the product's list appears: the question says "every policy document", never the shared count. Once the list is shown, it says the product's count.
3. On the chat page, open the knowledge-base drawer and click "remove" on a shared document. You see the same question. Click Cancel.
4. Choose a product in the selector and remove one of its documents. The question names the product and says its file is deleted too, as before.

### 0.4 Forgetting a chat asks first

1. Open the chat. In the history list, point at a conversation: an ✕ appears at its right.
2. Click ✕. A question names the conversation (and its file, if it has one) and says it cannot be recovered. Click Cancel: it is still there. Click ✕ again and OK: it is gone.
3. With the keyboard: click a conversation, then press Tab. The ✕ of that row shows, highlighted. Press Enter: the same question. Click Cancel.
4. Still with the keyboard, on a conversation that is not the open one: press Tab to reach its ✕, press Enter, then OK. The conversation goes, and the keyboard is on the conversation below it (or the last one): press Tab and its ✕ is highlighted.
5. On a phone or tablet the ✕ is always shown, and tapping it asks first.

### 0.5 Edit on a Brief card edits the brief

1. On the Workbench, open an answered questionnaire and set "Answers" to Brief. The cards show short answers.
2. Click Edit on a card. The box holds the short answer you see, not the long one.
3. Change a word and click "Done editing". The card shows your short answer, and the status says your edit is saved.
4. Set "Answers" to Full: the long answer is as it was.
5. Back to Brief, fill the file and download it: the cell has your short answer.
6. Edit a Brief card, delete all its text and click "Done editing". It is refused with a note pointing to "Leave blank", and the short answer comes back. With a screen reader on (Narrator: Ctrl+Win+Enter), the note is read out when it appears.
7. In the chat's answers panel, set Brief and repeat steps 2 and 3.
