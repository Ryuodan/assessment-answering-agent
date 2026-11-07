# Decisions

Lasting decisions, numbered. Each records its context, the decision, its
consequences, the date, its status (accepted, superseded by D-NNN, or
withdrawn), and who decided. Earlier design decisions are recorded, with
their measurements, in the design notes that were moved out of the README
(plan 009): [answering](answering.md), [questionnaires](questionnaires.md),
[the assistant](assistant.md), [the answer memory](answer-memory.md),
[preferences](preferences.md), [access](access.md), and the
[evaluation](../measurements/evaluation.md). A decision is promoted here when
a plan relies on it.

## D-001: poethepoet is the task runner

- **Context:** the gate needs named tasks that run the same on the Windows
  development machine and the Linux server. make, just and node are not
  installed on the development machine.
- **Decision:** tasks are defined in `[tool.poe.tasks]` in `pyproject.toml`
  and run as `uv run poe <task>`. `uv run poe check` is the definition of done.
- **Consequences:** one dev dependency; tasks are declarative and listed by
  `uv run poe`.
- **Date:** 2026-10-05. **Status:** accepted. **Decided by:** the user (plan 001).

## D-002: ruff format is enforced, after one mechanical commit

- **Context:** 116 of 141 Python files were not ruff-formatted.
- **Decision:** reformat everything in one commit (`4a7c3c6`) whose syntax
  trees were verified unchanged (`python -m harness.same_ast`), list it in
  `.git-blame-ignore-revs`, and enforce `ruff format --check` from then on.
  Markdown is excluded: ruff would reformat Python code blocks in the README.
- **Consequences:** `git blame` needs `blame.ignoreRevsFile` set to look
  through the commit.
- **Date:** 2026-10-05. **Status:** accepted. **Decided by:** the user (plan 001).

## D-003: mypy strict, with a baseline that only shrinks

- **Context:** no type checker had ever run; strict mode reports 324 errors in
  `src/`.
- **Decision:** mypy `strict = true` with the pydantic plugin over `src/` and
  `harness/`. Existing errors live in `harness/mypy-baseline.txt`, matched
  without line numbers; new errors fail, fixed errors must be removed
  (`uv run poe types-baseline` only removes). Untyped third-party libraries are
  ignored by a mypy override, not baselined.
- **Consequences:** new code is fully typed; old code is typed as it is
  touched. `eval/`, `scripts/` and `tests/` are not type checked yet.
- **Date:** 2026-10-05. **Status:** accepted. **Decided by:** the user (strict
  and baseline); Claude (scope).

## D-004: dependencies are locked to the versions the suite passed on

- **Context:** there was no lock file. An unconstrained `uv lock` resolved
  about 60 upgrades, including sentence-transformers 5 to 6 and websockets 15
  to 16, none of which the tests had run against.
- **Decision:** `uv.lock` was created pinned to the installed, tested versions,
  plus the new dev tools; dev tools are a uv dependency group, not an extra.
  Upgrades are deliberate changes with a test run, not side effects.
- **Consequences:** `uv sync --inexact` reproduces the environment;
  `uv lock --check` verifies the lock matches `pyproject.toml`.
- **Date:** 2026-10-05. **Status:** accepted. **Decided by:** Claude, within plan 001.

## D-005: confidential eval data is sealed in the repository

- **Context:** `eval/house_set.json` and `eval/answer_memory.json` hold named
  customers' questions and the team's real answers, in plaintext in git.
- **Decision:** commit only an encrypted copy; decrypt on demand with a key
  held in `.env`; encrypt forward only, without rewriting history.
- **Consequences:** the plaintext stays in old commits (TD-013) and must be
  purged before any remote is added. Implemented by plan 002. Format in D-011.
  *Amended 2026-10-20 by the user: the repository is pushed unpurged to a
  private GitHub repository (TD-013).*
- **Date:** 2026-10-05. **Status:** accepted. **Decided by:** the user.

## D-006: the README is kept and reorganised, not replaced

- **Context:** the README is 3,320 lines of design history with measurements,
  partly out of date (TD-001 to TD-005).
- **Decision:** keep its content; move it into `docs/` (decisions, design
  notes, measurements) in a later plan, and cut the README to an introduction.
- **Consequences:** done in plan 009: the sections moved verbatim into
  `docs/design/`, `docs/operations/` and `docs/measurements/`; the API, settings
  and module tables are generated instead of hand-written.
- **Date:** 2026-10-05. **Status:** accepted. **Decided by:** the user.

## D-007: harness code lives in `harness/`, outside the application

- **Context:** checks and generators are not application code, and `scripts/`
  already holds the application's operational scripts.
