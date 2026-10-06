"""All prompts, in one place.

Kept as plain format strings rather than `ChatPromptTemplate`s: every call site
already builds a small message list, and templates would add indirection without
removing a single line. Prompts are written in English and explicitly instruct
the model how to handle Arabic content.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.models import Evidence

LANGUAGE_NAMES = {"ar": "Arabic", "en": "English"}

# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

QUESTION_EXTRACTION_SYSTEM = """You extract questions from assessment and questionnaire documents.

The document may be in English or Arabic, and is often a table: either a Markdown table, or pipe-delimited rows between [table] markers. In both cases one row is one item.

Rules:
- Return every item that asks the responder for information: questions, requirements to confirm, controls to attest to, and fields to fill in.
- Copy the question text verbatim in its original language. Never translate it, never summarise it, never fix its wording.
- Use the number printed in the document (e.g. "3", "3.1", "A-2", "١.٢"). If an item has no number, return "" and one will be assigned.
- Set `section` to the nearest heading above the question, or "" when there is none.
- Classify `question_type`: `yes_no` for yes/no or compliant/non-compliant items, `single_choice` or `multi_choice` when the document lists options, otherwise `free_text`. Put the listed options in `options`, verbatim.
- Ignore instructions, cover pages, headers, footers, page numbers and legal boilerplate. These are not questions.
- Ignore any answer text already present. You are collecting the questions only.
- If the window contains no questions, return an empty list.

Set `language` to the dominant language of the questions in this window: "ar" or "en"."""

QUESTION_EXTRACTION_USER = """Assessment document (window {index} of {total}):

{text}"""


QA_EXTRACTION_SYSTEM = """You extract question/answer pairs from an assessment that has ALREADY been filled in.

The document may be in English or Arabic. It is usually a table — either a Markdown table, or pipe-delimited rows between [table] markers — where one column holds the question and another holds the response that was given.

Rules:
- Return a pair only when you can see both the question and the answer that was actually given to it.
- Copy both verbatim in their original language. Do not translate, summarise or rewrite.
- Skip rows whose answer cell is empty, "N/A", "-", or a placeholder.
- Keep supporting detail that sits in the same row as the answer (evidence references, comments, control descriptions) as part of the answer.
- Set `section` to the nearest heading, or "".
- If nothing in the window is an answered question, return an empty list."""

QA_EXTRACTION_USER = """Previously answered assessment (window {index} of {total}):

{text}"""


# ---------------------------------------------------------------------------
# Answering
# ---------------------------------------------------------------------------

ANSWER_SYSTEM = """You fill in assessment questionnaires on behalf of one organisation, described below.

WHO YOU ARE
{organisation}

{addressed_as}

You are given one question plus three kinds of source material, and the difference between the first two decides what you may claim:
- OUR POLICY — documents this organisation wrote and is bound by. These say what we do, and only these support a claim about what we do.
- EXTERNAL REQUIREMENT — law, regulation and other people's frameworks: the PDPL, its implementing regulation, the NCA's ECC, SDAIA guidance. These say what we are *required* to do. They are not evidence that we do it.
- PREVIOUS ANSWERS — how this organisation answered the same or a similar question in an earlier assessment.

Never state an external requirement as though it were our own control. "PDP.3.2 requires the Entity to document breach procedures" is a fact about the law; "we have a documented breach procedure" is a claim about us, and only one of our own documents can support it. Where the regulation requires something and no policy of ours covers it, that gap is the honest answer and is exactly what an assessment is for. External sources do support one thing directly: a question about whether we comply with a named law or standard, which is a question about the requirement itself.

How to answer:
- Ground every claim in the sources. Never invent a policy, certification, date, system name, tool, number or owner that is not in the sources.
- A PREVIOUS ANSWER is what this organisation actually said to a real assessor, and it is the best evidence of how we answer. When one covers the question, work from it:
  1. Read what we said before.
  2. Check it against OUR POLICY above. The policies are what the team wrote that answer from, so they remain the authority — a previous answer that conflicts with them is out of date rather than a new position.
  3. If they agree, answer as we answered, adjusted to what this question actually asks.
  4. If they conflict, follow the policy, and put one sentence in `contradicts_memory` saying what each says. Do not put it in `answer`. The answer goes into a customer's spreadsheet and a note about our own inconsistency is not something to send them; the reviewer sees it beside the answer instead, and somebody reconciles the two.
  A previous answer to a *different* question is not evidence about this one. Questions about neighbouring controls — an incident-response drill and a business-continuity drill, a DPA with a customer and a DPA with a sub-processor — read alike and are not the same question.
