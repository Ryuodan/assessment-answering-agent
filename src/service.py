"""Application service — the one orchestration layer the API and CLI share.

Both front ends do the same three things (ingest a guideline, ingest a previous
assessment, answer a new one), so those flows live here and the front ends stay
thin: HTTP plumbing in `api.py`, argument parsing in `cli.py`, no logic in either.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import re
import uuid
from pathlib import Path

from src.errors import NotADocument as NotADocument
from src import answer_memory, progress
from src.config import settings
from src.documents import SUPPORTED_SUFFIXES, load_text
from src.extraction import extract_qa_pairs, extract_questions
from src.graph import answer_one_question, assessment_graph, failed_answer
from src.knowledge import get_store
from src.lexical import reciprocal_rank_fusion
from src.models import (
    AnsweredQuestion,
    AssessmentResult,
    Evidence,
    ExtractedQAPair,
    IngestResult,
    Language,
    Question,
    SourceType,
)

logger = logging.getLogger(__name__)

_DOCUMENT_LABELS = {"uploaded": "Uploaded document"}

_ARABIC_TEXT = re.compile(r"[؀-ۿ]")


async def ingest(
    path: str | Path,
    source_type: SourceType,
    authority: str = "ours",
    team_id: str | None = None,
) -> IngestResult:
    """Index one uploaded file as either a guideline or a previously answered assessment.

    `authority` distinguishes a document this organisation wrote and is bound by
    from a law or framework it is subject to. It only means anything for a
    guideline: a previous answer is ours by definition.

    Failures are returned, not raised: a batch upload of ten policies should
    report which one was unreadable and index the other nine.
    """
    path = Path(path)
    store = get_store(team_id)

    try:
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        original = store.source_with_hash(content_hash, excluding=path.name)
        if original:
            logger.info("Skipping '%s': byte-identical to already-indexed '%s'", path.name, original)
            return IngestResult(
                source_name=path.name,
                source_type=source_type,
                chunks_indexed=0,
                duplicate_of=original,
            )

        if source_type is SourceType.GUIDELINE:
            text = await extracted_document_text(path)
            chunks = store.add_guideline(path.name, text, content_hash, authority=authority)
            return IngestResult(
                source_name=path.name,
                source_type=source_type,
                chunks_indexed=chunks,
                warning=_looks_like_a_questionnaire(text, path.name),
            )

        pairs = await answered_pairs(path)
        if not pairs:
            # Indexing nothing and reporting success reads as "done". A policy
            # filed here is simply absent from the knowledge base afterwards,
            # and nothing says so.
            logger.warning("No Q/A pairs in '%s'; it was probably not a completed assessment", path.name)
            return IngestResult(
                source_name=path.name,
                source_type=source_type,
                chunks_indexed=0,
                qa_pairs_found=0,
                error=(
                    f"No question/answer pairs were found in '{path.name}', so nothing was indexed. "
                    "Previous answers must be an assessment that has already been filled in. "
                    "If this is a policy or standard, upload it as a guideline instead."
                ),
            )

        chunks = store.add_prior_answers(path.name, pairs, content_hash)
        # Every pair is now an answer-memory entry with a row of its own, and
        # arrives unscanned: what it supersedes and what it contradicts is
        # settled by the sweep the caller runs next, not here, because that
        # sweep is model calls and an upload should not wait for them.
        answer_memory.adopt_file(path.name, pairs, team_id=team_id)
        return IngestResult(
            source_name=path.name,
            source_type=source_type,
            chunks_indexed=chunks,
            qa_pairs_found=len(pairs),
        )

    except Exception as exc:  # noqa: BLE001 - reported per file, not fatal to the batch
        logger.exception("Failed to ingest %s", path.name)
        return IngestResult(source_name=path.name, source_type=source_type, chunks_indexed=0, error=str(exc))


async def answered_pairs(path: str | Path, text: str | None = None) -> list[ExtractedQAPair]:
    """The questions a filled-in questionnaire answers, and what it answered.

    A spreadsheet or Word form is read by the same reader that opens a
    questionnaire for answering, and its answers are the ones that reader finds
    already in the file -- status and comment joined, the author's instruction
    column told apart from the answer. That is how the team's own 1,055 answers
    were harvested. The earlier path turned every file into text and asked a
    model to find the pairs, which was the only option for a PDF, could not take
    a spreadsheet at all, and is what almost every questionnaire arrives as.

    A PDF still goes that way, and so does a Word document the form reader
    cannot make sense of.

    The configured detection strategy reads it -- the one questionnaires are
    opened with, chosen and tested for that -- and the rules alone read it
    again, kept only if they find more answers. Opening a questionnaire to
    answer it and harvesting what somebody already wrote in it are different
    jobs: over the team's seventeen filled questionnaires the guarded reading
    relabels PSAT's answer column and finds none of its 183 answers, where the
    rules find all of them. Together the two find 1,087; either alone, at most
    1,055. Only the command line imports this way now; in the app an answer
    reaches the memory one at a time, written or approved by a person.
    """
    from src import forms
    from src.forms import reading

    path = Path(path)
    if path.suffix.lower() in forms.SUPPORTED:
        best: list[ExtractedQAPair] = []
        # The configured strategy first, so it is the reading kept on a tie.
        for strategy in dict.fromkeys((settings.detection_strategy, "rules")):
            try:
                read = await asyncio.to_thread(reading.read, path, strategy)
            except Exception:  # noqa: BLE001 - a form one reader cannot parse may suit the other
                logger.info("The %s reader could not read '%s'", strategy, path.name)
                continue
            pairs = [
                ExtractedQAPair(
                    question=question.text.strip(),
                    answer=question.existing_answer.strip(),
                    section=(question.section or "").strip(),
                )
                for question in read.form.questions
                if question.text.strip() and question.existing_answer.strip() and not question.skip
            ]
            if len(pairs) > len(best):
                best = pairs
        if best or path.suffix.lower() != ".docx":
            return best
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        return []
    return await extract_qa_pairs(text if text is not None else await extracted_document_text(path))


# A questionnaire is mostly questions; a policy states things. Measured across
# the eighty indexed policies and standards the highest density is 1.46 per
# thousand characters, and a filled-in assessment runs above 20 — so anything
# past this is a document of a kind that does not belong in the guidelines.
_QUESTION_DENSITY_LIMIT = 5.0


def _looks_like_a_questionnaire(text: str, name: str) -> str | None:
    """Warn when a guideline upload looks like an assessment form instead.

    The mistake is silent and one-directional. A policy filed as previous
    answers yields no Q/A pairs and indexes nothing, which is recoverable. An
    assessment filed as a guideline indexes perfectly well — and every answer
    in it then carries the authority of a policy, so "Yes, AES-256 is applied"
    is retrieved as though the organisation's standard said it.
    """
    if len(text) < 2000:
        return None
    density = 1000 * text.count("?") / len(text)
    if density <= _QUESTION_DENSITY_LIMIT:
        return None
    logger.warning("'%s' reads like a questionnaire (%.1f ?/1k chars) but was indexed as a guideline", name, density)
    return (
        f"'{name}' is mostly questions, so it may be an assessment form rather than a policy. "
        "It has been indexed as a guideline, which means its contents will be treated as "
        "authoritative. If it is a completed assessment, remove it: the team's answers "
        "belong in the answer memory, not among the policies."
    )


async def answer_assessment(
    path: str | Path,
    language: Language | None = None,
    run_id: str | None = None,
    team_id: str | None = None,
) -> AssessmentResult:
    """Answer every question in an assessment document.

    `language` forces the output language; leaving it None answers each question
    in whatever language it was asked.
    """
    path = Path(path)
    run_id = run_id or uuid.uuid4().hex[:12]
    progress.start(run_id, stage="extracting")

    text = await extracted_document_text(path)

    final_state = await assessment_graph().ainvoke(
        {
            "source_name": path.name,
            "document_text": text,
            "language": language,
            "run_id": run_id,
            "team_id": team_id or settings.default_team,
            "questions": [],
            "answers": [],
        },
        # Bounds how many questions hit Groq at once. Without it a 60-question
        # assessment fans out 60 ways and trips the rate limit.
        config={"max_concurrency": settings.max_concurrent_questions},
    )

    questions = final_state.get("questions", [])
    answers = final_state.get("answers", [])

    # The fan-out completes out of order; the filled assessment must read in
    # document order, so answers are re-sorted against the question list.
    position = {question.id: index for index, question in enumerate(questions)}
    answers.sort(key=lambda answered: position.get(answered.question.id, len(position)))

    progress.finish(run_id)
    return AssessmentResult(
        run_id=run_id,
        source_name=path.name,
        language=final_state.get("language") or final_state.get("document_language") or "en",
        questions_found=len(questions),
        answers=answers,
    )


async def extract_assessment_questions(path: str | Path) -> tuple[Language, list[Question]]:
    """Pull the questions out of a document without answering any of them.

    Extraction is fast and answering is minutes, so separating them lets a
    reviewer see what was found — and correct it — before paying for a run.
    Question extraction is the step most likely to need a human: a numbered
    list can lose an item to a page break, and a table row that is guidance
    rather than a question can look like one.
    """
    path = Path(path)
    text = await extracted_document_text(path)
    language, questions = await extract_questions(text)
    logger.info("Extracted %d question(s) from %s", len(questions), path.name)
    return language, questions


async def answer_questions(
    questions: list[Question],
    language: Language | None = None,
    run_id: str | None = None,
    team_id: str | None = None,
) -> list[AnsweredQuestion]:
    """Answer a list of questions that did not come from a document.

    The same per-question graph the assessment flow fans out to, minus the
    extraction step. Used by the evaluation harness, which holds its questions
    as data, and by the interface whenever the question list was typed, edited
    after extraction, or added to after an earlier batch was answered.

    `run_id` registers the batch with `progress`, so a caller can watch it the
    same way it watches a document run. Without one the work still happens; it
    is simply not observable.
    """
    semaphore = asyncio.Semaphore(settings.max_concurrent_questions)
    progress.start(run_id, stage="answering")
    progress.set_total(run_id, len(questions))

    async def run(question: Question) -> AnsweredQuestion:
        async with semaphore:
            try:
                return await answer_one_question(
                    question, language or question.language, run_id=run_id or "", team_id=team_id
                )
            except Exception as exc:  # noqa: BLE001 - contained per question, as in the fan-out
                # The document flow already contains a per-question failure; this
                # path did not, so a single transient upstream error — a model
                # briefly withdrawn from the region, say — discarded a whole
                # forty-two question run that had nearly finished.
                logger.exception("Failed to answer question %s", question.id)
                return failed_answer(question, exc)
            finally:
                progress.advance(run_id)

    try:
        return list(await asyncio.gather(*(run(question) for question in questions)))
    finally:
        progress.finish(run_id)


def run_progress(run_id: str) -> dict | None:
    """How far an in-flight assessment run has got, or None if unknown."""
    return progress.snapshot(run_id)


def knowledge_stats(team_id: str | None = None) -> dict:
    """Counts and indexed file names, for the UI's knowledge panel."""
    return get_store(team_id).stats()


