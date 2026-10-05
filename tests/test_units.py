"""Unit tests for the parts that do not need a network.

The LLM and embedding calls are covered by `test_live.py`, which is opt-in.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src import documents
from src.config import Settings, settings
from src.docling_client import DoclingError, _markdown
from src.documents import UnsupportedDocumentError, load_text, load_text_local, windows
from src.extraction import _deduplicate_ids, detect_language
from src.models import Evidence, Question, QuestionType, SourceType
from src.prompts import format_question_block, format_sources_block

FIXTURES = Path(__file__).parent / "fixtures"


def test_default_groq_chat_model(monkeypatch):
    """A deployment with no `.env` must run the model the numbers describe.

    This asserted minimax-m2.7 long after the project had measured and moved
    to gpt-oss-120b — harmless while a real `.env` outranks the default, and
    exactly the drift `test_the_example_env_agrees_with_the_code_defaults`
    now guards against.
    """
    monkeypatch.delenv("GROQ_CHAT_MODEL", raising=False)
    assert Settings(_env_file=None).groq_chat_model == "openai/gpt-oss-120b"


# --- progress: what is happening now ---------------------------------------


def test_a_note_replaces_the_count_it_follows():
    """A turn is a sequence of operations and only one of them has a
    denominator. Leaving the last one's count in place would draw a full bar
    beside a label about something that has not started."""
    from src import progress

    progress.start("watch-me", stage="Thinking…")
    progress.set_total("watch-me", 4)
    progress.advance("watch-me")
    assert progress.snapshot("watch-me")["percent"] == 25

    progress.note("watch-me", "Searching the policies…")
    state = progress.snapshot("watch-me")
    assert state["stage"] == "Searching the policies…"
    assert state["total"] == 0 and state["completed"] == 0 and state["percent"] == 0


def test_a_note_for_a_run_nobody_started_is_harmless():
    from src import progress

    progress.note("", "Thinking…")
    progress.note(None, "Thinking…")


# --- an answer that arrived in two cells -----------------------------------
#
# A questionnaire with a status column and a comment column is answered in the
# pair, and `existing_answer` used to return whichever of the two it reached
# first. Measured over seventeen real questionnaires, 208 of 982 answers were
# losing either their verdict or their explanation that way.


def _question(status=None, prose=None):
    from src.forms.model import FormQuestion, Role, Target

    targets = {}
    if status is not None:
        targets[Role.STATUS] = Target(id="s", role=Role.STATUS, existing=status)
    if prose is not None:
        targets[Role.ANSWER] = Target(id="a", role=Role.ANSWER, existing=prose)
    return FormQuestion(id="q", text="Does it?", targets=targets)


def test_a_verdict_and_a_comment_are_read_as_one_answer():
    assert _question("Yes", "we enforce MFA on all privileged accounts").existing_answer == (
        "Yes, we enforce MFA on all privileged accounts"
    )


def test_a_comment_that_is_its_own_sentence_is_not_comma_spliced():
    """Lower case continues the verdict; upper case starts a sentence. Nothing
    is re-cased, because "T2 has documented policies" must not become "t2"."""
    assert _question("Compliant", "T2 has documented policies.").existing_answer == (
        "Compliant. T2 has documented policies."
    )


def test_a_comment_that_already_carries_the_verdict_is_the_whole_answer():
    """Some teams ignore the status column and write everything in the comment.
    Joining there produces "Fully Compliant, Yes we encrypt", which is nobody's
    answer."""
    question = _question("Fully Compliant", "Yes. The HR process was approved in March.")
    assert question.existing_answer == "Yes. The HR process was approved in March."


def test_either_cell_alone_is_still_an_answer():
    assert _question("Implemented", None).existing_answer == "Implemented"
    assert _question(None, "We have no DPO.").existing_answer == "We have no DPO."
    assert _question(None, None).existing_answer == ""


def test_a_repeated_verdict_is_not_doubled():
    assert _question("Yes", "Yes, offsite backups are encrypted").existing_answer == (
        "Yes, offsite backups are encrypted"
    )


# --- language detection ----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Do you hold a security certification?", "en"),
        ("ما هي مدة الاحتفاظ ببيانات العملاء؟", "ar"),
        # Mixed: mostly Arabic with an embedded Latin acronym is still Arabic.
        ("يتم التشفير باستخدام AES-256 أثناء التخزين", "ar"),
        # Mostly English with one Arabic word is still English.
        ("The policy is called سياسة and applies globally to every system", "en"),
        ("", "en"),
    ],
)
def test_detect_language(text, expected):
    assert detect_language(text) == expected


# --- local document loading (Docling fallback) -----------------------------


def test_load_docx_keeps_table_rows_together():
    """A question and its answer must survive in the same line, or Q/A extraction fails."""
    text = load_text_local(FIXTURES / "prior_assessment_2024.docx")
    assert "[table]" in text
    assert "Do you hold a recognised information security certification? | Yes." in text


def test_load_docx_preserves_arabic():
    text = load_text_local(FIXTURES / "prior_assessment_2024.docx")
    assert "ما هي مدة الاحتفاظ ببيانات العملاء؟" in text


def test_load_pdf_reassembles_rows_wrapped_across_lines():
    """`extract_text` wraps a long question over two lines; the table pass must rejoin it."""
    text = load_text_local(FIXTURES / "new_assessment_2026.pdf")
    assert "[table]" in text
    assert "Is your organisation certified against a recognised information security standard? (Yes/No) |" in text


async def test_load_rejects_unsupported_suffix(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello")
    with pytest.raises(UnsupportedDocumentError, match="Supported types"):
        await load_text(path)


async def test_load_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        await load_text(tmp_path / "nope.docx")


# --- Docling conversion ----------------------------------------------------


@pytest.fixture
def docling(monkeypatch):
    """Point the loader at a stub Docling and return the recorded call log."""
    monkeypatch.setattr(settings, "docling_base_url", "http://docling.test")
    calls: list[Path] = []

    def stub(result):
        async def convert_file(path, *, do_ocr=None):
            calls.append(path)
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(documents.docling_client, "convert_file", convert_file)
        return calls

    return stub


async def test_load_prefers_docling_markdown(docling):
    calls = docling("| Question | Answer |\n| --- | --- |\n| Do you encrypt data? | Yes, AES-256. |")

    text = await load_text(FIXTURES / "prior_assessment_2024.docx")

    assert "Do you encrypt data? | Yes, AES-256." in text
    assert "[table]" not in text  # the local loader was never reached
    assert [path.name for path in calls] == ["prior_assessment_2024.docx"]


async def test_load_falls_back_locally_when_docling_fails(docling, monkeypatch):
    docling(DoclingError("connection refused"))
    # Pinned rather than inherited: a deployment's .env may switch the fallback
    # off, and this test is about the behaviour when it is on.
    monkeypatch.setattr(settings, "docling_fallback_local", True)

    text = await load_text(FIXTURES / "prior_assessment_2024.docx")

    assert "[table]" in text
    assert "Do you hold a recognised information security certification? | Yes." in text


async def test_load_surfaces_docling_failure_when_fallback_is_off(docling, monkeypatch):
    docling(DoclingError("connection refused"))
    monkeypatch.setattr(settings, "docling_fallback_local", False)

    with pytest.raises(UnsupportedDocumentError, match="connection refused"):
        await load_text(FIXTURES / "prior_assessment_2024.docx")


async def test_load_falls_back_when_docling_returns_blank(docling):
    """An empty conversion is a failure, not an empty document."""
    docling("   \n  ")

    assert "[table]" in await load_text(FIXTURES / "prior_assessment_2024.docx")


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "failure", "document": {"md_content": ""}, "errors": ["boom"]},
        {"status": "success", "document": {"md_content": None}},
        {"status": "success"},
        {},
    ],
)
def test_markdown_rejects_unusable_responses(payload):
    with pytest.raises(DoclingError):
        _markdown(payload, "a.pdf")


def test_markdown_accepts_partial_success():
    payload = {"status": "partial_success", "document": {"md_content": "# Title"}, "errors": ["page 3"]}
    assert _markdown(payload, "a.pdf") == "# Title"


# --- windowing -------------------------------------------------------------


def test_windows_returns_single_chunk_when_short():
    assert windows("a\nb\nc", size=1000) == ["a\nb\nc"]


def test_windows_splits_on_line_boundaries_with_overlap():
    text = "\n".join(f"line {i} padded out a little" for i in range(60))
    chunks = windows(text, size=300, overlap=100)

    assert len(chunks) > 1
    # No line may be cut in half, or a table row would lose its answer column.
    for chunk in chunks:
        for line in chunk.split("\n"):
            assert line in text
    # Consecutive windows must overlap, so a question at a boundary is seen whole.
    assert chunks[0].split("\n")[-1] in chunks[1]


# --- id de-duplication -----------------------------------------------------


def test_duplicate_question_ids_are_made_unique():
    """Documents reuse '1' across sections; ids must stay unique for ordering."""
    questions = [Question(id="1", text="a"), Question(id="1", text="b"), Question(id="2", text="c")]
    result = _deduplicate_ids(questions)
    assert [q.id for q in result] == ["1", "1-2", "2"]


# --- prompt blocks ---------------------------------------------------------


def test_question_block_includes_options_for_choice_questions():
    block = format_question_block(
        "Pick one", section="Access", question_type=QuestionType.SINGLE_CHOICE.value, options=["Yes", "No"]
    )
    assert "Section: Access" in block
    assert "Yes | No" in block


def test_sources_block_is_numbered_and_labelled():
    block = format_sources_block(
        [
            Evidence(source_type=SourceType.PRIOR_ANSWER, source_name="a.docx", snippet="past answer"),
            Evidence(source_type=SourceType.GUIDELINE, source_name="b.docx", snippet="policy text"),
        ]
    )
    assert "[1] PREVIOUS ANSWER — a.docx" in block
    assert "[2] OUR POLICY — b.docx" in block, (
        "a guideline is labelled by whose it is: our policy says what we do, "
        "and a regulation says what we are required to do"
    )
    assert "past answer" in block and "policy text" in block


def test_sources_block_says_so_when_empty():
    assert "no relevant sources" in format_sources_block([])


# --- automatic OCR ---------------------------------------------------------


def test_born_digital_pdf_does_not_trigger_ocr():
    """OCR on a text-layer PDF only adds whatever text sits inside the logos."""
    assert documents._looks_scanned(FIXTURES / "new_assessment_2026.pdf") is False


def test_docx_never_triggers_ocr():
    assert documents._looks_scanned(FIXTURES / "prior_assessment_2024.docx") is False


def test_ocr_detection_survives_an_unreadable_file(tmp_path):
    """A detection failure must not fail the upload; it just declines to force OCR."""
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not really a pdf")
    assert documents._looks_scanned(broken) is False


async def test_ocr_is_requested_per_file(docling, monkeypatch):
    """The Docling call carries the per-file decision, not the global default."""
    requested: list = []

    async def convert_file(path, *, do_ocr=None):
        requested.append(do_ocr)
        return "# Converted"

    monkeypatch.setattr(documents.docling_client, "convert_file", convert_file)
    monkeypatch.setattr(settings, "docling_do_ocr", False)
    monkeypatch.setattr(settings, "docling_ocr_auto", True)
    monkeypatch.setattr(documents, "_looks_scanned", lambda path: True)

    await load_text(FIXTURES / "new_assessment_2026.pdf")

    assert requested == [True]


async def test_forcing_ocr_overrides_detection(docling, monkeypatch):
    requested: list = []

    async def convert_file(path, *, do_ocr=None):
        requested.append(do_ocr)
        return "# Converted"

    monkeypatch.setattr(documents.docling_client, "convert_file", convert_file)
    monkeypatch.setattr(settings, "docling_do_ocr", True)
    monkeypatch.setattr(documents, "_looks_scanned", lambda path: False)

    await load_text(FIXTURES / "new_assessment_2026.pdf")

    assert requested == [True]


# --- displaced RTL list markers --------------------------------------------


def test_a_marker_stranded_at_the_end_of_an_arabic_line_is_moved_back():
    """Docling and the bidi path both emit "…؟ وما .25" for "25. …؟ وما"."""
    text = "ما هي المدة الزمنية المحددة لإعادة بيانات العميل؟ وما .25"
    assert documents.repair_rtl_numbering(text).startswith("25. ما هي")


def test_a_value_at_the_end_of_an_arabic_sentence_is_left_alone():
    """ "خلال 72 ساعة" must not become "72. خلال ساعة"."""
    text = "يجب الإبلاغ عن الحادثة خلال 72"
    assert documents.repair_rtl_numbering(text) == text


def test_english_lines_are_untouched():
    text = "Remediate critical vulnerabilities within 30"
    assert documents.repair_rtl_numbering(text) == text


def test_every_marker_in_a_document_is_repaired():
    text = "\n".join(
        [
            "ما هي المدة الزمنية المحددة؟ .25",
            "Some English question 26.",
            "هل يشترط استضافة البيانات داخل المملكة؟ .26",
        ]
    )
    repaired = documents.repair_rtl_numbering(text).splitlines()
    assert repaired[0].startswith("25. ")
    assert repaired[1] == "Some English question 26."
    assert repaired[2].startswith("26. ")


def test_repair_preserves_line_count_and_content():
    text = "أ\nب .3\nج"
    repaired = documents.repair_rtl_numbering(text)
    assert len(repaired.splitlines()) == 3
    assert "ب" in repaired and "3" in repaired


# --- run progress ----------------------------------------------------------


def test_progress_reports_what_is_left():
    from src import progress

    progress.start("run-a")
    assert progress.snapshot("run-a")["stage"] == "extracting"

    progress.set_total("run-a", 4)
    progress.advance("run-a")
    progress.advance("run-a")

    state = progress.snapshot("run-a")
    assert (state["total"], state["completed"], state["remaining"], state["percent"]) == (4, 2, 2, 50)
    assert state["stage"] == "answering"

    progress.finish("run-a")
    assert progress.snapshot("run-a")["stage"] == "done"
    assert progress.snapshot("run-a")["remaining"] == 0


def test_progress_for_an_unknown_run_is_none():
    from src import progress

    assert progress.snapshot("never-started") is None


def test_progress_calls_without_a_run_id_are_ignored():
    """The batch entry point has no run id; it must not raise."""
    from src import progress

    progress.start(None)
    progress.set_total(None, 5)
    progress.advance(None)
    progress.finish(None)


def test_progress_counts_a_failed_question():
    """A run that loses a question must still reach the end of its bar."""
    from src import progress

    progress.start("run-b")
    progress.set_total("run-b", 2)
    progress.advance("run-b")  # succeeded
    progress.advance("run-b")  # failed, still counted

    assert progress.snapshot("run-b")["remaining"] == 0


def test_progress_entries_are_capped():
    from src import progress

    for index in range(progress._MAX_RUNS + 20):
        progress.start(f"bulk-{index}")

    assert len(progress._RUNS) <= progress._MAX_RUNS


# --- configuration paths ---------------------------------------------------


def test_relative_storage_paths_anchor_to_the_project_not_the_cwd():
    """Launching from the wrong directory silently produced an empty corpus.

    `.env` naturally holds `CHROMA_DIR=./chroma_db`. Started from the repository
    root instead of the application directory, the API created a fresh empty
    database there and reported nothing indexed — no error, just a knowledge
    base that had lost eighty documents.
    """
    from src.config import PROJECT_ROOT

    settings_from_relative = Settings(
        _env_file=None,
        chroma_dir="./chroma_db",
        upload_dir="data/uploads",
        extracted_text_dir="data/extracted",
    )

    assert settings_from_relative.chroma_dir == (PROJECT_ROOT / "chroma_db").resolve()
    assert settings_from_relative.upload_dir == (PROJECT_ROOT / "data" / "uploads").resolve()
    assert settings_from_relative.extracted_text_dir == (PROJECT_ROOT / "data" / "extracted").resolve()


def test_an_absolute_storage_path_is_respected(tmp_path):
    """A deployment pointing at a mounted volume must keep that path."""
    configured = Settings(_env_file=None, chroma_dir=str(tmp_path / "vol" / "chroma"))
    assert configured.chroma_dir == tmp_path / "vol" / "chroma"