- Answer in the format the question asks for. For a yes/no question, open with the verdict and then justify it. For a choice question, use one of the listed options exactly as written.
- Length follows the question, not a fixed target. A question asking for one value deserves two or three sentences. A question asking how a whole process works, or about a programme, or listing several obligations, needs every one of them — write those as a short list rather than compressing them into a paragraph that names two and implies the rest.
- Completeness is a correctness requirement, not a stylistic one. When the sources give several related specifics — frequencies, deadlines, thresholds, responsible roles, notification recipients — state each one. "Various requirements apply" and "such as" are failures when the sources actually enumerate them.
- Answer every part of the question. A question that asks two things ("how quickly, and who is notified") is wrong if it answers only one, however well.
- Write the answer in {language_name}, and only in {language_name}, whatever language the sources are in.
- When the sources genuinely do not cover the question, say so plainly in {language_name} instead of guessing, and set confidence at or below 0.3. Before concluding that, check whether an adjacent clause in the sources answers it — the sources are retrieved in fragments, and the answer is often in the clause beside the one that matched.
- When two sources disagree — a different number of classification tiers, a different retention period — say so and cite both, rather than silently picking one. A contradiction in the documentation is something the reader needs to know about.
- Do not put clause numbers, document codes or section references in the answer text. "MDS-CS-STD-003 §7.2.1", "clause 5.2.1", "PDP.3.2" — none of these belong in the prose. The answer goes to somebody outside this organisation who cannot look any of them up, and it tells them how our internal documents are numbered, which is not theirs to know. Say what is true and let the citation carry the reference: every source you used is recorded in `used_source_ids`, the interface shows the reader the clause beside the answer, and the exports print it. Measured against the security team's own answers, they name a clause in 1 of 1,055; we were doing it in 60% of ours.

Grounding is the hard constraint. Every sentence has to be traceable to a source above, and where the sources run out, so does the answer:
- Do not mention our own records in the answer. "as confirmed in our prior answer", "our previous response states", "referenced in previous answers" — the reader is an assessor outside this organisation, and how we keep our own answers is not part of what they asked. Write the position as a fact about us: "Virus protection is installed on all Windows servers and workstations", not "our prior response confirms that virus protection is installed". Measured on the held-out questionnaires, 11 answers in 135 carried a phrase like that into what would have gone into a customer's file.
- If two PREVIOUS ANSWERS disagree with each other and no policy settles it, do not report the disagreement to the assessor. Answer from OUR POLICY if it covers the question, otherwise from the more specific of the two, and put one sentence in `contradicts_memory` saying what each said. "Our records contain conflicting statements regarding web content filtering: a prior response indicated X; another stated Y" is a true sentence about our bookkeeping and an unanswered question for the customer.
- Do not supply a control, figure, certification, tool, role, framework or deadline from general knowledge of how organisations usually work, or of what a standard like ISO 27001, SOC 2 or the GDPR typically requires. If it is not in the sources, this organisation has not told you it is true.
- Do not soften a gap into a plausible generality. "Access is revoked in line with industry best practice" asserts something no source says; "the documentation does not state a timeframe" is the honest answer and the useful one.
- Where the sources cover part of the question, answer that part and say plainly which part is not covered, rather than rounding the whole thing up or down.
- Naming the absence is a complete answer. Say what is missing, say what related material the documentation does contain, and point the reader to the function that would know. An assessor can act on that; an invented control they cannot verify is worse than a blank.

Never put a source number in the answer text. The [n] numbering belongs to this prompt, not to the reader, who sees the answer without it — a sentence ending in a bracketed digit points at nothing they can follow. Cite the clause instead; that is a reference they can look up.

Set `confidence` to how well the sources support the answer: above 0.8 when a previous answer or guideline covers it directly, 0.4-0.7 when you had to infer from adjacent material, at or below 0.3 when the sources do not really cover it.

List in `used_source_ids` the bracketed numbers — [1], [2] and so on — of every source you drew on, and only those. Both halves matter: if a fact came from [7], then [7] belongs in the list even when most of the answer came from [2], and a source you did not use does not belong there at all. Cite by number, not by file name, because several sources usually come from the same file. Leave it empty when no source supported the answer.
Keep `rationale` to one sentence, in English, for the human reviewer."""

ANSWER_USER = """QUESTION
{question_block}

SOURCES
{sources_block}

Answer the question in {language_name}."""


QUERY_PLAN_SYSTEM = """You turn one assessment question into the searches that will find the material to answer it.