# A person waiting at a search box will not wait a minute for a remote
# embedding host that is not answering. The literal search needs no network.
SEARCH_EMBED_TIMEOUT = 10.0


async def search_knowledge(
    query: str,
    *,
    mode: str = "hybrid",
    limit: int = 20,
    source_name: str = "",
    team_id: str | None = None,
) -> dict:
    """Search a team's indexed corpus directly, for a person rather than the drafter.

    Two ways of matching, because they fail in opposite ways and someone
    verifying a claim needs to choose. `semantic` finds material that means the
    same thing in either language; `keyword` matches the literal text, which is
    what you want when checking whether a policy really says "90 days", and
    understands `"quoted phrases"` and `-exclusions`. `hybrid` fuses both by
    reciprocal rank.

    Units are deliberately not expanded here. The answering path completes a
    split series so the drafter never mistakes a fragment for the whole list; a
    search result should be the chunk that actually matched.
    """
    query = (query or "").strip()
    if not query:
        return {"query": "", "mode": mode, "results": [], "documents": []}

    store = get_store(team_id)
    limit = max(1, min(limit, 50))
    # An empty collection still costs an embedding round trip to search, and
    # the prior-answers one is usually empty.
    counts = await asyncio.to_thread(store.counts_by_type)
    degraded: list[str] = []

    async def for_type(source_type: SourceType) -> list[Evidence]:
        if not counts.get(source_type.value):
            return []

        dense: list[Evidence] = []
        literal: list[Evidence] = []
        if mode in ("semantic", "hybrid"):
            try:
                dense = await asyncio.wait_for(
                    store.search(query, source_type, limit, expand=False), SEARCH_EMBED_TIMEOUT
                )
            except Exception as error:  # noqa: BLE001
                # The embedding service is remote and occasionally slow to
                # answer; a person at a search box should get the literal
                # matches rather than a spinner or a stack trace.
                degraded.append(str(error) or repr(error))
                logger.warning("Semantic search unavailable, falling back to text: %s", error)
        if mode in ("keyword", "hybrid"):
            literal = await asyncio.to_thread(store.text_search, query, source_type, limit)
        if not dense and degraded and mode == "semantic":
            # Nothing to show otherwise: answer the query the one way still working.
            literal = await asyncio.to_thread(store.text_search, query, source_type, limit)
        if mode != "hybrid":
            return dense or literal

        # Fused on rank, not score: a text-match count and a cosine are not
        # comparable numbers, and averaging them would silently favour
        # whichever happens to use the wider range.
        by_key: dict[tuple, Evidence] = {}
        for item in dense + literal:
            by_key.setdefault((item.source_name, item.chunk), item)
        rankings = [
            [(item.source_name, item.chunk) for item in dense],
            [(item.source_name, item.chunk) for item in literal],
        ]
        return [by_key[key] for key in reciprocal_rank_fusion(rankings) if key in by_key]

    # Both collections at once: they are independent queries and running them
    # in sequence doubled the wait for no reason.
    batches = await asyncio.gather(
        *(for_type(source_type) for source_type in (SourceType.GUIDELINE, SourceType.PRIOR_ANSWER))
    )
    found = [item for batch in batches for item in batch]

    if source_name:
        found = [item for item in found if item.source_name == source_name]

    return {
        "query": query,
        "mode": mode,
        "results": [item.model_dump() for item in found[:limit]],
        "documents": await asyncio.to_thread(store.documents_indexed),
        # Set when meaning-based search could not run, so the interface can say
        # so rather than implying the corpus holds nothing.
        "degraded": bool(degraded),
    }