- **Decision:** a top-level `harness/` package; its tests in `tests/harness/`.
  Nothing in `src/` imports it.
- **Date:** 2026-10-05. **Status:** accepted. **Decided by:** Claude, within plan 001.

## D-008: tools are always run as `python -m <tool>`

- **Context:** this `.venv` was copied from another checkout. 46 of its `.exe`
  launchers, `pytest` and `uvicorn` among them, still started that checkout's
  interpreter, so a bare `pytest` silently ran in a different environment
  (found 2026-10-05 when it failed to import `rank_bm25`).
- **Decision:** every task and every documented command starts a tool as
  `python -m <tool>`; poe runs tasks inside `.venv`. The launchers were
  regenerated by reinstalling the same versions.
- **Consequences:** the gate cannot be fooled by stale launchers;
  `tests/harness/test_tasks.py` holds the rule for poe tasks.
- **Date:** 2026-10-05. **Status:** accepted. **Decided by:** Claude, within plan 001.

## D-009: the development environment includes every optional extra

- **Context:** a fresh clone with `uv sync` (no extras) failed `types`: mypy
  could not find the Phoenix modules `src/config.py` imports when tracing is on,
  while the original venv happened to have the `phoenix` extra installed. The
  gate's verdict depended on what had been installed by hand, and one test
  (needing `openpyxl`) had always been skipped.
- **Decision:** the `dev` dependency group repeats the packages of the
  `phoenix` and `reports` extras, so a plain `uv sync` builds the full
  environment and the gate sees every import and runs every test. The extras
  stay, for installs without the dev tools. A missing module in `types` now
  says to sync the environment.
- **Consequences:** the two lists must be kept in step (a comment says so);
  the development environment carries the OpenTelemetry client libraries,
  not the Phoenix server.
- **Date:** 2026-10-05. **Status:** accepted. **Decided by:** Claude, within plan 001.

## D-010: ARCH-SIZE does not count the Settings class

- **Context:** adding `EVAL_DATA_KEY` (plan 002) took `src/config.py` from 545
  to 551 lines, past its allow-listed ceiling, while D-003's companion rule says
  ceilings never rise. Adding a setting is that module's job; the module's real
  excess is the tracing and logging setup (TD-009).
- **Decision:** ARCH-SIZE subtracts the `Settings` class body from
  `src/config.py`'s length (`SIZE_EXEMPT_CLASSES` in `harness/arch.py`). The
  module then counts 142 lines and leaves the allow-list.
- **Alternatives rejected:** raising the ceiling once (breaks "only shrinks",
  and recurs with every setting); moving tracing out first (M3 work, changes
  when tracing starts); keeping the key outside Settings (breaks configuration
  in one place).
- **Consequences:** logic placed inside the Settings class would escape the
  size rule; review watches for it.
- **Date:** 2026-10-05. **Status:** accepted. **Decided by:** the user, from options Claude proposed.

## D-011: how the eval data is sealed

- **Context:** D-005 decided to seal the house set and the answer memory with a
  key in `.env`.
- **Decision:** AES-256-GCM (`cryptography`), a random 96-bit nonce per seal,
  the file name as associated data (two sealed files cannot be swapped), a
  32-byte key as URL-safe base64. `eval/sealed/manifest.json` records each
  plaintext's SHA-256, so the arch check needs no key and sealing an unchanged
  file writes nothing. Unlock decrypts and verifies everything before writing
  anything, and will not overwrite a differing local copy unless forced.
- **Consequences:** the manifest reveals whether a guessed plaintext is exactly
  right, which only matters to someone who already holds the file.
- **Date:** 2026-10-05. **Status:** accepted. **Decided by:** Claude, within plan 002.

## D-012: six layers, enforced by the arch check

- **Context:** the survey found the dependency directions only as a habit,
  with two cycles and several upward imports hidden inside functions (TD-007)
  and IO libraries used from several places (TD-019).
- **Decision:** `src/` has six layers, lowest first: foundation, integrations,
  records, answering, operations, interfaces, defined in `harness/layers.toml`.
  A module imports only its own layer and those below, including inside
  functions (ARCH-LAYER); each IO or framework library is imported only by the
  layer that owns it (ARCH-OWNER); a new module must be given a layer. The
  reasons for each line are in ARCHITECTURE.md#layers. The layering was measured
  before it was adopted: 2 upward imports and 5 ownership exceptions, all
  allow-listed against TD-007, TD-009 and TD-019.
- **Alternatives considered (Claude):** splitting forms into its own layer
  (rejected: its rules are file handling like the exports, and its
  model-driven reading is answering); a generic types-config-repo-service-UI
  stack (rejected by the brief: it does not name what this system does).
