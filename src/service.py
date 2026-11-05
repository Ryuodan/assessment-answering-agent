"""Application service — the one orchestration layer the API and CLI share.

Both front ends do the same three things (ingest a guideline, ingest a previous
assessment, answer a new one), so those flows live here and the front ends stay
thin: HTTP plumbing in `api.py`, argument parsing in `cli.py`, no logic in either.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from collections.abc import Callable
from pathlib import Path

from src.errors import NotADocument as NotADocument
from src import answer_memory, docx_preview, products, progress, uploads
from src.config import settings
from src.documents import SUPPORTED_SUFFIXES, load_text
from src.extraction import extract_qa_pairs, extract_questions
from src.graph import answer_one_question, assessment_graph, failed_answer
from src.scoped_knowledge import clear_knowledge as clear_knowledge, delete_source as delete_source
from src.scoped_knowledge import knowledge_stats as knowledge_stats, own_store
from src.models import AnsweredQuestion, AssessmentResult, IngestResult, Language, Question, SourceType
from src.schemas import ExtractedQAPair
from src.search import search_knowledge as search_knowledge
from src.uploads import extracted_text_cache_path as _extracted_text_cache_path

logger = logging.getLogger(__name__)

_DOCUMENT_LABELS = {"uploaded": "Uploaded document"}

docx_preview_html = docx_preview.preview_html
"""The Word preview, in `src/docx_preview.py` since plan 029; its callers still use this name."""


async def ingest(
    path: str | Path,
    source_type: SourceType,
    authority: str = "ours",
    team_id: str | None = None,
    product_id: str = "",
) -> IngestResult:
    """Index one uploaded file as either a guideline or a previously answered assessment.

    `authority` distinguishes a document this organisation wrote and is bound by
    from a law or framework it is subject to. It only means anything for a
    guideline: a previous answer is ours by definition.

    Failures are returned, not raised: a batch upload of ten policies should
    report which one was unreadable and index the other nine.
    """
    path = Path(path)
    store = own_store(team_id, product_id)  # the shared knowledge base, or a product's (plan 021)

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
    relabels Litware's answer column and finds none of its 183 answers, where the
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
    product_id: str = "",
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
            "product_id": product_id,
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
    product_id: str = "",
    on_answer: Callable[[AnsweredQuestion], None] | None = None,
) -> list[AnsweredQuestion]:
    """Answer a list of questions that did not come from a document.

    The same per-question graph the assessment flow fans out to, minus the
    extraction step. Used by the evaluation harness, which holds its questions
    as data, and by the interface whenever the question list was typed, edited
    after extraction, or added to after an earlier batch was answered.

    `run_id` registers the batch with `progress`, so a caller can watch it the
    same way it watches a document run. Without one the work still happens; it
    is simply not observable.

    `product_id` answers them for a product, from its knowledge base and the
    shared one (plan 023). It is passed on only when there is one. `on_answer`
    is handed each answer as it finishes, failed ones too, before it is counted.
    """
    semaphore = asyncio.Semaphore(settings.max_concurrent_questions)
    scope = {"product_id": product_id} if product_id else {}
    progress.start(run_id, stage="answering")
    progress.set_total(run_id, len(questions))

    async def run(question: Question) -> AnsweredQuestion:
        async with semaphore:
            try:
                try:
                    answered = await answer_one_question(
                        question, language or question.language, run_id=run_id or "", team_id=team_id, **scope
                    )
                except Exception as exc:  # noqa: BLE001 - contained per question, as in the fan-out
                    # The document flow already contains a per-question failure; this
                    # path did not, so a single transient upstream error — a model
                    # briefly withdrawn from the region, say — discarded a whole
                    # forty-two question run that had nearly finished.
                    logger.exception("Failed to answer question %s", question.id)
                    answered = failed_answer(question, exc)
                if on_answer is not None:
                    on_answer(answered)  # before it is counted: "12 done" finds 12 saved (plan 029)
                return answered
            finally:
                progress.advance(run_id)

    try:
        return list(await asyncio.gather(*(run(question) for question in questions)))
    finally:
        progress.finish(run_id)


def run_progress(run_id: str) -> dict | None:
    """How far an in-flight assessment run has got, or None if unknown."""
    return progress.snapshot(run_id)


def save_upload(
    filename: str,
    content: bytes,
    team_id: str | None = None,
    owner: str = "",
    product_id: str = "",
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

    A knowledge-base file is checked against every knowledge-base folder of the
    team, the shared one and each product's (plan 027): one name is one
    document, which is what answering merges evidence by.
    """
    settings.ensure_directories()
    name = Path(filename).name
    if owner:  # a questionnaire goes to the person who uploaded it
        return uploads.save(settings.user_upload_dir(team_id, owner), name, content)
    # A policy goes to whoever it answers for: the team, or one of its products.
    directory = settings.product_upload_dir(team_id, product_id) if product_id else settings.team_upload_dir(team_id)
    return uploads.save(directory, name, content, uploads.knowledge_folders(team_id))


def list_documents(team_id: str | None = None, owner: str = "") -> list[dict]:
    """What one person may open: their own questionnaires, and the team's documents.

    Everything in the team's folder used to be listed, which meant every
    questionnaire anybody had ever uploaded. Policies still are listed for
    everyone -- the knowledge base is the team's, an answer cites it, and the
    citation has to open. What is hidden is a questionnaire somebody else is
    working on. A product's files are its knowledge base, listed for everyone
    with the product they are for; a deleted product's are not listed at all.
    """
    settings.ensure_directories()
    paths = uploads.document_files(settings.user_upload_dir(team_id, owner)) if owner else []
    paths += [
        path
        for path in uploads.document_files(settings.team_upload_dir(team_id))
        if _may_read_shared(path.name, team_id, owner)
    ]
    documents = [_document_info(path) for path in paths]
    for product in products.list_products(team_id or settings.default_team):
        folder = settings.product_upload_dir(product.team_id, product.id)
        documents += [_document_info(path, product) for path in uploads.document_files(folder)]
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
    not readable by typing its name -- then each product's that still exists.
    """
    if not name or name != Path(name).name or Path(name).suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError("Invalid document name.")

    if origin != "uploaded" or category != "uploaded":
        raise ValueError("Invalid document location.")

    shared = settings.team_upload_dir(team_id)
    directories = [settings.user_upload_dir(team_id, owner)] if owner else []
    directories.append(shared)
    for product in products.list_products(team_id or settings.default_team):
        directories.append(settings.product_upload_dir(product.team_id, product.id))
    for directory in directories:
        base = directory.resolve()
        path = (base / name).resolve()
        if path.parent != base:
            raise ValueError("Invalid document path.")
        if not path.is_file():
            continue
        # Somebody else's questionnaire is absent rather than forbidden.
        if directory != shared or _may_read_shared(name, team_id, owner):
            return path
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


def _document_info(path: Path, product: products.Product | None = None) -> dict:
    title = path.stem.replace("_", " ").replace("-", " ").strip().title()
    return {
        "name": path.name,
        "title": title,
        "origin": "uploaded",
        "category": "uploaded",
        "label": _DOCUMENT_LABELS["uploaded"],
        "extension": path.suffix.lower().lstrip("."),
        "size_bytes": path.stat().st_size,
        # Whose knowledge base it is: a product's, or "" for the team's and a person's own.
        "product_id": product.id if product else "",
        "product_name": product.name if product else "",
    }