def delete_source(source_name: str, team_id: str | None = None) -> None:
    """Remove one previously uploaded policy document from the knowledge base.

    Only documents. Previous answers are indexed too, but they belong to the
    answer memory, where each has a row -- who approved it, what it replaced --
    that a delete by source name would orphan by the hundred.
    """
    kind = get_store(team_id).source_type_of(source_name)
    if kind == SourceType.PRIOR_ANSWER.value:
        raise NotADocument("Previous answers are part of the answer memory. Manage them on the Answer memory page.")
    if not kind:
        # Said, rather than reported as deleted: a name that was never indexed,
        # or already removed by somebody else, is not something this removed.
        raise KeyError(source_name)
    get_store(team_id).delete_source(source_name)


def clear_knowledge(team_id: str | None = None) -> None:
    """Remove every policy document, and leave the answer memory standing.

    It used to drop the whole collection, which took the memory's 698 vectors
    with it and left their rows on the memory page -- listed, and never
    retrieved again. Clearing the corpus and forgetting what the team has said
    are different decisions, made in different places.
    """
    get_store(team_id).delete_type(SourceType.GUIDELINE)


def save_upload(
    filename: str,
    content: bytes,
    team_id: str | None = None,
    owner: str = "",
) -> Path:
    """Persist an uploaded file under the configured upload directory.

    Only the basename is used, so a crafted filename such as `../../.env` cannot
    escape the upload directory.

    A name already taken by *different* content gets a numbered sibling rather
    than overwriting it. Two people on one team send each other questionnaires
    called `Vendor Security Questionnaire.xlsx`, and the second upload used to
    replace the first on disk -- silently repointing a batch that had already
    been read, column by column, at somebody else's spreadsheet. Identical
    content keeps the one name: re-uploading the same file is how a person
    reopens their own work, and a folder of `(2)`, `(3)`, `(4)` copies of one
    document helps nobody.
    """
    settings.ensure_directories()
    # A questionnaire goes to the person who uploaded it; a policy for the
    # knowledge base goes to the team, because that is who it answers for.
    directory = settings.user_upload_dir(team_id, owner) if owner else settings.team_upload_dir(team_id)
    directory.mkdir(parents=True, exist_ok=True)
    name = Path(filename).name
    destination = directory / name
    stem, suffix = destination.stem, destination.suffix
    attempt = 1
    while destination.exists() and destination.read_bytes() != content:
        attempt += 1
        destination = directory / f"{stem} ({attempt}){suffix}"
    destination.write_bytes(content)
    return destination


