# Plan 026: Product data, cleaned and reviewed (first batch: Ole5)

**Status:** active

## Goal

The team delivered the products' raw material: 71 files in five folders (one
per product, and one of general requests), plus a workbook someone made to
organise them. It is messy: exported email threads and tickets, filled and
blank questionnaires, contracts, risk sheets. Some of it we already hold.

The goal is clean, reviewed data for each product:

- **a fact sheet** for the product's knowledge base;
- **answer pairs** for the product's answer memory;
- **T2-wide items** for the shared ones.

Every item cites where it came from. Nothing in the clean data names a person,
and nothing that was true only on one date is stated as a standing fact.

Nothing reaches the real knowledge base or answer memory in this plan. Importing
is a later plan, run when the user asks for it.

This plan covers four things:

- the survey;
- the tools that make cleaning checkable;
- the first batch, Ole5;
- the user's notes on its sample, which shape the other batches.

The raw files and the clean data stay outside the repository, beside the raw
data. Customer and client names stay out of this record (TD-030), so it gives
counts and categories, not file names.

## What the survey found

*Read 2026-10-18 (Claude). One reader per group of files read every file in
full. A separate auditor checked a sample of the organising workbook against
the files.*

- **Shape.** Availo 3 files, Msegat 5, Ole5 20, RICH 22, general requests 21.
  There are no SouqT2 files.
- **Already held: 15 files.**
  - 13 are byte-identical to completed questionnaires we already have, and 2
    more have the same text. 10 of them are the sources of the shared answer
    memory's 698 entries.
  - **5 are the evaluation's held-out questionnaires**, the ones the 135
    held-out cases are graded against (docs/measurements/evaluation.md).
    Importing them would hand the system the answer key, so they are excluded
    by content hash, and the import will run the contamination check.
- **Duplicated or misfiled.** 2 files appear twice in the delivery, and about 7
  sit in the wrong folder.
- **The organising workbook is an index, not data.** It has 1,384 rows.
  - 908 of them (66%) come from questionnaires we already hold or must not use.
  - Its 444 "inferred" questions are a single template ("what is the approved
    response regarding <file name>? (point N)"), paired with paragraph N of the
    file.
  - In whole files the columns were mapped wrongly: domain labels taken as
    questions, question text taken as answers, the mitigation column dropped.
  - Routing notes, placeholders and staff names were stored as answers.
  - It has no rows for 12 files, among them several of the most valuable.
  - In a stratified sample of 75 rows, 21 were faithful, 18 partly faithful and
    36 wrong or useless; only 6 (8%) were faithful and new.

  Its source locations all resolve, so it is used only as a cross-check that
  nothing answered was missed.
- **What is worth keeping**, by product:
  - **Ole5 has the most.** It is a multi-tenant SaaS correspondence system, and
    its tickets and evidence replies state its tenancy, single sign-on,
    monitoring, penetration-test stance, backups, data export and what it
    discloses. That makes about 30 candidate facts and 30 pairs.
  - **RICH** has an architecture and hosting description in the team's own
    words, and one questionnaire answered in full. But its hosting is described
    three different ways, which the team has to settle first.
  - **Availo** has a handful of facts, mostly from a draft that waits for
    confirmation.
  - **Msegat** has almost nothing about the product: its folder's answers are
    T2-wide.
  - **General requests** has T2-wide answered questionnaires (one about 2021),
    data-processor procedures and certification statements. It also has a
    filled questionnaire for a product the files do not name.
- **Not to be kept.** This covers scheduling and status emails, account
  support, legal templates, blank forms, and drawn checkbox selections that
  text cannot read reliably. It also covers assessor findings. A finding is
  what a client recorded, not what T2 does, so it never becomes a fact.
- **Contradictions for the team.** The survey found six:
  - the hosting provider and data centres;
  - the SOC 2 status (being prepared, or a Type II report held);
  - whether a Data Protection Officer is appointed;
  - one client's risk register against Ole5's stated controls;
  - how business-continuity tests are described;
  - incident-notification times.

  Each batch lists the ones that touch it, as questions for the team, and
  resolves none of them itself.
- **Found in passing.** Three entries in the live shared memory need the user's
  decision (TD-036), and the import path has a latent bug (TD-035).

## Decisions needed (the user's)

Each is listed with Claude's recommendation.

1. **Review format.** One workbook per batch with five sheets:
   - Facts;
   - Q&A;
   - Questions for the team;
   - Files, with what was done with each;
   - Read me, which explains the columns.

   Each row has a Decision column (keep, edit, drop) for the reviewer. The fact
   sheet document is generated from the rows kept. *Recommended.*
2. **What may become a fact.** Only something T2 stated, to a customer or in
   its own documents. Drafts, dated statuses, contradictions and anything
   unconfirmed are listed but proposed as "hold", not "keep". *Recommended.*
3. **Shared-memory entries whose questionnaire sits in a product folder.** For
   example, 193 entries come from two questionnaires in the Ole5 folder.
   *Recommended:* keep them shared for now. Their answers are mostly T2-wide,
   and the product's own facts take precedence where they differ (plan 018,
   decision 2). Re-tagging is a later, per-entry choice.
