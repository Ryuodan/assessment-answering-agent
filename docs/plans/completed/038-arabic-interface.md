# Plan 038: The whole interface in Arabic, right to left, chosen per person

**Status:** completed 2026-11-07

## Goal

The user's choices (plan 033's questions): "Whole interface", described as "an Arabic/English switch per person (in Preferences and the header), every page right-to-left in Arabic, built after this round's redesign so nothing is translated twice". Also "You check a glossary first". On 2026-11-07 the user approved the glossary, [arabic-glossary.md](../../design/arabic-glossary.md), as written.

When this is done, a person can choose Arabic in Preferences, or with the switch in any page's top bar. Every page then reads in Arabic, right to left: headings, labels, buttons, hints, empty states, confirmations, the status lines and the errors. The choice is kept with the person, on any device. Answers are not changed by it: they still follow the question's language, or the language a questionnaire is forced into.

## Acceptance criteria

- [x] The choice:
  - each person has one, English until chosen, kept on the server (`src/interface_language.py`, migration 17) and returned by `GET /api/auth/session`;
  - `PUT /api/preferences/language` changes it;
  - the switch is in every page's top bar, and the same choice is in Preferences;
  - the device keeps a copy, so a page is drawn in the right language from the first paint;
  - a page whose copy differs from the person's choice takes the person's.
- [x] In Arabic, every page has `lang="ar"` and `dir="rtl"`, and its layout reads right to left with nothing overlapping or cut off, down to a phone's width.
- [x] Every string a page shows is in the catalogs (`src/static/i18n/`), translated with the glossary's terms. A test reads every page's markup and every `t("…")` in its scripts, and fails on one that has no Arabic.
- [x] A browser test opens each page in Arabic, in the states that matter: signed out, empty, with a questionnaire answered, with the dialogs open. It fails on any visible English word other than names: products, files, standards, formats and keys.
- [x] The server's sentences that reach a page are in Arabic:
  - why an answer is held back;
  - the review's reasons;
  - the errors, by their codes, with the English kept for the rest.
- [x] Dates are Gregorian, with Western digits, as the glossary says.
- [x] Answers, questions and sources keep their own direction: an English answer in an Arabic page reads left to right.
- [x] The Workbench's keys (J/K, A, E) work with an Arabic keyboard layout too.
- [x] In English, nothing changes: every existing test passes as it is.
- [x] `uv run poe check` passes. ARCHITECTURE, decisions and the generated docs are updated.

## Plan

1. **Groundwork** (one person, before the pages):
   - the server side: `interface_language`, migration 17, the route, the session field;
   - `src/static/i18n.js`: the language, `t()`, plurals, translating markup, dates, errors, the server's sentences, and the switch in the top bar;
   - `i18n/ar-common.js`: the top bar, sign-in, the theme and language switches;
   - the catalog test, and the Arabic browser test's harness.
2. **The pages, in parallel**, each translator owning its own files and its own catalog:
   - the Workbench (`index.html`, `ar-workbench.js`);
   - the chat (`chat.html`, `ar-chat.js`);
   - the answer card and the server's sentences (`cards.js`, `cards.css`, `ar-cards.js`, `ar-server.js`);
   - the four smaller pages (`knowledge.html`, `memory.html`, `preferences.html`, `products.html`, one catalog each).
3. Merge; review the Arabic against the glossary; run each page in Arabic; fix what that finds.
4. The gate, the docs, and a "How to test it yourself" section.

## How the pages are translated

My design, written down so each translator applies the same rules:

- **English is the source.** A page keeps its English text, and `I18n.t("Needs review")` returns the catalog's Arabic. A missing entry shows the English, and the catalog test fails.
- **Markup is translated once,** after the page loads: text, `title`, `placeholder`, `aria-label` and `alt`, where the catalog has the whole text. Markup with elements inside a sentence uses `data-i18n-html`.
- **Script-made text goes through `t()`,** with `{name}` placeholders and never concatenated English. A count's Arabic depends on the number: an entry can give `zero`, `one`, `two`, `few`, `many` and `other` forms.
- **Names stay as they are:** products, files, standards, formats.
- **Numbers are Western digits;** dates go through `I18n.date`.
- **A switch reloads the page** in the other language. A page with unsaved typing asks first.