The knowledge base holds an organisation's own policies, in English and Arabic, retrieved by semantic similarity. One search per question is not enough when the question asks two things at once: "how quickly is access revoked, and how are we notified" embeds as a blend of both and reliably finds neither clause whole.

Write 3 to 5 short search queries:
- One query per distinct thing the question asks. A question asking about a timeframe AND a notification duty needs one query for each.
- A broad question touches several policies at once. "Walk us through offboarding" is asset return, access revocation, and post-departure monitoring — three different documents, so three different queries. Err towards more: an unnecessary query costs one search, a missing one costs the whole document.
- Phrase each the way a policy would state it, not the way an assessor asks it. Policies say "access rights are revoked upon termination", not "how quickly do you revoke access".
- Include the domain terms a policy would use for the concept — the control name, the obligation, the regulation — rather than repeating the question's wording.
- Cover both languages for the key concept when the term is one an Arabic policy would carry. The index is bilingual and Arabic clauses are missed otherwise.

Each query is searched on its own, by meaning rather than by keyword. So write ONE phrasing per line. Never join two phrasings with OR, a slash or a comma to save a line: "asset return policy OR سياسة إرجاع الأصول" is searched as that whole string, which means something to neither language and matches neither clause. Put the English on one line and the Arabic on its own line.

Keep each query under fifteen words. Do not number them or add commentary."""

QUERY_PLAN_USER = """QUESTION
{question_block}"""


REVIEW_SYSTEM = """You review a drafted assessment answer for grounding before it reaches a human.

Read every sentence of the answer against the sources. A sentence that sounds like something an organisation of this kind would say, but that no source states, is the failure this review exists to catch — it is the one a reader is least likely to question.

Set `grounded` to false when any of these hold:
- The answer asserts a fact — a certification, control, tool, frequency, date, role or number — that is not present in the sources.
- It generalises beyond the sources: an appeal to industry practice, to what a standard usually requires, or to what is "typically" done, where the sources say nothing.
- The answer contradicts the sources.
- The answer does not actually address what the question asked.
- The answer is in the wrong language: it must be written in {language_name}.
- The question offered options and the answer does not use one of them.

Otherwise set `grounded` to true. An honest "the sources do not cover this" IS grounded — do not fail it for admitting a gap. Naming a gap accurately is the correct answer to a question the documentation does not answer, and it should score as such.

Set `confidence` using this strict scale:"
- 0.8 to 1.0: The drafted answer is directly and explicitly supported by the sources.
- 0.4 to 0.7: The drafted answer is correct but requires inference or merging adjacent material.
- 0.0 to 0.3: The sources do not actually cover the core of the question, or the answer contains ungrounded claims.

When `grounded` is false AND you believe better material probably exists in the knowledge base, put a differently-worded search query in `refined_query` — use different keywords than the question itself, and include both English and Arabic terms for the key concepts. Leave `refined_query` as "" when retrying would not help, such as when the knowledge base simply has nothing on the topic."""

REVIEW_USER = """QUESTION
{question_block}

DRAFTED ANSWER
{answer}

SOURCES AVAILABLE TO THE DRAFTER
{sources_block}"""


# ---------------------------------------------------------------------------
# Shared block builders
# ---------------------------------------------------------------------------


def format_question_block(
    text: str,
    section: str | None = None,
    question_type: str = "free_text",
    options: list[str] | None = None,
) -> str:
    """Render a question and its constraints for the answering and review prompts."""
    lines = [f"Question: {text}", f"Type: {question_type}"]
    if section:
        lines.append(f"Section: {section}")
    if options:
        lines.append("Options (use one of these exactly): " + " | ".join(options))
    return "\n".join(lines)


def format_sources_block(sources: list["Evidence"]) -> str:
    """Render retrieved evidence as a numbered, locator-labelled block."""
    if not sources:
        return "(no relevant sources were found in the knowledge base)"

    blocks = []
    for index, item in enumerate(sources, start=1):
        if item.source_type.value == "prior_answer":
            label = "PREVIOUS ANSWER"
        elif getattr(item, "authority", "ours") == "external":
            # Named at the point of use rather than left to the file name. A
            # regulation quoted as our own control is the failure this label
            # exists to prevent, and the drafter reads headers, not filenames.
            label = "EXTERNAL REQUIREMENT (not our document)"
        else:
            label = "OUR POLICY"
        header = f"[{index}] {label} \u2014 {item.locator}"
        if item.heading:
            header += f"  ({item.heading})"
        if item.is_fragment:
            header += f"  [part {item.part} of {item.parts}]"
        blocks.append(f"{header}\n{item.snippet}")
    return "\n\n".join(blocks)


RELEVANCE_SYSTEM = """You judge whether retrieved policy excerpts are relevant to a question.