def list_documents(team_id: str | None = None, owner: str = "") -> list[dict]:
    """What one person may open: their own questionnaires, and the team's documents.

    Everything in the team's folder used to be listed, which meant every
    questionnaire anybody had ever uploaded. Policies still are listed for
    everyone -- the knowledge base is the team's, an answer cites it, and the
    citation has to open. What is hidden is a questionnaire somebody else is
    working on.
    """
    settings.ensure_directories()
    paths = _document_files(settings.user_upload_dir(team_id, owner)) if owner else []
    paths += [
        path
        for path in _document_files(settings.team_upload_dir(team_id))
        if _may_read_shared(path.name, team_id, owner)
    ]
    documents = [_document_info(path, origin="uploaded", category="uploaded") for path in paths]
    return sorted(documents, key=lambda document: document["name"])


def _may_read_shared(name: str, team_id: str | None, owner: str) -> bool:
    """Whether this person may open a file in the team's own folder.

    Questionnaires are kept per person now, so what is left here is the team's:
    the policies the knowledge base was built from, and -- from before the
    split -- questionnaires that were uploaded into it. One of those belongs to
    whoever opened it, and is hidden from everybody else; anything nobody has
    opened is the team's, like the policies beside it.
    """
    if not owner:
        return True  # nobody is asking: the CLI, a script, the tests
    from src import batches
    from src.knowledge import get_store

    claimed = batches.claimed_sources(team_id or settings.default_team).get(name)
    if claimed is None or claimed == owner:
        return True
    return name in set(get_store(team_id).documents_indexed())