## How to test it yourself

On your local copy. The database gains migration 17 the first time the app starts. Start the app with `uv run python -m uvicorn src.api:app --reload` and open http://127.0.0.1:8000.

1. In the top bar, press "العربية". The page reloads right to left, in Arabic, and the button now reads "English".
2. Open each page from the bar: the assistant, the Workbench, the knowledge base, the answer memory, Preferences and products. Each is in Arabic. Product names, file names, questions, answers and sources stay as they are, and an English answer reads left to right.
3. On the Workbench, load a questionnaire, answer it and open the review. The tabs, the cards, their reasons ("why it needs review") and the held-back list are in Arabic. With an Arabic keyboard layout, the J, K, A and E keys still move, approve and edit.
4. Type a wording under "More options" and, without saving, press "English": the page asks first.
5. In Preferences, "لغة الصفحات" (Language of the pages) shows the same choice. Open the app in another browser, as the same person: it opens in Arabic.
6. On the products page, Delete asks you to type "تأكيد" (or "confirm").
7. Press "English": every page is as it was.

## Progress log

- 2026-11-07: the server side of the choice.
  - `src/interface_language.py`, migration 17 (`interface_languages`), `PUT /api/preferences/language`, and `interface_language` in the session.
  - To make room, the preferences and skills routes moved from `src/api.py` into `src/routes/preferences.py`. The move is behaviour-neutral: `openapi.json` changed only by the new route. `api.py`'s ceiling went from 1178 to 982 lines, and the baseline lost the moved routes' 9 untyped `dict`s, now typed.
  - 6 tests (`tests/test_interface_language.py`).
- 2026-11-07: the pages' groundwork.
  - `src/static/i18n.js`: the language, `t()` with Arabic plurals, the markup translated on load, dates and numbers, the server's sentences, errors, and the switch it puts in every top bar.
  - `i18n/ar-common.js`: the top bar, signing in, the theme and the pages' titles. Each page and `cards.js` also has a catalog of its own, empty until its translator fills it.
  - Every page loads `i18n.js` first, and its catalogs after it. It follows the person's choice from the session, and its theme switch's words go through `t()`.
  - Tests:
    - `tests/test_i18n_catalogs.py`: the catalogs, the pages' wiring, and each page's markup and `t()` strings once its catalog is filled;
    - `tests/browser/arabic.py`: the helper that finds English left on screen;
    - `tests/browser/test_language_switch.py`: 10 tests, all passing.
- 2026-11-07: the pages, by four translators in parallel, each in its own worktree, then merged.
  - **The Workbench:** 445 entries and 17 patterns (`ar-workbench.js`), 14 browser tests. Its keys work on an Arabic keyboard layout (ت/ن/ش are J/K/A by `event.code`).
  - **The chat:** 154 entries (`ar-chat.js`), with the assistant's own progress sentences, 15 browser tests. The answers panel's edge widens toward the page's start in either direction.
  - **The card and the server's sentences:** 133 entries (`ar-cards.js`); 139 entries and 60 patterns (`ar-server.js`), with every error code in `errors.md` and every fixed message raised in the code, 8 browser tests.
  - **The smaller pages:** the knowledge base (58), the answer memory (64), Preferences (96, and 12 patterns for its limits) and products (71). Preferences has "Language of the pages", and a product's Delete takes "تأكيد" as well as "confirm". 24 browser tests.
  - In English, every page reads and behaves as before: the translators ran the existing browser tests, unchanged.
