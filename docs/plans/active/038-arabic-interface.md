# Plan 038: The whole interface in Arabic, right to left, chosen per person

**Status:** active

## Goal

The user's choices (plan 033's questions): "Whole interface", described as "an Arabic/English switch per person (in Preferences and the header), every page right-to-left in Arabic, built after this round's redesign so nothing is translated twice". Also "You check a glossary first". On 2026-11-07 the user approved the glossary, [arabic-glossary.md](../../design/arabic-glossary.md), as written.

When this is done, a person can choose Arabic in Preferences, or with the switch in any page's top bar. Every page then reads in Arabic, right to left: headings, labels, buttons, hints, empty states, confirmations, the status lines and the errors. The choice is kept with the person, on any device. Answers are not changed by it: they still follow the question's language, or the language a questionnaire is forced into.

## Acceptance criteria

- [ ] The choice:
  - each person has one, English until chosen, kept on the server (`src/interface_language.py`, migration 17) and returned by `GET /api/auth/session`;
  - `PUT /api/preferences/language` changes it;
  - the switch is in every page's top bar, and the same choice is in Preferences;
  - the device keeps a copy, so a page is drawn in the right language from the first paint;
  - a page whose copy differs from the person's choice takes the person's.
- [ ] In Arabic, every page has `lang="ar"` and `dir="rtl"`, and its layout reads right to left with nothing overlapping or cut off, down to a phone's width.
- [ ] Every string a page shows is in the catalogs (`src/static/i18n/`), translated with the glossary's terms. A test reads every page's markup and every `t("…")` in its scripts, and fails on one that has no Arabic.
- [ ] A browser test opens each page in Arabic, in the states that matter: signed out, empty, with a questionnaire answered, with the dialogs open. It fails on any visible English word other than names: products, files, standards, formats and keys.
- [ ] The server's sentences that reach a page are in Arabic:
  - why an answer is held back;
  - the review's reasons;
  - the errors, by their codes, with the English kept for the rest.
- [ ] Dates are Gregorian, with Western digits, as the glossary says.
- [ ] Answers, questions and sources keep their own direction: an English answer in an Arabic page reads left to right.
- [ ] The Workbench's keys (J/K, A, E) work with an Arabic keyboard layout too.
- [ ] In English, nothing changes: every existing test passes as it is.
- [ ] `uv run poe check` passes. ARCHITECTURE, decisions and the generated docs are updated.

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

## Decision log

- 2026-11-07: the language is kept in a table of its own, not among the answer preferences. Those change what an answer says and are recorded as events; this changes only how the pages read. (Mine.)
- 2026-11-07: English stays the default for everyone until they choose. (Mine; the user chose a per-person switch, and English is what everyone sees today.)
- 2026-11-07: translated in the pages, not on the server. The server keeps writing English: its logs, the API and the generated docs stay one language, and every Arabic word is in one place, the catalogs. (Mine.)
- 2026-11-07: switching reloads the page in the other language, rather than redrawing it in place. Everything a page drew was drawn in one language, and a reload draws all of it again from the same code. A page with unsaved typing asks first (`I18n.beforeSwitch`). (Mine.)
- 2026-11-07: a page is checked by the catalog test once its own catalog has entries, so the four translators never edit the same list. While they work, each one's browser tests leave out the areas another one owns (`NOT_YET` in `tests/browser/arabic.py`); it is emptied after the merge. (Mine.)
- 2026-11-07: the filled files and the PDF and Word downloads are not part of this plan. They are documents for a customer, in the questionnaire's language, not the interface. (Mine; worth asking the user whether the downloads' own headings should follow the interface.)