def resolve_document(
    origin: str,
    category: str,
    name: str,
    team_id: str | None = None,
    owner: str = "",
) -> Path:
    """Resolve a catalog document without allowing traversal outside its directory.

    Their own folder first, then the team's -- and there only the names
    `list_documents` would have shown them, so a colleague's questionnaire is
    not readable by typing its name.
    """
    if not name or name != Path(name).name or Path(name).suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError("Invalid document name.")

    if origin != "uploaded" or category != "uploaded":
        raise ValueError("Invalid document location.")

    directories = [settings.user_upload_dir(team_id, owner)] if owner else []
    directories.append(settings.team_upload_dir(team_id))
    for index, directory in enumerate(directories):
        base = directory.resolve()
        path = (base / name).resolve()
        if path.parent != base:
            raise ValueError("Invalid document path.")
        if not path.is_file():
            continue
        their_own = index < len(directories) - 1 or not owner
        if their_own or _may_read_shared(name, team_id, owner):
            return path
        break  # somebody else's: absent rather than forbidden
    raise FileNotFoundError(name)


async def extracted_document_text(path: str | Path) -> str:
    """Return extracted text, caching it until the source or converter settings change."""
    path = Path(path)
    settings.ensure_directories()
    cache_path = _extracted_text_cache_path(path)

    if cache_path.is_file() and cache_path.stat().st_mtime_ns >= path.stat().st_mtime_ns:
        return cache_path.read_text(encoding="utf-8")

    text = await load_text(path)
    cache_path.write_text(text, encoding="utf-8")
    return text