- **Consequences:** cycles inside one layer are not caught (forms.xlsx and
  forms.llm_layout); a layer can grow large, which ARCH-SIZE watches per module.
- **Date:** 2026-10-05. **Status:** accepted. **Decided by:** Claude, within plan 003; the user delegated the plan.

## D-013: one error hierarchy, one handler, a code on every error response

- **Context:** eleven unrelated exception classes, four wrappers in `api.py`
  that each turned some of them into HTTP errors, 45 hand-built
  `HTTPException`s, and three responses that included an internal exception's
  text, one of them the server's file path (TD-008).
- **Decision:** `src/errors.py` defines `AppError` and one subclass per status
  in use (Invalid 400, SignInRequired 401, Forbidden 403, NotFound 404,
  UnsupportedFile 415, Unprocessable 422, Unavailable 503), and the domain
  errors, which keep their built-in bases (`PreferenceError` is still a
  `ValueError`). Each class has a default code; a raise site may name a more
  specific one. `src/api.py` has one handler: every error response is
  `{"detail": <message>, "code": <code>}`, FastAPI's own errors and the 500
  included. ARCH-ERROR keeps new exceptions in the hierarchy and
  `HTTPException` out of `src/`; `docs/generated/errors.md` lists every code.
- **Consequences:** the pages keep reading `detail`; clients and tests can
  branch on `code`. Behaviour was pinned first and compared after: 29 error
  responses gained a code, none changed status, two stopped showing a server
  path. Errors that used to escape as an unhandled 500 now answer with their
  class's status. The domain errors moved into `src/errors.py` (re-imported
  by their modules), which also took 75 lines out of the oversized modules.
- **Date:** 2026-10-05. **Status:** accepted. **Decided by:** the user approved
  the plan; the design is Claude's.

## D-014: structured logs with event names, and a request ID everywhere

- **Context:** 90 prose log calls with no event names, no request context,
  `logging.basicConfig` in `src/config.py`, and errors a person could not
  match to a log line (TD-009).
- **Decision:** `src/logs.py` wraps the standard library: `get_logger(name)`
  gives a logger whose calls take a dotted event name and keyword fields; one
  handler writes `text` or `json` (`LOG_FORMAT`); a filter adds the current
  request's ID to every record, from any logger; the formatter replaces
  configured secret values and key-shaped strings with `[redacted]`.
  `src/web.py` gives every request an ID (a well-formed `X-Request-ID` is kept),
  returns it in the response header and every error body, and logs each
  request once as `http.request` with the route template, never the raw path
  or query string. ARCH-LOG stops new prose logging; unconverted modules are
  allow-listed (TD-028).
