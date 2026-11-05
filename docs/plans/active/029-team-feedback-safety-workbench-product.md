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

- [x] **1.1** Reloading the page reopens the open questionnaire. "Or pick up" lists every questionnaire of the person, most recently used first.
- [x] **1.2** Uploading a file the person already has as a questionnaire offers to open it, or to start fresh.
- [x] **1.3** A "Needs review" filter with counts shows first the answers the gate holds back, plus failed ones. A fixed bar keeps Fill and the counts in reach.
- [x] **1.4** Each answer is saved as it finishes. A second run on a questionnaire that is still being answered is refused. Reopening it shows the progress.
- [x] **1.5** Leaving the page with an unsaved answer or unsaved typed answers asks first.

Stage 2, product choice:

- [x] **2** The Workbench and the chat start with no product chosen. General is one of the choices, and reading a questionnaire or starting a chat waits for a choice. "Last used" fills the choice in one click and is never preselected. The chosen product shows as a label.

All stages:

- [ ] Every fix has a test that fails without it. `uv run poe check` passes. Tech-debt, ARCHITECTURE.md, decisions and the generated docs are updated.
- [x] Each item has a "How to test it yourself" note for the user.

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
- 2026-11-05, review of Stage 0: the server changes and `inspect fills` behaved as designed. It found 2 major and 5 minor problems, reproduced in Chromium and with the suite's isolation. All 7 are fixed; none was rejected.
  - Major: "Write them in anyway" could write more than its confirm counted. The page counted the last Fill's list and the server wrote whatever was held at the click: an approval withdrawn in between went in under "Write 2" and "including 2" (3 were written). Fixed on the server: the request names the answers it counted (`unreviewed_ids`), only those are written, one held since stays out and is offered again, and the first line shows the server's count (`written_anyway`, also in the event).
  - Major: the 0.4 note's keyboard steps ("click a conversation, then press Tab") did not work. Opening or forgetting a conversation rebuilt the list and dropped focus to the page. The list now puts focus back on the same control of the same conversation, or on the next one after a Forget.
  - Minor, fixed: the clear count named the previous knowledge base's number while a product's list loaded; approving an answer the old withdrawal released recorded the cleared flag, so approve-then-withdraw released it again; the audit dropped answers cleared after a fill and fills of deleted questionnaires; the refused-brief note was silent to screen readers; TD-060's fix was missing from the decision log.
  - Room: `_nothing_written` moved into `selection.py` (`tools.py` ceiling 1,365 to 1,334 for the move, 1,347 after the fix), and the fill route moved into `src/routes/forms.py`, the first of the questionnaire routes the plan moves for Stage 1 (`api.py` ceiling 1,296 to 1,264). Both behaviour-neutral, each in its own commit, proven by the existing tests; `openapi.json` unchanged by the move. The mypy baseline went from 244 to 243.
  - 15 tests added, each failing on the old code: 10 unit and API (4 in `test_tools.py`, 1 in `test_api_forms.py`, 5 in `test_fill_audit.py`), 5 browser (1 in `test_workbench.py`, 1 in `test_knowledge_scope.py`, 3 in `test_chat_history.py`). Changed on purpose: the "Write them in anyway" browser test now expects the ids in the request; the empty-brief test also checks the live region.
  - `uv run poe check`, first run: every task passed except `test`, which had 1 failure, in an answer-memory test this round does not touch. That test passes only when two answers are recorded in the same second (TD-061, recorded and not fixed: it needs approval). Second run: every task passed (fmt, lint, types with 243 in the baseline, arch, docs, rules 94, test 2,169 passed and 2 skipped, browser 58).
  - Stage 0 waits for the user's test.