- 2026-11-07: the merge.
  - The checks read what the translators found they missed: a `<textarea>`'s placeholder and a `<kbd>`'s title, and the tags of a `data-i18n-html` value are not English words. `XLSM` is a name, as `XLSX` is.
  - One English, one Arabic: 16 entries read two ways across catalogs, settled (the chosen Arabic is in the decision log). The sign-in's two sentences moved to `ar-common.js`, and the built-in skills' names and descriptions are only in `ar-server.js`.
  - Every Arabic test reads every word: `NOT_YET` and the translators' own lists of other translators' areas are gone, and `test_every_page_is_translated` is no longer expected to fail.
  - With every word read, 11 of 71 Arabic tests failed, on what lay between two translators' areas. Fixed:
    - a name an attribute holds (a product's in its badge's title, a question's place in its card's label) is allowed by name: `names` in `expect_arabic`, as no element can mark part of an attribute as content;
    - the Workbench's "Which, and why" puts the server's sentence in with `Cards.serverInto`, so what it carries from the case is content, as on the card;
    - the chat marks a file's name in its own Markdown turns as content (Arabic only);
    - the Preferences page's 12 patterns for the server's limits were already in `ar-server.js`, and are gone from `ar-preferences.js`;
    - tests: a reason the server really writes (`verification.UNGROUNDED`) rather than one it never does; a failure's code says what kind it was (`I18n.error`), where a translator expected the English; the settled wordings.
  - Found, not fixed: TD-081 (the closed search drawer's shadow, in English too).
- 2026-11-07: the gate.
  - `uv run poe check`: lint, types, arch, docs, rules and test (2436) passed. fmt failed on one line of `tests/browser/arabic.py`, now formatted. The browser task failed on TD-080 alone (`['MFA', 'MFA']`), the flaky Workbench search that failed the same way before this plan; 273 passed. That test then passed 3 times out of 3 on its own, and the whole browser task again: 274 passed.
  - No existing English test changed: since the groundwork, only the Arabic tests and the two checks did.
  - Screenshots in Arabic at 1280 and 375 px (the Workbench's review, Preferences, the assistant): right to left, English answers and questions left to right, nothing overlapping.

## Decision log

- 2026-11-07: the language is kept in a table of its own, not among the answer preferences. Those change what an answer says and are recorded as events; this changes only how the pages read. (Mine.)
- 2026-11-07: English stays the default for everyone until they choose. (Mine; the user chose a per-person switch, and English is what everyone sees today.)
- 2026-11-07: translated in the pages, not on the server. The server keeps writing English: its logs, the API and the generated docs stay one language, and every Arabic word is in one place, the catalogs. (Mine.)
- 2026-11-07: switching reloads the page in the other language, rather than redrawing it in place. Everything a page drew was drawn in one language, and a reload draws all of it again from the same code. A page with unsaved typing asks first (`I18n.beforeSwitch`). (Mine.)
- 2026-11-07: a page is checked by the catalog test once its own catalog has entries, so the four translators never edit the same list. While they work, each one's browser tests leave out the areas another one owns (`NOT_YET` in `tests/browser/arabic.py`); it is emptied after the merge. (Mine.)
- 2026-11-07: where two translators chose differently, one Arabic for both. (Mine.)
  - "Include it again" is أدرجها في الملف مجدداً: an imperative, as the glossary's "Leave blank" (اتركها فارغة), naming the file, as "Set aside" (مستبعدة من الملف) does.
  - "guideline" is وثيقة إرشادية, apart from a document (وثيقة); an uploaded completed assessment is استبيان مُجاب عنه مرفوع.
  - "Removed {name}." and "Added {name}." are تمت إزالة / تمت إضافة, the glossary's nouns.
  - "Download original" is تنزيل الملف الأصلي; "Last used {when}" is آخر استخدام: {when}.
  - Counts take Arabic plural forms wherever one translator gave them.
  - The sign-in's "Check the address" names the email (تحقّق من البريد الإلكتروني): the address is the email address.
- 2026-11-07: the filled files and the PDF and Word downloads are not part of this plan. They are documents for a customer, in the questionnaire's language, not the interface. (Mine; worth asking the user whether the downloads' own headings should follow the interface.)
