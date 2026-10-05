# What we are building

*Drafted by Claude on 2026-10-05 from the README and the code, at the user's
request. Statements of intent here are inferred from what the code and README
do; the user owns this page and corrects it.*

## The problem

A security team answers assessment questionnaires all year: vendor security
reviews, third-party risk assessments, privacy and compliance attestations from
customers. Each arrives as the customer's own spreadsheet or Word file, asks
the same controls in different words, and must be answered from the team's
policies and from what the team has said before, in English, Arabic, or both
in one form. Doing it by hand is slow and inconsistent; doing it with a
general chatbot produces confident answers the policies do not support.

## What the system does

- **Learns the team's sources.** Policies and standards are indexed as a
  knowledge base; answers the team approved become an answer memory.
- **Reads the customer's file as it is.** It finds the questions in a
  spreadsheet or Word document, works out where each answer and each
  yes/no/partial status belongs, and lets a person correct that reading before
  anything is answered.
- **Drafts grounded answers.** For each question it searches the knowledge
  base and the memory, drafts an answer in the team's own style, reviews it
  against the sources, and cites the clauses it relied on.
- **Holds back what it is unsure of.** Low confidence, ungrounded claims and
  disagreements with remembered answers are flagged for a person rather than
  written into the customer's file.
- **Writes the answers back** into a copy of the customer's own file, keeping
  its formatting, or exports them as PDF, Word, CSV or JSON.
- **Can be driven by conversation.** A chat assistant can do everything the
  workbench can: open a questionnaire, answer, reword, fill.

## Who uses it

Members of a security team, each signed in, each with their own questionnaires
and conversations; the team shares one knowledge base and one answer memory.
Administrators manage people, teams and access codes from inside the
application.

## Qualities that matter more than features

1. **A wrong answer is worse than no answer.** Compliance answers become
   commitments; the system says "not covered" or flags for review rather than
   inventing.
2. **Every answer can be audited**: its sources, its reasoning, and who
   approved it.
3. **Customer and policy data stay where they belong**: per person, per team,
   and inside the country unless the owner decides otherwise.
4. **Arabic is first-class**, including Arabic PDFs whose text layer is stored
   in visual order.

## Not goals

- Submitting a questionnaire on the team's behalf: answers are drafts until a
  person reads them.
- Reconciling contradictory policies: the system reports what it found;
  deciding between two policies is a human job.

For how it works, start with the [overview](overview.md).
