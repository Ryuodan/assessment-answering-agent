"""A product's questionnaire names its product, and says which sources are its own (plan 031).

The user found product answers that "mix unrelated information from the shared
knowledge base, and it sounds like it is information related to the product".
Measured before this plan on 24 product questions: answers with no source of the
product's own said "Msegat is hosted on Alibaba Cloud in Saudi Arabia" and "Data
stored by Ole5 is encrypted at rest with AES-256", and went into the file at
0.85 to 0.90. The drafter had been told only that some sources were "FOR THIS
PRODUCT", never which product, and nothing about the rest.
"""

from __future__ import annotations

import pytest

from src import identity, organisation, products
from src.config import settings
from src.graph import nodes
from src.models import Evidence, Question, SourceType
from src.product_prompts import product_answering, product_review, product_sources_line
from src.prompts import (
    ANSWER_SYSTEM,
    LANGUAGE_NAMES,
    PRODUCT_SOURCES_NOTE,
    REVIEW_SYSTEM,
    format_question_block,
    format_sources_block,
)
from src.schemas import AnswerReview, DraftedAnswer

TEAM = settings.default_team


@pytest.fixture
def availo():
    identity.ensure_team(TEAM)
    made = products.add(None, TEAM, "Availo", description="An attendance system for employers.")
    products.add(None, TEAM, "Ole5")
    return made


@pytest.fixture
def told(monkeypatch):
    """Every (system, user) pair the drafter and the reviewer were sent, in order."""
    sent: list[tuple[str, str]] = []

    class Model:
        def __init__(self, schema):
            self.schema = schema

        async def ainvoke(self, messages):
            said = dict(messages)
            sent.append((said["system"], said["user"]))
            if self.schema is DraftedAnswer:
                return DraftedAnswer(answer="Our cryptography policy requires it.", confidence=0.8, used_source_ids=[1])
            return AnswerReview(grounded=True, confidence=0.8)

    monkeypatch.setattr(nodes, "structured_llm", lambda schema, temperature=None: Model(schema))
    return sent


def _sources(product_id: str) -> list[Evidence]:
    return [
        Evidence(
            source_type=SourceType.GUIDELINE,
            source_name="Availo facts.docx",
            snippet="Availo is hosted in Riyadh.",
            product_id=product_id,
            score=0.8,
        ),
        Evidence(
            source_type=SourceType.GUIDELINE,
            source_name="Cryptography Policy.pdf",
            snippet="Data at rest is encrypted for critical systems.",
            score=0.8,
        ),
        Evidence(
            source_type=SourceType.PRIOR_ANSWER,
            source_name="memory",
            snippet="Our platform is hosted on Alibaba Cloud.",
            score=0.8,
        ),
    ]


def _state(product_id: str, evidence: list[Evidence]) -> dict:
    question = Question(id="q1", text="Where is the system hosted?")
    return {"question": question, "language": "en", "team_id": TEAM, "product_id": product_id, "evidence": evidence}


@pytest.mark.asyncio
async def test_the_drafter_is_told_the_product_and_what_each_mark_supports(availo, told) -> None:
    state = _state(availo.id, _sources(availo.id))
    await nodes.draft(state)
    system, user = told[0]

    profile = organisation.load()
    assert system.endswith(
        product_answering("Availo", "An attendance system for employers.", profile.short_name, ["Ole5"])
    )
    assert "This questionnaire is about Availo, one of our products. An attendance system for employers." in system
    assert "Our other products are Ole5" in system
    assert "About: Availo" in user
    block = format_sources_block(nodes._sources(state), "Availo")
    assert block in user
    assert "OUR POLICY, FOR Availo — Availo facts.docx" in block
    assert "OUR POLICY, SHARED — Cryptography Policy.pdf" in block
    assert "PREVIOUS ANSWER, SHARED —" in block
    assert PRODUCT_SOURCES_NOTE not in user, "said in the system prompt, by name"


@pytest.mark.asyncio
async def test_the_reviewer_holds_a_product_fact_only_shared_sources_support(availo, told) -> None:
    state = _state(availo.id, _sources(availo.id))
    drafted = await nodes.draft(state)
    await nodes.review({**state, **drafted})
    (_, drafter), (system, reviewer) = told

    assert system == REVIEW_SYSTEM.format(language_name=LANGUAGE_NAMES["en"]) + product_review("Availo")
    assert "only a SHARED source supports" in system
    block = format_sources_block(nodes._sources(state), "Availo")
    assert block in reviewer and block in drafter, "the same marked list, for both"
    assert "About: Availo" in reviewer


def test_the_sources_say_which_are_the_products_own_above_them() -> None:
    own, policy, prior = _sources("p1")

    alone = format_sources_block([policy, prior], "Availo")
    assert alone.startswith("None of these sources is FOR Availo: they are all SHARED.")
    assert alone.startswith(product_sources_line([policy, prior], "Availo") + "\n\n[1] OUR POLICY, SHARED")

    assert format_sources_block([own, policy], "Availo").startswith("Source 1 is FOR Availo; the others are SHARED.")
    assert format_sources_block([policy, own, prior, own], "Availo").startswith(
        "Sources 2, 4 are FOR Availo; the others are SHARED."
    )


@pytest.mark.asyncio
async def test_a_general_questionnaires_prompts_are_as_they_were(availo, told) -> None:
    _own, policy, prior = _sources("")
    state = _state("", [policy, prior])
    drafted = await nodes.draft(state)
    await nodes.review({**state, **drafted})
    (drafter_system, drafter), (reviewer_system, reviewer) = told

    profile = organisation.load()
    assert drafter_system == ANSWER_SYSTEM.format(
        language_name="English", organisation=profile.describe(), addressed_as=organisation.ADDRESSED_AS
    )
    assert reviewer_system == REVIEW_SYSTEM.format(language_name="English")
    for user in (drafter, reviewer):
        assert "SHARED" not in user and "About:" not in user and "FOR " not in user
        assert format_question_block("Where is the system hosted?") in user


@pytest.mark.asyncio
async def test_a_product_the_team_no_longer_has_keeps_the_marks_it_had(availo, told) -> None:
    """Its questionnaire is kept read-only (plan 027); nothing names a product that is gone."""
    state = _state("p-gone", _sources("p-gone"))
    await nodes.draft(state)
    system, user = told[0]

    assert "THE PRODUCT THIS QUESTIONNAIRE IS ABOUT" not in system
    assert PRODUCT_SOURCES_NOTE in user and "FOR THIS PRODUCT" in user and "SHARED" not in user
