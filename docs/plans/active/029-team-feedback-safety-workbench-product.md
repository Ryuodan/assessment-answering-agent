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

- [ ] **0.1** Filling from the Workbench writes only what the gate allows. Held answers are reported with their count and reasons, and written only through "Write them in anyway". The FILE_FILLED event records whether the gate was bypassed and how many answers were held. A read-only command lists the questionnaires filled with held answers before the fix.
- [ ] **0.2** Withdrawing an approval puts back the answer's review flag and reasons as they were before the approval.
- [ ] **0.3** Removing a shared knowledge-base document, or clearing a knowledge base, on the Workbench asks first and says what is affected.
- [ ] **0.4** Forgetting a chat asks first and names it. The control is a real button that can be reached with the keyboard and is not nested in another button.
- [ ] **0.5** Edit on a Brief card edits the brief text that is shown.

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

## Decision log

- 2026-11-05, by the user: the chat stays the home page. Its upload is to be made more obvious, in a later round. The Workbench becomes the questionnaire front door, redesigned in a later round.
- 2026-11-05, by the user: this round is the safety fixes, the Workbench relief and the product choice. Each is tested by the user before the next round.
- 2026-11-05, by the user, on product choice: there is no silent General. General stays a deliberate choice, with a one-click "last used".
- 2026-11-05, Claude, on defaults the designs proposed and the user has not yet seen. Each can be reversed after the user's test.
  - **0.1:**
    - The fill event records what the gate held, and whether "Write them in anyway" was used.
    - The "nothing written" message says that answers are held back, when they are.
    - A read-only command (`inspect fills`) lists the questionnaires filled with held answers before the fix. The user decides what to tell the team.
  - **0.2:**
    - An approval keeps the review flag and reasons it replaced, and a withdrawal restores them.
    - Rewording follows the same rule.
    - Answers released by a withdrawal before the fix are listed, not repaired.
  - **0.3 and 0.4:** they ask first. Who may remove shared documents, and an Undo for forgetting a chat, are for a later round.
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
