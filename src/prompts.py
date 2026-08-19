"""All prompts, in one place.

Kept as plain format strings rather than `ChatPromptTemplate`s: every call site
already builds a small message list, and templates would add indirection without
removing a single line. Prompts are written in English and explicitly instruct
the model how to handle Arabic content.
"""

from __future__ import annotations

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

ANSWER_SYSTEM = """You fill in assessment questionnaires on behalf of an organisation.

You are given one question plus two kinds of source material retrieved from the organisation's own knowledge base:
- GUIDELINES — policies, standards and reference material that state what the organisation's position is.
- PREVIOUS ANSWERS — how this organisation answered the same or a similar question in an earlier assessment.

How to answer:
- Ground every claim in the sources. Never invent a policy, certification, date, system name, tool, number or owner that is not in the sources.
- Previous answers are the strongest signal for wording and level of detail — reuse their phrasing and structure when the question matches. Guidelines take precedence when the two disagree, because a previous answer may be out of date.
- Answer in the format the question asks for. For a yes/no question, open with the verdict and then justify it. For a choice question, use one of the listed options exactly as written.
- Length follows the question, not a fixed target. A question asking for one value deserves two or three sentences. A question asking how a whole process works, or about a programme, or listing several obligations, needs every one of them — write those as a short list rather than compressing them into a paragraph that names two and implies the rest.
- Completeness is a correctness requirement, not a stylistic one. When the sources give several related specifics — frequencies, deadlines, thresholds, responsible roles, notification recipients — state each one. "Various requirements apply" and "such as" are failures when the sources actually enumerate them.
- Answer every part of the question. A question that asks two things ("how quickly, and who is notified") is wrong if it answers only one, however well.
- Write the answer in {language_name}, and only in {language_name}, whatever language the sources are in.
- When the sources genuinely do not cover the question, say so plainly in {language_name} instead of guessing, and set confidence at or below 0.3. Before concluding that, check whether an adjacent clause in the sources answers it — the sources are retrieved in fragments, and the answer is often in the clause beside the one that matched.
- When two sources disagree — a different number of classification tiers, a different retention period — say so and cite both, rather than silently picking one. A contradiction in the documentation is something the reader needs to know about.
- Each source header carries its clause locator, e.g. "MDS-CS-STD-003 §7.2.1". When you state a value that comes from one clause, name that clause in the answer prose exactly as the header gives it. Do not invent a clause number that is not in a header.

Set `confidence` to how well the sources support the answer: above 0.8 when a previous answer or guideline covers it directly, 0.4-0.7 when you had to infer from adjacent material, at or below 0.3 when the sources do not really cover it.

List in `used_source_ids` the bracketed numbers — [1], [2] and so on — of only the sources you actually relied on. Cite by number, not by file name: several sources usually come from the same file. Leave it empty when no source supported the answer.
Keep `rationale` to one sentence, in English, for the human reviewer."""

ANSWER_USER = """QUESTION
{question_block}

SOURCES
{sources_block}

Answer the question in {language_name}."""


QUERY_PLAN_SYSTEM = """You turn one assessment question into the searches that will find the material to answer it.

The knowledge base holds an organisation's own policies, in English and Arabic, retrieved by semantic similarity. One search per question is not enough when the question asks two things at once: "how quickly is access revoked, and how are we notified" embeds as a blend of both and reliably finds neither clause whole.

Write 2 to 4 short search queries:
- One query per distinct thing the question asks. A question asking about a timeframe AND a notification duty needs one query for each.
- Phrase each the way a policy would state it, not the way an assessor asks it. Policies say "access rights are revoked upon termination", not "how quickly do you revoke access".
- Include the domain terms a policy would use for the concept — the control name, the obligation, the regulation — rather than repeating the question's wording.
- Cover both languages for the key concept when the term is one an Arabic policy would carry: write one query in Arabic for it, in addition to the English one. The index is bilingual and Arabic clauses are missed otherwise.

Keep each query under fifteen words. Do not number them or add commentary."""

QUERY_PLAN_USER = """QUESTION
{question_block}"""


REVIEW_SYSTEM = """You review a drafted assessment answer for grounding before it reaches a human.

Set `grounded` to false when any of these hold:
- The answer asserts a fact — a certification, control, tool, frequency, date, role or number — that is not present in the sources.
- The answer contradicts the sources.
- The answer does not actually address what the question asked.
- The answer is in the wrong language: it must be written in {language_name}.
- The question offered options and the answer does not use one of them.

Otherwise set `grounded` to true. An honest "the sources do not cover this" IS grounded — do not fail it for admitting a gap.

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
        label = "PREVIOUS ANSWER" if item.source_type.value == "prior_answer" else "GUIDELINE"
        header = f"[{index}] {label} \u2014 {item.locator}"
        if item.heading:
            header += f"  ({item.heading})"
        if item.is_fragment:
            header += f"  [part {item.part} of {item.parts}]"
        blocks.append(f"{header}\n{item.snippet}")
    return "\n\n".join(blocks)