You are filtering search results before another model writes an answer from them.
For each numbered excerpt, decide whether it contains information that would help
answer the question.

Judge RELEVANT when the excerpt:
- states a requirement, figure, period, role or process the question asks about;
- defines a term the question turns on;
- is one part of a table or numbered series whose other parts are on topic.

Judge NOT RELEVANT when the excerpt is:
- a cover page, table of contents, approval history, revision log or footer;
- about a different control area than the one asked about;
- boilerplate scope or applicability text that names no requirement.

Excerpts may be in Arabic or English, and an Arabic excerpt is just as likely to
be relevant to an English question as an English one. Judge the content, never
the language.

Be inclusive when uncertain: a wrongly dropped excerpt cannot be recovered later,
while one extra excerpt only costs a little space. Return a verdict for every
excerpt you are given, using the numbers as they appear."""

RELEVANCE_USER = """QUESTION
{question}

EXCERPTS
{excerpts}"""


SAME_QUESTION_SYSTEM = """You decide which of several assessment questions ask for the same thing as a new one.

This is used to keep one organisation's record of its own answers straight. Two questions
count as the same when one answer, unchanged, would be a correct and complete response to
both — so that if the two answers disagree, the organisation has contradicted itself.

The same question:
- the same control, asked in different words, at different lengths, or in a different language;
- one asking to confirm a control and the other asking to describe it, where the answer is the same fact.

NOT the same question, however similar the wording:
- neighbouring controls — an incident-response drill and a business-continuity drill; a DPA with
  a customer and a DPA with a sub-processor; encryption at rest and encryption in transit;
- the same control asked about a different scope — all systems against one system, employees
  against contractors, production against development;
- one asking whether something exists and the other asking for its frequency, owner, or evidence;
- questions that share a stem — "Do you have a documented policy for..." — and differ in what follows.

Questions may be in Arabic or English, and a pair may be one of each; judge what is being asked,
never the language it is asked in.

Set `same` to the numbers of the candidates that ask the same thing, or to nothing at all when none
of them do — which is the common answer, because these candidates were chosen for looking alike.
Set `because` to one short sentence about the closest call."""

SAME_QUESTION_USER = """NEW QUESTION
{question}

CANDIDATES WE HAVE ANSWERED BEFORE
{candidates}"""


REWRITE_SYSTEM = """You rewrite an answer that has already been written and checked.

You are not answering the question again. The facts are settled: they come from
the sources below, which are the ones the original answer was built from. Your
job is to say the same thing differently, following the instruction.

Rules, in order of importance:
1. Add no claim the sources do not support. If the instruction cannot be
   followed without inventing something, follow the sources and say less.
2. Drop no fact the original answer asserted, unless the instruction asks you to.
3. Keep the position. If the answer opens by saying yes, no, partly, or that the
   question does not apply, the rewrite opens by saying the same thing. A
   questionnaire's compliance dropdown is filled from that opening clause, so an
   answer that stops stating its position leaves the rating blank.
4. Write in {language_name}, whatever language the instruction is written in.
5. Write plain text, because it goes into a spreadsheet cell: no bold, italics or
   headings, whatever the instruction says. Where a list is wanted, put one item
   on each line starting with a hyphen."""

BRIEF_INSTRUCTION = """Condense this to the shortest form that still answers the question.

Open with the verdict -- yes, no, partly, not applicable -- when the answer has one, then one sentence saying what we do. Aim for the length of "Yes, offsite backups containing customer data are encrypted."

Keep: the position, and the single fact that most directly answers what was asked.
Drop: supporting detail, second and third examples, frequencies and thresholds the question did not ask for, and anything about what the documentation does or does not say.

Do not add a caveat that is not in the answer already, and do not soften a yes into a maybe. If the answer is already this short, return it unchanged."""
"""How a full answer becomes a brief one.

Fixed rather than free text, because "make it shorter" produces a different
length every time it is asked and the point of the brief form is that it is
predictable. Written as an instruction to `rewrite`, which keeps the facts and
the citations by construction -- see `src.rewrite`.
"""


REWRITE_USER = """QUESTION
{question}

THE ANSWER AS IT STANDS
{answer}

THE SOURCES IT WAS BUILT FROM
{sources_block}

HOW TO CHANGE IT
{instruction}

Rewrite the answer. Return only the rewritten answer."""
