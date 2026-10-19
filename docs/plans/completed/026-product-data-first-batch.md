# Plan 026: Product data, cleaned and reviewed (first batch: Ole5)

**Status:** completed

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
- [x] `scripts/product_data.py`, tested on synthetic files:
  - extracts a file's text with locations (paragraph, table cell, sheet cell);
  - validates a clean batch:
    - every item cites a source whose quote is found in that file;
    - no email address or phone number appears anywhere;
    - a dated item carries its date;
    - only standing facts may be proposed for keeping;
    - no source is an excluded file (by content hash);
    - ids are unique;
  - writes the review workbook, and the fact sheet from the rows kept.
- [x] Batch 1, Ole5: clean data in its review workbook. Each item was extracted from the files, not from the organising workbook, and checked against its source by a second reader. The batch passes validation.
- [x] The user's notes on the Ole5 sample are recorded in the decision log, and the tools and rules are changed to match.
- [x] The other batches (RICH, Availo, Msegat, shared) are cleaned under the same rules and pass `check`. Every held item from every batch is in one workbook for the team's later review.
- [x] The shared entries from questionnaires filed in a product's folder are sorted. Product-specific ones are proposed for moving, and the uncertain ones are listed for the team.
- [x] The live-memory changes are applied with the app stopped: `MEM-0519` and `MEM-0400` forgotten, `MEM-0397` moved to RICH.
- [x] TD-035 and TD-036 recorded.
- [x] `uv run poe check` passes.

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
- 2026-10-19: The user's notes, applied to Ole5:
  - 12 facts and 9 evidence answers that only restated a policy in the shared knowledge base were dropped.
  - The single sign-on answer was rewritten to stand without its attachment, and is marked rewritten.
  - Two items were held: the database-encryption fact, because its only source names no product, and the reports-under-NDA fact, because two shared answers say reports are never shared.

  Ole5 now has 12 facts and 4 pairs ready to use. Its earlier workbook was open in Excel, so the revised files were written under new names ("v2").
- 2026-10-19: The tools followed the notes:
  - `scripts/product_data.py` records `rewritten` on a pair;
  - `held` writes one workbook of every held item, every question for the team, and the live entries held rather than moved, across every batch;
  - the shared batch gets a T2-wide fact sheet;
  - a quote may be a single-word cell, since its location is exact.

  `scripts/memory_changes.py` (8 tests) applies forgets and moves to the live memory. Two of its checks were tested against their regressions: the app-running guard and the unknown-product refusal.
- 2026-10-19: Availo, Msegat and RICH were cleaned with the same workflow: three passes, with your rules in the prompts.
  - Availo: 1 fact and 1 pair kept (DDoS protection is enabled). Its other 4 facts and 1 pair are held, most of them from a June draft that was never confirmed.
  - Msegat: nothing about the product can be kept. One T2-wide fact (the ISO/IEC 27001-certified ISMS) goes to the shared batch.
  - RICH: 27 facts and 27 pairs are kept, most of them T2's own answers in a client's security-requirements form. Its hosting, described three ways, is held.

  Every batch passes `check`.
- 2026-10-19: The shared entries from the Ole5 folder's two questionnaires were sorted: 181 general, 11 unclear, 1 conflicting. Neither questionnaire can be shown to concern Ole5. One asks only about "your organisation"; the other describes an unnamed SaaS on Alibaba Cloud, which fits Availo as well. So nothing moves, and the 12 unclear or conflicting entries are listed for the team's review.
- 2026-10-19: The shared batch merged the 13 general-request files with the 51 T2-wide items the product batches had set aside. It keeps 30 facts and 17 pairs: certifications, NCA/ECC compliance, evidence-sharing terms, the data-copy procedure, corporate MFA and EDR, incident escalation. It holds 45 facts and 28 pairs, including everything from a 2021 insurance form and an unfinished 2026 checklist, and the open conflicts on breach-notification time, the DPO, SOC 2 sharing and the SOC/SIEM provider.
- 2026-10-19: `check` caught an agent citing one of the five held-out questionnaires, which it had been told never to open. The consolidator had gone looking for evidence about the data protection officer. The source, and the sentence of the note that came from it, were removed, so the batch holds nothing from that file. The citation check catches a cited source. An item shaped by such a file without citing it would be caught at import instead, by the contamination check that compares remembered questions with the house set (plan 013). The import plan must run it.
- 2026-10-19: The shared entries from RICH's six folder questionnaires were sorted: 391 general, 40 unclear, 2 conflicting, 1 specific.
  - Only one questionnaire names the product: the RiCH communication platform, for an SMS managed service. Its answers are mostly T2's stock wording (in-Saudi hosting as a rule, tenant isolation, TLS), so they stay shared, where RICH can still use them.
  - The one moved is `MEM-0397`, that the service processes personal and sensitive data.
  - The 42 uncertain or conflicting entries stay shared and are listed for the team; the two being forgotten are left off the list.