def docx_preview_html(path: str | Path) -> str:
    """Render a safe, self-contained HTML preview of a Word document."""
    from docx import Document as WordDocument
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    path = Path(path)
    if path.suffix.lower() != ".docx":
        raise ValueError("HTML preview is only available for DOCX files.")

    document = WordDocument(str(path))
    blocks: list[str] = []
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            blocks.append(_preview_paragraph(Paragraph(child, document)))
        elif tag == "tbl":
            blocks.append(_preview_table(Table(child, document)))

    title = html.escape(path.stem.replace("_", " ").replace("-", " ").title())
    content = "\n".join(blocks)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 28px; background: #e8eaee; color: #1b1d21;
          font: 15px/1.55 Arial, "Noto Sans Arabic", sans-serif; }}
  .page {{ width: min(850px, 100%); min-height: 1050px; margin: 0 auto; padding: 58px 64px;
           counter-reset: preview-list;
           background: white; box-shadow: 0 2px 16px rgba(0,0,0,.14); }}
  h1, h2, h3, h4, h5, h6 {{ line-height: 1.25; margin: 1.2em 0 .45em; }}
  h1:first-child, h2:first-child {{ margin-top: 0; }}
  p {{ margin: .55em 0; white-space: normal; }}
  .spacer {{ height: .75em; }}
  .list-bullet {{ padding-inline-start: 1.4em; }}
  .list-bullet::before {{ content: "•"; display: inline-block; width: 1.2em; margin-inline-start: -1.2em; }}
  .list-number {{ padding-inline-start: 1.4em; }}
  .list-number {{ counter-increment: preview-list; }}
  .list-number::before {{ content: counter(preview-list) "."; display: inline-block; width: 1.4em;
                          margin-inline-start: -1.4em; }}
  .align-center {{ text-align: center; }}
  .align-right {{ text-align: right; }}
  .align-justify {{ text-align: justify; }}
  table {{ width: 100%; border-collapse: collapse; margin: 1em 0; font-size: 13px; }}
  th, td {{ border: 1px solid #aeb4bd; padding: 7px 9px; vertical-align: top; text-align: start; }}
  th {{ background: #edf1f6; font-weight: 700; }}
  [dir="rtl"] {{ text-align: right; }}
  @media (max-width: 700px) {{ body {{ padding: 0; }} .page {{ padding: 28px 22px; min-height: 100vh; }} }}
</style>
</head>
<body><main class="page">{content}</main></body>
</html>"""


def _preview_paragraph(paragraph) -> str:
    text = paragraph.text
    if not text.strip():
        return '<div class="spacer"></div>'

    style_name = paragraph.style.name if paragraph.style is not None else ""
    heading_match = re.fullmatch(r"Heading\s+([1-6])", style_name, flags=re.IGNORECASE)
    tag = f"h{heading_match.group(1)}" if heading_match else "p"

    classes = []
    lowered_style = style_name.lower()
    if "list bullet" in lowered_style:
        classes.append("list-bullet")
    elif "list number" in lowered_style:
        classes.append("list-number")

    alignment_class = {1: "align-center", 2: "align-right", 3: "align-justify"}.get(paragraph.alignment)
    if alignment_class:
        classes.append(alignment_class)

    attributes = []
    if classes:
        attributes.append(f'class="{" ".join(classes)}"')
    if _ARABIC_TEXT.search(text):
        attributes.append('dir="rtl"')

    rendered_runs = "".join(_preview_run(run) for run in paragraph.runs)
    if not rendered_runs:
        rendered_runs = html.escape(text)
    attrs = f" {' '.join(attributes)}" if attributes else ""
    return f"<{tag}{attrs}>{rendered_runs}</{tag}>"


def _preview_run(run) -> str:
    rendered = html.escape(run.text).replace("\t", "&emsp;").replace("\n", "<br>")
    if not rendered:
        return ""
    if run.bold:
        rendered = f"<strong>{rendered}</strong>"
    if run.italic:
        rendered = f"<em>{rendered}</em>"
    if run.underline:
        rendered = f"<u>{rendered}</u>"
    return rendered


def _preview_table(table) -> str:
    rows = []
    for row_index, row in enumerate(table.rows):
        cells = []
        seen_cells = set()
        for cell in row.cells:
            cell_id = id(cell._tc)
            if cell_id in seen_cells:
                continue
            seen_cells.add(cell_id)

            cell_tag = "th" if row_index == 0 else "td"
            text = cell.text
            direction = ' dir="rtl"' if _ARABIC_TEXT.search(text) else ""
            paragraphs = "<br>".join(
                "".join(_preview_run(run) for run in paragraph.runs) or html.escape(paragraph.text)
                for paragraph in cell.paragraphs
                if paragraph.text.strip()
            )
            cells.append(f"<{cell_tag}{direction}>{paragraphs}</{cell_tag}>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return f"<table>{''.join(rows)}</table>"


def _document_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES)


def _document_info(path: Path, *, origin: str, category: str) -> dict:
    title = path.stem.replace("_", " ").replace("-", " ").strip().title()
    return {
        "name": path.name,
        "title": title,
        "origin": origin,
        "category": category,
        "label": _DOCUMENT_LABELS[category],
        "extension": path.suffix.lower().lstrip("."),
        "size_bytes": path.stat().st_size,
    }


# Bumped whenever the extraction code changes in a way that alters its output,
# so cached text from an older, worse extractor is not silently reused.
_EXTRACTION_VERSION = "7"


def _extracted_text_cache_path(path: Path) -> Path:
    cache_input = "\0".join(
        (
            _EXTRACTION_VERSION,
            str(path.resolve()),
            settings.docling_base_url,
            str(settings.docling_do_ocr),
            str(settings.docling_ocr_auto),
            settings.docling_image_export_mode,
            str(settings.docling_heading_hierarchy),
            # Part of the key, not just the version: a text extracted without
            # page markers and one extracted with them are different documents
            # as far as chunk metadata is concerned.
            settings.docling_page_break_placeholder,
        )
    )
    cache_key = hashlib.sha256(cache_input.encode("utf-8")).hexdigest()[:24]
    return settings.extracted_text_dir / f"{cache_key}.txt"
