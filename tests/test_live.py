"""Opt-in tests that call the real Groq and BGE-M3 endpoints.

    pytest -m live_ai

Excluded from a default run because they cost tokens and need `GROQ_API_KEY`.
They are the only place the prompts themselves are exercised.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src import service
from src.config import settings
from src.documents import load_text
from src.extraction import extract_qa_pairs, extract_questions
from src.knowledge import get_store
from src.models import SourceType

pytestmark = [
    pytest.mark.live_ai,
    pytest.mark.skipif(not settings.groq_api_key, reason="GROQ_API_KEY is not set"),
]

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def isolated_knowledge_base(tmp_path_factory):
    """Point the store at a throwaway Chroma directory for the whole module.

    These tests call `reset()`, and `get_store()` is a process-wide singleton
    over whatever `settings.chroma_dir` says. Without this fixture, running
    `pytest -m live_ai` on a machine with a populated knowledge base deletes
    it — the indexed corpus is hours of work and there is no undo.
    """
    directory = tmp_path_factory.mktemp("chroma_live")
    original = (settings.chroma_dir, settings.collection_name)
    settings.chroma_dir = directory
    settings.collection_name = "assessment_knowledge_test"
    get_store.cache_clear()
    try:
        yield
    finally:
        settings.chroma_dir, settings.collection_name = original
        get_store.cache_clear()


@pytest.fixture(scope="module")
async def populated_store(isolated_knowledge_base):
    """A knowledge base holding the fixture guideline and prior assessment."""
    store = get_store()
    store.reset()
    store.add_guideline("guideline_infosec.docx", await load_text(FIXTURES / "guideline_infosec.docx"))
    pairs = await extract_qa_pairs(await load_text(FIXTURES / "prior_assessment_2024.docx"))
    store.add_prior_answers("prior_assessment_2024.docx", pairs)
    return store


async def test_embeddings_match_across_languages(populated_store):
    """An Arabic query must find the Arabic prior answer — this is why BGE-M3 was chosen."""
    hits = await populated_store.search("كم مدة الاحتفاظ بالبيانات؟", SourceType.PRIOR_ANSWER, 3)
    assert hits
    assert "سبع سنوات" in hits[0].snippet


async def test_extracts_every_question_from_a_table():
    _language, questions = await extract_questions(await load_text(FIXTURES / "new_assessment_2026.docx"))
    assert len(questions) == 5
    # The Arabic row must survive extraction and be tagged as Arabic.
    arabic = [q for q in questions if q.language == "ar"]
    assert len(arabic) == 1
    assert "الاحتفاظ" in arabic[0].text


async def test_qa_extraction_recovers_answers_from_a_filled_form():
    pairs = await extract_qa_pairs(await load_text(FIXTURES / "prior_assessment_2024.docx"))
    assert len(pairs) == 4
    assert any("ISO 27001" in pair.answer for pair in pairs)


async def test_answers_each_question_in_its_own_language(populated_store):
    result = await service.answer_assessment(FIXTURES / "new_assessment_2026.docx")
    by_id = {answered.question.id: answered for answered in result.answers}

    assert result.questions_found == 5

    # A question the knowledge base covers: answered, well supported, cited.
    certified = by_id["1"]
    assert certified.confidence > 0.6
    assert certified.evidence
    assert "27001" in certified.answer

    # The Arabic question must come back in Arabic, not the document's dominant language.
    retention = by_id["4"]
    assert any("؀" <= char <= "ۿ" for char in retention.answer)

    # A question nothing covers must abstain rather than invent a roadmap.
    quantum = by_id["5"]
    assert quantum.needs_review
    assert quantum.confidence <= 0.4


async def test_answers_a_pdf_assessment_from_arabic_sources(populated_store):
    """The retention answer only exists in Arabic; an English PDF question must still find it."""
    result = await service.answer_assessment(FIXTURES / "new_assessment_2026.pdf")
    by_id = {answered.question.id: answered for answered in result.answers}

    retention = by_id["4"]
    assert "seven" in retention.answer.lower() or "7" in retention.answer
    assert retention.evidence


async def test_forced_language_overrides_every_question(populated_store):
    result = await service.answer_assessment(FIXTURES / "new_assessment_2026.docx", language="ar")
    assert result.language == "ar"

    answered_questions = [a for a in result.answers if a.answer]
    assert answered_questions
    for answered in answered_questions:
        assert any("؀" <= char <= "ۿ" for char in answered.answer), answered.answer