- **Alternatives considered (Claude):** structlog (rejected: a dependency for
  what four small classes do); logging the raw path (rejected: file names and
  search text can be a customer's).
- **Consequences:** an event's record message is its rendered form, so any
  handler (pytest's capture included) shows the fields. The error-response
  snapshots gained `request_id` and nothing else, compared as data. The
  catch-all 500 runs outside the middleware, so it re-enters the request's
  context to log under the same ID.
- **Date:** 2026-10-05. **Status:** accepted. **Decided by:** the user chose
  this plan; the design is Claude's.

## D-015: data is parsed into models where it enters

- **Context:** the survey for plan 007 found most boundaries already parsed
  into pydantic models; four were not: vocabulary settings typed as free
  strings, the organisation profile read into a dataclass without checks,
  Docling's responses used as raw dicts, and no rule against new raw decoding.
- **Decision:** `Literal` types for the four vocabulary settings (an invalid
  value stops startup naming the setting); the organisation profile and
  Docling's task and result responses become pydantic models; ARCH-JSON fails on
  `json.loads` in `src/` except in `store`, `conversations` and `llm`, each with
  its reason written beside the exemption. `docs/design/boundaries.md` keeps the
  inventory.
- **Consequences:** a misconfigured deployment fails at startup instead of when
  a questionnaire is opened; a misshapen Docling reply is a `DoclingError` and
  the local fallback applies, where before it could be an `AttributeError` that
  escaped it (shown by running the old code against the new test). HTTP
  parameters checked by hand keep their own error codes.
- **Date:** 2026-10-06. **Status:** accepted. **Decided by:** Claude, within plan 007; the user asked for M3 to be finished.

## D-016: products scope a team's knowledge and memory, one level down

- **Context:** the security team answers for several products (Availo, Msegat,
  Ole5, RICH, SouqT2) and needs knowledge and answers per product, on top of
  what the whole team shares (plan 018).
- **Decision:**
  - Products belong to a team.
  - Each product will have its own Chroma collection beside the team's shared
    one, which is not touched. "General" keeps today's code path exactly. A
    product's questionnaire searches shared and product material and merges
    the results by score.
  - For that product, its own material wins over shared material. The memory
    compares answers only within one scope.
  - Approved answers go to the questionnaire's product.
  - The team's leads and administrators manage products.
  - Deleting a product takes its documents and answers, behind a typed
    "confirm"; questionnaires that used it become General. *Amended by D-019:
    they are kept read-only instead.*
  - `SEED_PRODUCTS` applies once.
- **Consequences:** no stored vector is migrated, and deleting a product drops
  one collection. The routes and records that products need go into new modules
  (`src/products.py`, `src/routes/`), because the modules they touch are at
  their size ceilings.
- **Date:** 2026-10-06. **Status:** accepted. **Decided by:** the user (decisions 1-8 of plan 018, with two changes).

## D-017: a team lead role manages the team's products

- **Context:** the user wanted people inside a team, not only administrators,
  to manage that team's products.
- **Decision:**
  - A third role, `lead`, shown as "Team lead", sits between member and
    administrator.
  - A lead may add, edit and delete their own team's products, and nothing an
    administrator does besides.
  - Roles live in `src/roles.py`. Demoting the last administrator to any other
    role is refused; before this it was refused only for "member".
- **Consequences:** the Access panel offers the role. `roles.manages_products` is
  the one rule the routes and pages check.
- **Date:** 2026-10-06. **Status:** accepted. **Decided by:** the user (the role); Claude (its name, which the user left open).


## D-018: a questionnaire's and a chat's product is fixed when it is created

- **Context:** the pre-deploy tests (TD-040) found a way for a product's wording
  to leak into the shared answer memory. Someone switched a product
  questionnaire to General and then approved an answer drafted from the
  product's material, and that answer was filed as shared. The user preferred
  removing the switch to policing it.
- **Decision:**
  - The product is chosen when a questionnaire is opened or a chat starts, and
    it cannot be changed afterwards.
  - The two routes that changed it now refuse any other product with 409
    `product_locked`. Another team's or a deleted product is still 404
    `product_not_found`, checked first.
  - The workbench can close a questionnaire, so the file can be opened again
    for another product.
  - The chat's product chip can be changed until the first message.
  - `conversations.save` no longer writes the product, so a turn that outlives
    a change cannot write an old value back.
- **Consequences:** only creation and product deletion write a questionnaire's
  or chat's product. Evidence precedence still rests on the FOR THIS PRODUCT
  label in the drafter's prompt; the pipeline orders evidence by score
  (TD-040's first item, accepted as it is).
- **Date:** 2026-10-19. **Status:** accepted. **Decided by:** the user (plan 027). Supersedes plan 018's decision 8.

## D-019: a deleted product takes its files, and leaves its work read-only

- **Context:** deleting a product left its uploaded files on the server and in
  the document library (TD-039). Its questionnaires and chats also became
  General and stayed usable, so approving an answer in one would file the
  product's wording as a shared answer.
- **Decision:**
  - A product's knowledge-base files live in its own folder,
    `<uploads parent>/products/<product id>/`. One file name is still one
    document across the team and its products: a different file under a name
    already used gets " (2)".
  - Deleting a product removes, after the database commit:
    - its knowledge base, its folder and the text read from its files;
    - files uploaded before the folder existed, but only those that nothing
      else indexes or claims;
    - its remembered answers, including those moved in from Shared.
  - Removing a product document, or clearing a product's knowledge base, deletes
    those files too. Shared documents keep their files, as before.
  - The delete dialog is a red warning that counts what goes and still needs
    the typed word.
  - The product's questionnaires and chats are kept and keep its id. A
    `deleted_products` table (migration 14) holds the name they are labelled
    with. They can be read, and filled files downloaded, but every write is
    refused with 409 `product_deleted`: answering, editing, approving and
    chatting. Forgetting one's own chat is still allowed.
  - A deleted product's knowledge base is never created again by a late
    request.
- **Consequences:** the name can be reused by a new product. Answer runs or
  approvals already in flight when a product is deleted are not stopped
  (TD-045). `migrations.py` is at its 400-line limit (TD-046).
- **Date:** 2026-10-19. **Status:** accepted. **Decided by:** the user (files and warning, TD-039; read-only work, plan 027); Claude (the folder layout, the tombstone table).

## D-020: what the review gate held is kept, not derived

- **Context:** the review gate (`selection.ready_to_write`) holds flagged and
  low-confidence answers back from the customer's file. Two places lost what
  it had said. Approving cleared the flag, and withdrawing the approval did
  not put it back (TD-053). And a fill that wrote held answers recorded
  `held_back=0` (TD-052), so nothing could show afterwards which files held them.
- **Decision:**
  - An approval keeps the flag and the reason it replaced, in the answer's
    stored JSON (`AnsweredQuestion.before_approval`) rather than a column:
    no migration (TD-046), every stored answer loads unchanged, and an older
    build ignores the key. Withdrawing restores them, and rewording an
    approved answer withdraws the approval the same way
    (`selection.approve`, `selection.withdraw_approval`). An approval from
    before kept nothing, so withdrawing it applies the review's rule again.
  - The `file_filled` event records the gate's count (`held_back`) whether or
    not the gate was opened, and `include_unreviewed`. The fill response keeps
    `held_back` empty after a deliberate "Write them in anyway".
  - "Write them in anyway" names the held answers the person was shown
    (`unreviewed_ids`), and only those are written; one held since stays out
    and comes back in `held_back`. The event records which went in
    (`written_anyway`), and the response how many (plan 029's review: the
    confirm counted the last Fill's list, and the server wrote what was held
    at the click). A request that names none writes every held answer, as
    before.
  - `python -m src.cli inspect fills` reads both to list the fills that wrote
    held answers, and writes nothing. An answer cleared after a fill, and a
    fill of a questionnaire no longer on the server, are listed as unknown.
- **Consequences:** a withdrawal restores the flag the answer had, whatever
  the threshold is now; only an approval from before this uses today's
  threshold. Answers released by a withdrawal before this stay released until
  somebody edits or approves them: they are listed, not repaired. Approving
  one records what the review's own rule says (`selection.held_by_the_review`)
  rather than the cleared flag, because the stored state contradicts that
  rule and recording it would release the answer again on the next
  withdrawal (plan 029's review). Events from before have no
  `include_unreviewed` key.
- **Date:** 2026-11-05. **Status:** accepted; a default the user can reverse
  after testing plan 029. **Decided by:** the user (kept, not derived); Claude
  (where it is kept, the event's fields, listing rather than repairing).

## D-021: the Workbench keeps a person's place, and one run holds a questionnaire

- **Context:** the team lost work on the Workbench (plan 029's feedback). A
  reload opened nothing; "Or pick up" offered three questionnaires, by upload;
  the same file again made a second, empty questionnaire; a run saved its
  answers only at its end, outlived nginx's 15 minutes, and could be started
  again, paid for twice, while it was still going.
- **Decision:**
  - A questionnaire's last use is its last change (`form_batches.updated_at`,
    which every write moves). "Or pick up" lists every one, last changed first,
    up to 500. The open one is in the page's address (`?q=<id>`), which opens
    only for its owner. No migration.
  - The same file again is matched by its bytes against this person's
    questionnaire files still on disk, before anything is saved or read, and
    offered to open or start fresh (`if_already_open="ask"`, sent only by the
    Workbench). Not a stored fingerprint: that needs a migration (TD-046).
    One nothing was read from is not offered: a Word file written as prose is
    read as text again (plan 029's review; TD-065).
  - Each answer is saved as it finishes. One run at a time per questionnaire,
    held in memory (`src/busy.py`), and nothing else changes it until the run
    ends: one writer at a time, rather than letting edits through and merging
    at the end. A run carries on after a reload or a timeout, as before, and
    the page follows it.
  - Leaving the Workbench with work only the page holds asks first; nothing
    is saved on the way out.
- **Consequences:** opening or filling a questionnaire does not move it up the
  list. During a run nobody can edit that questionnaire, in the Workbench or
  the chat. The hold assumes one process (TD-063), and a run that never ends
  holds its questionnaire until a restart (TD-064). The chat does not yet ask
  about the same file (TD-062).
- **Date:** 2026-11-05. **Status:** accepted; defaults the user can reverse
  after testing plan 029. **Decided by:** Claude, on the design's
  recommendations recorded in plan 029's decision log.

## D-022: a questionnaire's or a chat's product is always chosen; General is a choice, never a default

- **Context:** the team reported that the product "defaults to General and
  sometimes resets" (plan 029's feedback), and it was reproduced: both pages
  started on General, every reload rebuilt them on General, a deleted product
  fell back to General, and New conversation carried the last choice over to
  the next chat. A questionnaire answered for General by accident is answered
  without the product's own policies and past answers, and its approvals are
  filed in the shared memory.
- **Decision:**
  - The Workbench and the chat start with no product chosen ("Product:
    choose…"). General is one of the choices, "General (shared policies
    only)", chosen like any product.
  - Reading any file (a PDF included), answering a typed or PDF list, and a
    new chat's first message wait for a choice. Enter waits as Send does. In
    the chat a file can be attached first: nothing reaches the server until
    Send. A team with no products still chooses General.
  - The rule is kept where a file is read, not on one button: the "You
    already have this file" box's "Start fresh" is for the product chosen
    now, and waits while nothing is (plan 029's review of Stage 2: it opened
    the file as General after Clear all or a deletion). Its copies each name
    their product, General's included.
  - "Last used" fills the choice in one click and is never preselected. It is
    derived from the person's own saved questionnaires and chats, and from
    what they did on the page; nothing new is stored.
  - Close questionnaire, Clear all of an answered list, New conversation from
    an open chat, a reload and a deleted product all go back to "choose…". The
    product of the work just left is offered as "Last used".
  - A fixed product reads as a label in its colour, and the Workbench's review
    heading names it.
  - The server is unchanged: it still reads a missing product as General
    (TD-066). The pages send `""` for General through `Cards.serverProduct`,
    the one line to change when the server refuses a missing product.
- **Alternatives:** remembering the last choice in the browser (per device,
  empty in private windows, a choice rather than work done, so a product
  chosen and abandoned would be suggested); or in the person's preferences on
  the server (a new write on every questionnaire and chat start, in modules at
  their size ceilings, and an API change). Deriving it needs neither, follows
  the person across computers, and is literally their last work.
- **Consequences:** one more click for every new questionnaire and chat, one
  for a person who works on one product all day (on "Last used"). A typed list
  answered and never saved is not remembered after a reload. Scripts, the API
  and the evaluation can still answer as General without saying so (TD-066).
- **Date:** 2026-11-05. **Status:** accepted; the defaults are the user's to
  reverse after testing plan 029. **Decided by:** the user (no silent General,
  a one-click "last used"); the defaults by Claude, from plan 029's design.
  Supersedes plan 024's decision log entry of 2026-10-06 ("New conversation
  keeps the chip's choice").

## D-023: the knowledge base has a page of its own

- **Context:** the team's feedback (plan 030): the Workbench opened on
  knowledge-base tools, and the questionnaire upload was a screen further down.
  Curating the knowledge base is occasional; questionnaires are daily.
- **Decision:**
  - The knowledge-base tools move to a Knowledge base page at `/knowledge`,
    linked from every page header. They are the same tools, with the same
    confirmations and the same rights: any member may add, remove and clear.
  - The Workbench opens on the questionnaire. One line says how many documents
    its answers draw on and links to the page.
  - The document viewer that citations open, and Search, stay on the Workbench.
    The chat's knowledge-base drawer stays, with a link to the page.
- **Consequences:** the viewer exists in three copies (TD-067). Who may remove
  shared documents is a later decision.
- **Date:** 2026-11-06. **Status:** accepted. **Decided by:** the user (the page,
  from the team's feedback); Claude (keeping the drawer and the rights as they
  were, which the user can reverse).

## D-024: confidence agrees with the release decision

- **Context:** what the gate releases contradicted the team in 1% of the held-out
  answers, and what it held in 17 to 29%. But one held answer in eight showed
  "High confidence 85%+", and those contradicted the team in 12% of cases (plan 030).
- **Decision:**
  - A held answer's score is capped at the review threshold, and at 0.3 when the
    reviewer found it not grounded. 0.3 is a constant tied to the review prompt's
    own scale, not a setting.
  - The drafter's "sources disagree" check goes through the same assessment, and
    so through the cap.
  - The explanation of a low score describes the rating before the cap.
  - Every comparison holds an answer at or under the threshold
    (`verification.held_by_score`). The pages read the threshold from the server.
  - The card leads with its status and reasons; the score comes second, and the
    colour follows the status.
- **Consequences:**
  - The same answers are released and held as before, with one exception on the
    safe side. An unflagged answer at exactly the threshold is now held; the gate
    used to hold only scores under it. The pipeline never produces such an answer.
    A withdrawn approval (TD-053) or a threshold changed since drafting can leave
    one, and `inspect fills` still lists those that past fills wrote.
  - On the recorded evaluation runs, 0 decisions changed and 19 held answers lost
    a "High" score.
  - Confidence bands before and after are not comparable (evaluation.md).
  - Answers stored before the change keep their uncapped scores (TD-068).
- **Date:** 2026-11-06. **Status:** accepted. **Decided by:** the user (the round);
  Claude (the caps, which the user can reverse).

## D-025: a question answered in the chat is shown as its answer card

- **Context:** the chat model rewrote the drafted answer in its own words. In
  stored chats, 6 of 12 direct answers were paraphrased, and in one Arabic test
  the rewrite contradicted a correct draft. The chat showed no confidence.
- **Decision:**
  - Each drafted answer is shown under the reply as the Workbench's answer card,
    word for word, with its status, confidence and the clauses it cites. It is
    read-only, because no questionnaire stands behind it.
  - The cards are stored with the reply, not in a table of their own.
  - The model's own reply is one sentence leading into them, and must not
    restate the answer.
  - The sources listed under the reply are the cited clauses.
- **Consequences:** this changes text the model sees, so the paid assistant
  evaluation should be run again. Whether the model keeps to a lead-in is
  instructed, not enforced.
- **Date:** 2026-11-06. **Status:** accepted. **Decided by:** the user (plan 030).

## D-026: a product's questionnaire names its product, and every source says whose it is

- **Context:** the user found that product answers "mix unrelated information
  from the shared knowledge base, and it sounds like it is information related
  to the product". Measured on 24 product questions, 6 released answers stated
  a product fact, such as its hosting or its encryption, that only shared
  material supported. Some of it came from an earlier answer about another
  product. The drafter had been told that some sources were "FOR THIS PRODUCT",
  but never which product, and nothing about the rest.
- **Decision:**
  - The drafter and the reviewer are told the product's name, its description
    if it has one, and the team's other products. The question block says
    "About: <product>".
  - Every source is marked FOR <product> or SHARED, and a line above the
    sources says which are the product's own, or that none is.
  - The drafter states a shared policy as the organisation's policy, covering
    every product. It takes no product-specific fact from shared material, and
    says when the product's own documentation does not give the detail.
  - The reviewer sets `grounded` to false for a product-specific fact that only
    shared sources support. Saying that the organisation's policy applies to
    the product is grounded.
  - The assistant's own searches in a product's conversation mark shared
    clauses SHARED.
- **Consequences:**
  - A General questionnaire's prompts are unchanged, byte for byte, so the
    house evaluation's numbers still stand.
  - More product answers are held for review: on the 24 questions, 7 were held
    before, and 11 to 13 after, over three runs. Some of those holds are
    correct and some over-cautious.
  - A held answer is read by a person, which is the safe side. An answer with
    no product source of its own can still infer from an organisation-wide
    policy ("Therefore Msegat supports MFA").
  - A product's description, written on the Products page, now reaches the
    drafter. All five local products have none.
- **Date:** 2026-11-06. **Status:** accepted. **Decided by:** the user (plan 031).

## D-027: adding documents waits for a choice of knowledge base; documents are managed on one page

- **Context:** the Knowledge base page started on "Shared, for every product",
  so documents went into the shared knowledge base unless someone changed it.
  The user ruled that this choice is made, as a product is for answering
  (D-022). The chat's Documents drawer duplicated the page. "Your documents"
  listed files the page already listed, under "What is indexed".
- **Decision:**
  - The page opens with no knowledge base chosen. Adding, removing and
    clearing wait for a choice, and the list asks for one.
  - The address names the choice: `?product=<id>`, or `?product=general` for
    the shared one, the value the Workbench already uses for General. The
    Workbench's "Manage" link names what the Workbench chose.
  - The chat's drawer and the page's "Your documents" are removed. "view"
    beside each indexed source opens the document and the text read from it.
- **Consequences:**
  - The API still reads a missing `product` as the shared knowledge base
    (TD-066).
  - What only "Your documents" showed is gone: the person's own uploaded
    questionnaires, files that failed to index, and file sizes.
    `GET /api/documents` stays, and no page calls it.
- **Date:** 2026-11-06. **Status:** accepted. **Decided by:** the user (plan 031).

## D-028: a chat turn is held by its conversation, and the page follows turns by their run id

- **Context:** a turn runs inside its request. Opening another conversation
  while one worked threw its progress away. When the reply came, it set the
  page's conversation id and answers panel over the conversation then on
  screen. One page-wide `busy` flag blocked every conversation.
- **Decision:**
  - `chat_running` holds a running turn by its conversation: its run id, what
    was asked, the file and when it started. It is per process, like
    `progress` and `busy`.
  - A second message, an upload or forgetting the conversation is refused
    with 409 `conversation_busy`.
  - `GET /api/chat/{id}` and `GET /api/chat` say which turn is running.
  - The page tracks each turn by its run id. A reply changes the screen only
    if its conversation is the one on screen. A reopened or reloaded running
    conversation shows the message and its progress. The composer waits only
    in the conversation that is running.
- **Consequences:**
  - Two conversations can work at once.
  - With more than one server process, a turn is seen only by the process
    running it, as a questionnaire's run already is.
- **Date:** 2026-11-06. **Status:** accepted. **Decided by:** the user (plan 031).

## D-029: the Workbench is a questionnaire page in five steps, and review stays on the cards

- **Context:** the team's feedback, and plan 029's measurement of it. With 120 questions at 1366x768, the Answer button sat 14,000 px down and Fill 61 screens down. The team asked for a step-by-step flow and a review table. The user kept the chat as the home page, and chose the cards over a table.
- **Decision:**
  - **Five steps** with a step header: choose and load, check what was found, answer, review, fill and download. A done step folds to one line saying what it holds.
  - **Reading starts** when a file and a product are both there. A file given first waits in the page, and nothing is sent before a product.
  - **Answer** is one button in a bar that stays in view.
  - **"Fill and download"** is one action that says what was written and what was held back.
  - **Under "More":** the other downloads, rewording and "Ask another question".
  - **Review** opens on "Needs review", on smaller cards.
  - **Keys** work while no field has focus: J/K or the arrows move, A accepts, E edits, Esc closes. An accept moves to the next held answer, and a counter says how many are reviewed. There is no "Approve all".
- **Consequences:**
  - The "Read questions from file" click is gone, and the tests that clicked it were changed.
  - Esc keeps an edit, as leaving the editor always has.
  - The keys follow the physical key, so they work on an Arabic layout too.
- **Date:** 2026-11-07. **Status:** accepted. **Decided by:** the user (plan 033).

## D-030: a typed list, or a PDF's or Word text's questions, is a questionnaire with no file to fill

- **Context:** typed questions and PDF and Word text lists were answered statelessly. A reload lost them, and their card actions did nothing. Their runs were saved to `runs`, which no page reads.
- **Decision:**
  - `POST /api/forms/list` stores a list in `form_batches` with format `LIST` (`src/lists.py`). It is owner-scoped, and its product is fixed.
  - A list is answered, reopened, listed and exported like a file questionnaire, and every card action works on it.
  - Fill refuses it with 422 `nothing_to_fill` and offers the downloads. Its cards say "Ready to use".
  - `DELETE /api/forms/{id}` deletes any questionnaire with its answers and its own files. It is refused while it is being answered.
- **Consequences:**
  - The old `/api/assessments/answer-questions` and `/extract` routes stay, for scripts and the evaluation.
  - A question typed beside an open file questionnaire is answered as before: there is no route to add one to it.
- **Date:** 2026-11-07. **Status:** accepted. **Decided by:** the user (plan 033).

## D-031: saved work is deleted after RETENTION_DAYS unused

- **Context:** questionnaires arrive from other companies, often under an NDA, and every one, every list and every chat was kept for good.
- **Decision:**
  - `RETENTION_DAYS`, default 180 (0 keeps everything). Questionnaires, lists, chats and old `runs` not used for that long are deleted, with what is only theirs. Opening one counts as using it (`used_at`, migration 15).
  - A pass runs at start-up and then daily (`src/retention.py`). It skips what is being answered or talked about.
  - It never deletes the knowledge base, the answer memory, products, people or the event log.
  - Each pass that deletes something records one event per team, with counts.
  - The pages say "Kept until".
  - `inspect retention` lists what is due, and writes nothing.
- **Consequences:**
  - "Or pick up" and the chat's list are ordered by last use, so opening one moves it to the top.
  - Uploads in the team's shared folder from before per-person folders are left to the storage limit.
- **Date:** 2026-11-07. **Status:** accepted. **Decided by:** the user (plan 033).

## D-032: consistency comes from the same searches and the same question's earlier answer, not from copying

- **Context:** the same question was answered differently on each run (plan 029: three NAC runs). The user chose to keep drafting every time, not to return earlier answers word for word.
- **Decision:**
  - **The same searches.** The first search plan that worked is kept per team, product, language and folded wording (`search_plans`, migration 16), and used again. `REUSE_SEARCH_PLANS` turns it off.
  - **The same question's earlier answer first.** An earlier answer to the same words is kept first in the sources, beyond the cap, and marked PREVIOUS ANSWER TO THIS SAME QUESTION. The drafter keeps its position and facts unless our policy now says otherwise.
  - **No invented names.** The drafter and the reviewer are told not to claim a technology named in the question unless a source names it.
- **Consequences:**
  - On 12 questions, three runs each, measured against the baseline:
    - same decision: 9 to 11 of 12;
    - same verdict: 11 to 12 of 12;
    - cited sources in common: 0.72 to 0.88;
    - wording in common: 0.41 to 0.57.
  - The drafter's own wording still varies (temperature 0.2).
  - A kept plan does not change when the knowledge base does. What it finds does.
  - Kept plans hold the question's words, so retention deletes them.
- **Date:** 2026-11-07. **Status:** accepted. **Decided by:** the user (plan 034).