- 2026-11-05, Stage 1 build (in the order the design gives: 1.1, 1.5, 1.2, 1.4, 1.3):
  - 1.1: the Workbench writes the open questionnaire into its address (`?q=<id>`) and opens it again at start-up; Close and reading a PDF take it out. Someone else's, or one that is gone, opens nothing and says so. `GET /api/forms` lists last changed first (`updated_at`, which every write moves; no migration), and "Or pick up" lists every questionnaire, up to 500, in a scrolling box when there are more than three, each with when it last changed. 6 tests: 1 API and 4 browser, each failing on the old code, and 1 static guard that the address stays inside the prefix. The existing pick-up, close and deleted-product tests pass unchanged.
  - 1.5: leaving the Workbench asks first (the browser's own "Leave site?") while it holds work only the page has: an edit typed into a card and not yet saved, questions typed beside a file or into a list, or a question in "Ask another question". Nothing is saved on the way out. 4 browser tests: 2 fail on the old page, 2 guard against asking when everything is saved.
  - Room for 1.2 (R1, behaviour-neutral, its own commit): opening, listing and reading a questionnaire (`POST /api/forms`, `GET /api/forms`, `GET /api/forms/{id}`) moved into `src/routes/forms.py`, as a second router included where the routes were. `poe gen` left `openapi.json` and `api.md` byte-identical; 195 existing tests over the routes, the error responses and the pages pass unchanged. `api.py` ceiling 1,264 to 1,225.
  - 1.2: `POST /api/forms` takes `if_already_open` ("new", the default and today's behaviour, or "ask", which only the Workbench sends; anything else is a 422). With "ask", when this person already has questionnaires read from a file with exactly these bytes, whatever its name, nothing is saved, read or recorded, and the answer lists them (`batches.same_upload`, `uploads.holds`: the size first, then the bytes, against the files still on disk; no migration). The Workbench shows "You already have vendor.xlsx, with 4 of 4 answered…" with Open it, Start fresh (for the product chosen) and Cancel. 9 tests: 8 API (4 failing on the old code, 4 guards: different bytes, someone else's copy, a file the storage limit removed, and "new" still opening a second copy) and 1 browser, failing on the old page. The full browser suite (67) passes. The chat's "+" still opens a second copy (TD-062).
  - Room for 1.4 (R2, behaviour-neutral, its own commit): `tools.in_house_style` moved into `src/styling.py` (operations layer); `tools` re-exports it, so every caller and test is unchanged. Its failure log is now the event `styling.failed` (D-014) instead of a sentence; no test reads it. 418 existing tests over preferences, tools, the assistant and the pipeline pass unchanged. `tools.py` ceiling 1,347 to 1,294.
  - Room for 1.4 (R3, behaviour-neutral, its own commit): the Word preview moved out of `service` into `src/docx_preview.py` (integrations layer, which owns python-docx); `service.docx_preview_html` still names it. TD-019 resolved: its allow-list entry is gone. Its three helpers gained type annotations, which drops 3 errors from the mypy baseline (240 to 237). `service.py` ceiling 591 to 462.
  - 1.4: `service.answer_questions` hands each answer, failed ones too, to `on_answer` before it is counted, and `tools.answer` saves it there (`batches.saver`); the end-of-run save stays, for the styled wording. `src/busy.py` (foundation layer, in memory) holds a questionnaire for the length of a run, a rewording or a shortening; `tools._require` refuses any change to it meanwhile with 409 `questionnaire_busy` (a `ToolError` too, so the chat's model is told), while reading and filling go on. `GET /api/forms/{id}` says how far the run has got (`running`). The Workbench locks a questionnaire being answered, shows the progress and draws it again when the run ends; after a reload, and when the answer request fails with no code of its own (nginx's 502 or 504, a dropped line) or with 409, it follows the run instead of offering Answer again. 21 tests: 19 unit and API (8 in the new `tests/test_busy.py`, 3 in `test_concurrency.py`, 6 in `test_tools.py`, 2 of them guarding that a brief questionnaire still gets its briefs and that a failed run lets go, 1 API, 1 assistant) and 2 browser (a reload mid-run, and a 504 from the proxy), each failing on the old code. Changed on purpose: `test_preferences_are_never_handed_to_the_answering_pipeline` now allows `on_answer` among the pipeline's arguments, which is where answers are saved, not a wording instruction. The full browser suite (69) passes.
  - Ceilings: the moves lowered `tools.py` to 1,294 and `service.py` to 462 in their own commits; 1.4 brings them to 1,303 and 469, still below where the stage started (1,347 and 591). The same as Stage 0's 1,334 to 1,347 (TD-006). New debt: TD-063 (the hold is per process), TD-064 (a run that never ends holds its questionnaire). D-021 records the defaults of 1.1, 1.2, 1.4 and 1.5.
  - 1.3, the page only (and `edited_by` on the shared card): the review is in tabs, Needs review, Will be written, Done by a person, Blank or set aside, and All, each with its count, by the gate's verdict as the server gave it (`will_be_written`); failed answers count as needing review. It opens on Needs review when there is anything in it, and again after each run; approving or editing keeps the person's tab. Each card keeps its index in the answers, so the card's hooks are unchanged. A bar under the page header holds the tabs, "N will be written · M need review", Fill (moved there, its id kept) and what the last click did; Fill's report is under the bar, scrolled into view, and gains "Show them". "Write them in anyway" stays in the report only. The "need review" count above the cards is the tab's count. The question list folds into one line once a questionnaire has answer cards, unless the person opens or closes it themselves; "+ Add a question" opens it, and answers the file arrived with (no card) leave it open, where "Answer it again" is. 8 browser tests in the new `tests/browser/test_review_filter.py` (a 40-row fixture, `shapes.numbered`): 7 failing on the old page, 1 guarding the open list of a file that arrived answered. Changed on purpose: the two browser tests that follow one held card through approving and withdrawing (`test_write_them_in_anyway_writes_no_more_than_it_counted`, `test_withdrawing_an_approval_shows_the_answer_held_again`) first click All, because an approved answer now leaves Needs review. The full browser suite (76) passes.
  - Stage 1 done, waiting for review and the user's test. `uv run poe check`: every task passed (fmt, lint, types with 237 in the baseline, arch, docs, rules 94, test 2,198 passed and 2 skipped, browser 77). Stage 1 added 48 tests, 29 unit and API and 19 browser; 4 existing tests were changed on purpose, each named above. The mypy baseline went from 243 to 237, by the annotations the moved code gained.
- 2026-11-05, review of Stage 1: the server side held up (the guard, saving each answer, the 409, the byte match, the sort, the three moves). It found 4 major and 5 minor problems on the Workbench page, reproduced in headless Chromium. All 9 are fixed; none was rejected.
  - Major, 1.2: reading a Word file written as prose a second time offered the empty questionnaire its first read had left, "0 of 0 answered", and "Open it" read nothing. `batches.same_upload` now leaves out a questionnaire nothing was read from, so the file is read as text again. 2 tests (1 API, 1 browser), both failing on the old code. New debt: TD-065 (each such read still keeps an empty questionnaire, listed under "Or pick up").
  - Major, 1.3: Fill clicked from far down the list scrolled its report behind the page header and the sticky bar, so the held count, "Write them in anyway" and the download could not be seen. The report now scrolls to just under the bar, by their measured heights; "Show them" keeps it there. 1 browser test (40 rows, at 1366x768, clicked from the last card: a click at each control's middle reaches it), failing on the old page.
  - Major, 1.3: editing a held answer left it in Needs review, still "Not going into the file yet", and the bar's counts disagreed with what Fill writes (an edit is a person's, and goes in). A saved edit now draws the answers again from what the server holds, so the card moves and the counts follow. An edit is saved when its editor is left, by the press of the next click, so the redraw waits for that click to land; when that click opened another card's editor, the counts follow at once and the card at the next draw, so the editor being typed in stays open. After a redraw by an edit, an approval or a blank, the keyboard goes back to the same control, or to the answer now in that place. 3 browser tests, all failing on the old page; the second also fails on a fix that always redraws.
  - Major, 1.3: a question asked through "Ask another question" on an open questionnaire disappeared. Every run put the review back on Needs review, overriding the person's All, and a typed question's confident answer is in no tab but All. Only a run of the file's own rows goes back to Needs review now; a run of typed questions alone keeps the person's tab, or shows All when the tab would hide one of its answers. After a run of both, the status says the typed ones are under All. 2 browser tests, both failing on the old page.
  - Minor, 1.4: Fill could be clicked during the rewording pass that follows a run when the style box has text: drawing the answers set it to "not running", over the lock. Fill's state is now worked out from the page's state each time (answering, the server's run, a fill on its way) rather than remembered and put back. 1 browser test, failing on the old page.
  - Minor, 1.3 and 1.2, the keyboard and screen readers: choosing a tab dropped the focus to the page, because the tabs are drawn again; it now stays on the tab chosen. The "You already have" box appeared silently; the keyboard now goes to its first "Open it", and the box is described by its sentence. 2 browser tests, both failing on the old page.
  - Minor, 1.4: a followed run that had questions typed beside the file ended with "Finished: every question has an answer." They go out after the file's rows, so a request that failed never sent them, and the server does not keep them. The closing message now counts them and says to answer them again. 1 browser test (a 504 with a typed question), failing on the old page.
  - Minor, 1.4: TD-064 said `running.started_at` shows how long a run has been going, and no page showed it. The "Being answered on the server" note now says when the run started ("started at 14:02", with the day when it is not today). 1 browser test, failing on the old page.
  - Minor, the test note: 1.4's step 4 asked the chat to answer the questionnaire the Workbench was answering, which the chat cannot reach: it opens only a file attached to it, always as a new questionnaire (TD-062). The step now starts in the chat: attach the file there, then answer that questionnaire on the Workbench from "Or pick up", and ask the chat to change it during the run.
  - 14 tests added, each failing on the old code: 1 API (`test_api_forms.py`) and 13 browser (8 in `test_review_filter.py`, 5 in `test_workbench.py`). No existing test was changed. No server size ceiling moved (`batches.py` is under the default limit); the mypy baseline stays at 237. `docs/design/questionnaires.md` and D-021 say what changed in the review queue and the same-file check; ARCHITECTURE.md says what `same_upload` leaves out and that `running` carries the start.
  - `uv run poe check`: every task passed (fmt, lint, types with 237 in the baseline, arch, docs, rules 94, test 2,199 passed and 2 skipped, browser 89).
  - Stage 1 waits for the user's test.
- 2026-11-05, Stage 2 build (the product choice, as designed, on both pages; the pages only: no Python, API, setting, migration or size ceiling changed):
  - Groundwork: the chip's rules moved from `chat.html` into `cards.css`, shared by both pages (the Workbench's swatch is gone). `cards.js` gained the choice helpers: `Cards.GENERAL` ("general", never a product id), `serverProduct` (General goes to the server as `""`, the one line to change for TD-066), `choiceOf`, `choosable`, `lastUsed`, `choiceTag` and `lastUsedButton`.
  - 2.1, the Workbench: the selector starts on "Product: choose…" (dashed, amber); "General (shared policies only)" is an option. Read waits for a file and a product and names it ("Read questions for Msegat", also when a second file is read while one is open); Answer for a typed or PDF list waits too, with "Choose a product first.", "Last used" and "Choose…" beside both Answer buttons. Read's state is worked out each time (`paintRead`), and it left the lock's save-and-restore list. Close, Clear all of an answered list, a reload and a deleted product go back to "choose…"; the deleted-product notes say "Choose another product, or General". If the products cannot be loaded, the hint says so. A `?q=` questionnaire is opened after the products are listed, so its label shows at once.
  - 2.2, the chat: the chip starts on "Product: choose…"; a line above the box asks for one, and turns amber ("Choose a product to send this.") once something is typed or attached. Send and Enter wait; a file can be attached first. New conversation from an open chat chooses nothing (`chipChoice` is gone); from an unsent new chat it keeps the choice.
  - 2.3, "Last used": derived from the page's own last work, then the person's questionnaires (`GET /api/forms`, the "Or pick up" list) or chats (`GET /api/chat`), skipping deleted products and offering nothing until the products are listed. One click chooses; nothing is sent.
  - 2.4: a fixed choice is a label in its colour on both pages (General's neutral), and the Workbench's "Review and export" heading carries it (`#resultsProduct`).
  - Found by the suite and fixed: a choice made before `/api/products` answered was put back to "choose…" when the list arrived, because both pages read the choice before waiting. They read it after now. 2 browser tests (one per page), both failing without the fix.
  - 18 browser tests in the new `tests/browser/test_choosing_a_product_first.py`, each failing on the pages before this stage. Changed on purpose, each saying so in a comment: the existing tests that read a file or send a first message choose first (General where they meant General: the new `tests/browser/choosing.py` helper in `test_workbench.py`, `test_review_filter.py`, `test_answer_card.py` and `test_workbench_status.py`; `test_chat.py` twice); `test_product_choice.py`'s chat test now expects New conversation to choose nothing and offer "Last used: Availo" (plan 024's "keeps the choice" is superseded, D-022); its Close, Clear all and deleted-product tests expect "choose…" and Read or Send disabled, and choose General before going on; `test_deleted_product_work.py` expects a new chat after a deleted product's to wait, with no "Last used" offered.
  - New debt: TD-066 (the server still answers as General when no product is sent). D-022 records the decision and its defaults.

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
    - The same file means the same bytes as one of this person's questionnaire files still on disk. After the review of Stage 1: one nothing was read from is not offered, so a Word file written as prose is read as text again.
    - It is checked before the file is read. A match on another product is offered with its badge, and "Start fresh" stays one click away.
  - **1.3:**
    - The tabs are Needs review (the default when it has anything), Will be written, Done by a person, Blank or set aside, and All.
    - "Write them in anyway" appears only after Fill.
    - The question list folds once answers exist.
    - After the review of Stage 1: only a run of the file's own rows goes back to Needs review; a run of typed questions alone keeps the person's tab, or shows All when the tab would hide its answers. A saved edit moves its card like an approval does, except while another card's editor is being typed in, when only the counts follow.
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
    - Added during the build of Stage 2:
      - "Last used" offers nothing until the products are listed, so a product not yet listed is not passed over for an older General; if the products cannot be loaded, both pages say so and offer nothing.
      - A deleted product's questionnaire or chat is never offered as "Last used", and closing one goes back to "choose…".
      - Clicking "Last used" in the chat puts the cursor back in the box; on the Workbench it stays on the Product box.
      - A typed list whose product was deleted under it chooses nothing, and is not fixed to that nothing: the person can choose again without clearing the list.
      - On a phone-width chat (under 560 px) the chip is narrower, so the box keeps room to type.

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

### 1.1 A reload opens the questionnaire again

1. Open the Workbench, choose a product, upload a questionnaire and answer a few rows.
2. Press F5. The same questionnaire opens again, with its answers and its product. The address ends in `?q=` and a code.
3. Copy the address into a new tab. It opens there too.
4. Click "Close questionnaire". The `?q=` part disappears. Press F5: nothing is open.
5. Under "Or pick up", every questionnaire you have is listed, each with when it last changed. With more than three they are in a box that scrolls. Open an old one, change one answer and close it: it is now at the top.
6. On the server, repeat steps 2 to 4 under /assessment/.
7. Send the address to a colleague. It opens nothing for them, and says the questionnaire is not one of theirs.

### 1.5 Leaving with unsaved work asks first

1. Answer a questionnaire. Click Edit on an answer, type something and do not click anywhere else. Try to close the tab or press F5: the browser asks "Leave site?". Choose to stay: your text is still in the box.
2. Click outside the box and wait for "Your edit is saved". Press F5: no question this time, and the questionnaire opens again (1.1).
3. Type a question of your own with "+ Add a question" and press F5: the browser asks first.
4. With only a questionnaire's own rows, all answered and nothing being edited, press F5: no question.

### 1.2 The same file again offers the questionnaire you already have

1. Upload a questionnaire, answer some rows, then click "Close questionnaire".
2. Upload the same file again and click "Read questions from file". A box says you already have it, with how many are answered and when it last changed. "Open it" is highlighted, so Enter opens it; with a screen reader on, the box's sentence is read out.
3. Click "Open it". Your answers are there, and no second copy appears under "Or pick up".
4. Upload it again and click "Start fresh (for …)". A new, empty copy opens for the product chosen, and "Or pick up" now lists two.
5. Rename the file on your computer and upload it: it is still recognised. With two copies, the box lists both, each with its own "Open it".
6. Upload a different file with the same name: it opens normally, with no box.
7. Click Cancel in the box: nothing is opened.
8. Upload a Word file whose questions are plain paragraphs (no table, no "Q1:" lines) and click "Read questions from file": its questions are listed. Reload the page, upload it again and read it: the questions are listed again, with no box.

### 1.4 Each answer is saved as it finishes, and a run is not started twice

1. Upload a questionnaire with at least 20 questions and click Answer.
2. When a few are answered, press F5. The page reopens and says "Being answered on the server: 6 of 25 done, started at 14:02" (the time the run began). "Answer questions" and "Fill the original file" are greyed out, and the answers have no Edit or Approve.
3. Wait. The count rises, and at the end every answer appears with "Finished: every question has an answer." The questions were answered once, not twice.
4. While a run is going, open the same address in a second tab: it shows the same note and follows the same run.
5. The chat and the Workbench on one questionnaire. The chat can only open a file attached to it, always as a new questionnaire, so start there: in the chat, attach a questionnaire of at least 20 questions and send "Open this file, but do not answer anything yet." Then on the Workbench, open that questionnaire from "Or pick up" and click Answer. While it runs, go back to the chat and send "Change the answer to the first question to: Yes." The chat says the questionnaire is being answered right now, with how many are done, and changes nothing.
6. Optional, in Chrome: during a run press F12, then Network, and set Offline, then back to Online. The page says the connection timed out but the answering carries on there, then shows the answers.
7. Optional, the same with a question of your own: open a questionnaire with questions still waiting, add one with "+ Add a question", click Answer, and go Offline and back as in step 6. At the end the page says your typed question was not answered and offers "Answer 1 question", rather than "every question has an answer".
8. On the server, answer a questionnaire of more than 100 questions. After 15 minutes, instead of "Request failed (504)", the page says it carries on, and the answers arrive.
9. "Close questionnaire" works during a run: the run carries on, and opening the questionnaire again shows its progress.

### 1.3 Reviewing starts with the answers that need you

1. Open a questionnaire whose answers include some marked for review, and answer it.
2. The review section opens on "Needs review", with a count on each tab. Only the answers that need you are shown: flagged ones, ones with a low confidence even when not flagged, and ones that failed.
3. Approve one. It leaves the list, the counts change, and the bar says what happened ("Approved…").
4. Edit one: click Edit, change a word, click "Done editing". It leaves the list too ("Done by a person" goes up by one, and so does "will be written" in the bar), and the bar says "Your edit is saved". Edit another, and before clicking "Done editing" click Edit on a third: the third opens and stays open while you type, the counts change at once, and the second leaves the list when you finish the third.
5. With the keyboard: press Tab until an answer's Approve is highlighted, then press Enter. The answer leaves the list, and the next Tab goes on from the answer that took its place. Press Tab until the "All" tab is highlighted and press Enter: "All" stays highlighted (a screen reader says it is pressed), and the next Tab goes to "Fill the original file".
6. Scroll anywhere among the answers. The bar with the tabs, the counts and "Fill the original file" stays at the top, under the page header.
7. Click Fill, from far down the list. The page goes up to the result, which sits right under the bar, nothing of it covered. Only there, if answers were held back, do you see the count, "Show them" and "Write them in anyway".
8. The long question list above the answers is folded into one line ("Show the 59 questions…"). Click it to see the questions; "+ Add a question" opens it too.
9. Click "All" to see every answer, as before. Leave a card blank, or set a row aside: they are under "Blank or set aside", where a set-aside row has "Include".
10. Still on "All", type a question into "Ask another question" at the bottom, click "+ Add to the list", then Answer. Its answer appears, and "All" stays chosen. Click "Needs review" and ask another: the page goes to "All", where the new answer is.
11. Open a questionnaire with questions still waiting, add a question of your own with "+ Add a question", and click Answer. The review opens on "Needs review", and the status says your typed question's answer is under "All".

### 2.1 The Workbench waits for a product

1. Open the Workbench. In step 2, "Load a questionnaire", the Product box reads **Product: choose…**, with a dashed amber outline. The note beside it says what General and a product each answer from.
2. Drop a spreadsheet on the drop zone. **Read questions from file** stays grey, and beside it: **Choose a product first.**
3. Open the Product list. You see **General (shared policies only)**, then your products. Choose one, say Msegat. The button now reads **Read questions for Msegat**. Click it.
4. The Product box is now a Msegat label in Msegat's colour, and cannot be changed. Drop another spreadsheet: the button reads **Read questions for Msegat**, because a file read while one is open takes its product.
5. Click **Close questionnaire**. The box reads **Product: choose…** again.
6. Click **+ Add a question** and type a question. **Answer 1 question** stays grey, with **Choose a product first.** beside it, and the same under "Ask another question". Click **Choose…** in that note: the page goes to the Product box. Choose **General (shared policies only)**: Answer works.
7. Answer it, then click **Clear all** and OK. The box reads **Product: choose…** again.
8. Reload the page. The box reads **Product: choose…**: nothing was chosen for you.
9. Optional, with a PDF questionnaire: Read waits for a product too, and so does Answer.

### 2.2 The chat waits for a product

1. Open the chat (the home page). The chip beside the message box reads **Product: choose…**, and a line above the box asks which product this chat is for.
2. Type a question and press Enter. Nothing is sent: the line turns amber and says **Choose a product to send this.** Your text stays in the box.
3. Click **＋** and attach a questionnaire. It shows as attached, and the send arrow stays grey.
4. Choose a product on the chip, say Ole5. The arrow lights up and the line goes. Send. The chip becomes an Ole5 label in Ole5's colour, and cannot be changed.
5. Click **New conversation**. The chip reads **Product: choose…** again.
6. Choose **General (shared policies only)** and send a question. The chip stays a grey **General (shared policies only)** label.

### 2.3 "Last used", in one click, never chosen for you

1. In the chat, send a question for Ole5, then click **New conversation**. Above the box: **Last used: Ole5**. Click it. The chip shows Ole5, the cursor is back in the box, and you can send.
2. Reload the page. The chip reads **Product: choose…**, and **Last used** offers the product of your most recent chat. It comes from your own chats, so it is offered on another computer too.
3. Open an older chat for another product, say RICH, from the history, then click **New conversation**. It offers **Last used: RICH**, and nothing is chosen until you click.
4. On the Workbench, open a questionnaire for Msegat from "Or pick up" and close it. Beside the Product box: **Last used: Msegat**. Click it: Msegat is chosen, and nothing is opened or sent. Reload: it is offered again, and not chosen.
5. Typed questions: with nothing chosen, the **Choose a product first.** note beside Answer carries the same **Last used** button.
6. Optional: have a lead delete a test product you used last. It is no longer offered; the product before it is.

### 2.4 A fixed product shows as a label

1. Open a questionnaire for Availo on the Workbench. The Product box is an Availo label in Availo's colour.
2. Answer it and scroll to **3 Review and export**. The Availo label is beside the heading, so whoever approves can see which product's memory the approvals go to.
3. Open a General questionnaire: the label beside the heading reads **General**, in grey.
4. In the chat, a chat started as General shows a grey **General (shared policies only)** label beside the box.
5. If the products cannot be loaded (for example the server is restarting), the Product box and the chat's line say so and ask you to reload before choosing, rather than offering only General.