4. **T2-wide material** from the product folders and general requests goes into
   one shared batch after the products. It will produce a shared fact sheet and
   shared pairs, de-duplicated against the 698 entries. *Recommended.*
5. **The unnamed product** in general requests (a link and QR-code platform)
   needs the team to name it, or to add it as a new product.
6. **Order after Ole5:** RICH once its hosting is settled, then Availo, Msegat,
   and the shared batch. *Recommended.*

## Acceptance criteria

- [x] Every delivered file and the organising workbook are surveyed, and the findings recorded here without customer names.
- [ ] `scripts/product_data.py`, tested on synthetic files:
  - extracts a file's text with locations (paragraph, table cell, sheet cell);
  - validates a clean batch:
    - every item cites a source whose quote is found in that file;
    - no email address or phone number appears anywhere;
    - a dated item carries its date;
    - only standing facts may be proposed for keeping;
    - no source is an excluded file (by content hash);
    - ids are unique;
  - writes the review workbook, and the fact sheet from the rows kept.
- [ ] Batch 1, Ole5: clean data in its review workbook. Each item was extracted from the files, not from the organising workbook, and checked against its source by a second reader. The batch passes validation.
- [ ] The user's notes on the Ole5 sample are recorded in the decision log, and the tools and rules are changed to match.
- [ ] TD-035 and TD-036 recorded.
- [ ] `uv run poe check` passes.

## Plan

1. Survey (done above).
2. Write `scripts/product_data.py` and its tests.
3. Clean Ole5:
   - one set of readers extracts candidate facts and pairs, each with a verbatim quote and its location;
   - a second set tries to refute each item against the file;
   - a consolidator merges duplicates and lists contradictions and questions for the team;
   - the batch is validated, and the workbook and the draft fact sheet are written beside the raw data.
4. Show the user a sample. Record their notes, and adjust the tools and rules.
5. Later plans: the remaining batches, then the import (contamination check, product knowledge base, product memory, TD-035).

## Progress log

- 2026-10-18: Survey done (see above). 8 readers, 58 files read in full; the 13 byte-identical files were not re-read.
- 2026-10-18: Step 2. `scripts/product_data.py` is in place, with 19 tests (`tests/test_product_data.py`, synthetic files only). Three were checked against their regressions, and each failed with its check undone: a quote not in its file, an excluded file, and a dated fact proposed for keeping.
- 2026-10-18: Step 3, Ole5. It covers the folder's 18 files that are not copies, plus an Ole5 email filed under general requests.
  - Three readers extracted 66 facts and 31 pairs, each with a located verbatim quote.
  - Three second readers rejected 5 items, fixed others, and added the ones that had been missed.
  - The consolidator merged the result to 60 facts, 31 pairs and 27 questions for the team. Of these, 23 facts and 12 pairs are proposed for keeping:
    - 13 facts and 4 pairs about Ole5;
    - the rest T2-wide, for the shared batch.
  - `check` found 0 problems. A scan for client names found none in any fact, question or answer.
  - The draft fact sheet holds the 13 kept Ole5 facts.
  - The workbook and the fact sheet are beside the raw data, not in the repository.
- 2026-10-18: Reading the batch whole, before showing it, turned up three points for the user's notes:
  - 9 of the 10 T2-wide facts proposed for keeping restate policies already in the shared knowledge base.
  - Several answers point to an attachment ("please find attached"), which would read wrongly in another customer's questionnaire.
  - The heightened-alert checklist's "implemented" answers wait on whether the checklist was T2's and was sent.

  One fix came from it: the draft fact sheet said "reviewed by the team" before any review. It no longer does, and a test holds that.

## Decision log

- 2026-10-18: The clean data is built from the source files, not from the organising workbook. A sample of its rows against the files showed 8% faithful and new, and whole files with shifted columns, so cleaning its rows would cost more than reading the files. Its locations all resolve, so it stays as a cross-check. (Claude)
- 2026-10-18: Ole5 first. It has the most product-specific content, and every kind of source file appears in its folder: tickets, an evidence reply, a status sheet and an agreement. Its sample therefore exercises every rule the later batches need. Availo is too small to show much, Msegat's material is T2-wide, and RICH needs a hosting decision first. (Claude)