- 2026-10-19: What can be used now, counting each item once, where it is used: a product's own items in its batch, and T2-wide ones in the shared batch:

  | Batch | Facts kept | Pairs kept | Facts held | Pairs held |
  |---|---|---|---|---|
  | Ole5 | 12 | 4 | 23 | 8 |
  | RICH | 27 | 27 | 9 | 10 |
  | Availo | 1 | 1 | 4 | 1 |
  | Msegat | 0 | 0 | 4 | 3 |
  | Shared | 30 | 17 | 45 | 28 |

  The held-items workbook has 276 rows: these 135 held facts and answers, 88 questions for the team, and 53 live entries held rather than moved. A T2-wide item is held once, in the shared batch. A product batch's own copy is not counted again, and a test holds that.
- 2026-10-19: Three live-memory changes wait for the app to be stopped: forget `MEM-0519` and `MEM-0400`, and move `MEM-0397` to RICH. They are in a changes file beside the clean data, and `scripts/memory_changes.py` previews them. Importing the clean data is the next plan, when the user asks for it.
- 2026-10-19: The user stopped the app. Nothing answered on its port and no app process was left.
  - The database (34 MB) and the vector store (241 MB) were copied beside the raw data, as a backup to undo from.
  - `scripts/memory_changes.py --apply` made the three changes, recorded under the user's account.
  - Checked afterwards, read-only: the memory has 695 entries; `MEM-0519` and `MEM-0400` have no row and no vector left; `MEM-0397` belongs to RICH and its vector is in RICH's collection only.
  - The moved entry is compared with RICH's other answers the next time the app sweeps the memory.
- 2026-10-19: `uv run poe check` passes: 1,892 tests and 13 browser tests. Plan complete. Importing the clean data is the next plan, run when the user asks for it.

## Decision log

- 2026-10-18: The clean data is built from the source files, not from the organising workbook. A sample of its rows against the files showed 8% faithful and new, and whole files with shifted columns, so cleaning its rows would cost more than reading the files. Its locations all resolve, so it stays as a cross-check. (Claude)
- 2026-10-18: Ole5 first. It has the most product-specific content, and every kind of source file appears in its folder: tickets, an evidence reply, a status sheet and an agreement. Its sample therefore exercises every rule the later batches need. Availo is too small to show much, Msegat's material is T2-wide, and RICH needs a hosting decision first. (Claude)
- 2026-10-19, by the user, on the Ole5 sample:
  - **Restated policies.** Drop a fact or answer that only restates a T2 policy already in the shared knowledge base.
  - **Answers that point to an attachment.** Rewrite the answer so it stands on its own, and keep it; drop it if it cannot stand without the attachment.
  - **The team cannot review anything now.** Use only items with no conflict and no gap. Collect every held item from every product in one place, for a later review.
  - **Shared entries from questionnaires filed in a product's folder.** General information about T2 stays shared; information specific to the product moves to the product's memory. Some move and some stay, and the outcome is reported to the user.
  - **The unnamed link and QR-code product.** Ignore it.
  - **Order.** RICH, then Availo, Msegat and the shared batch, as recommended.
  - Everything else as recommended.
  - **Live memory.** The user deleted `MEM-0035` themselves and asked Claude to delete `MEM-0519` and `MEM-0400`.
- 2026-10-19: How "no conflict" is read. A disagreement counts only when another T2 source says otherwise about the same product. These do not count:
  - an answer from another product's questionnaire (MEM-0121 "no SSO", MEM-0480 "SIEM integration on request");
  - an answer that disagrees only in wording (MEM-0681: "Yes", but it says T2 tests internally);
  - a client's own risk register, which records the client's finding, not T2's.

  Items that rest on such sources stay usable, and their notes say why. (Claude)
- 2026-10-19: The live memory is changed only with the app stopped. Forgetting and moving both rewrite vectors, and the app (`uvicorn --reload`) holds the vector store open. `scripts/memory_changes.py` applies a reviewed changes file. It previews by default, refuses to apply while anything answers on the app's port, and records the same events as the memory page under the account of the person who decided. (Claude)
- 2026-10-19: Two consistency rules, applied to every batch:
  - **An item whose only link to its product is the folder is held.** Neither its file nor its text names the product, and the survey found misfiled files, so the folder alone does not establish the product. This applies to Ole5's F-027 and Msegat's BCP items.
  - **Provider names stay held while the products' sources disagree.** RICH's material names one SOC provider and Ole5's names another for the SIEM and MSOC, so both are held until the team says which provider does what.

  A held item is not lost: it is in the held-items workbook with the question that would settle it. (Claude)
