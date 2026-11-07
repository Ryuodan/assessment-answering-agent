"""The adversarial review of plans 033 and 034: what it found, each pinned by a test.

1. A kept search plan, and "the same question", went by the words alone, so "If yes,
   please provide details." under Encryption lent its searches, and its earlier
   answer, to the same words under Access control.
2. A chat turn that opened a questionnaire deleted while it ran was lost to the
   foreign key when it was saved.
3. Kept plans outlived the planner that wrote them and today's query limit, and an
   evaluation read and wrote them.
4. With the reranker's order, the same question's earlier answer was cut.
5. Deleting a questionnaire left its questions' wording in the kept plans.
6. The retention pass deleted what was opened after it listed it.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from src import batches, conversations, identity, prompts, retention, search_plans, store
from src.api import app
from src.config import settings
from src.formatting import asks_on_its_own, same_wording
from src.graph import kept_searches
from src.graph.state import select_evidence
from src.models import Evidence, Question, SourceType
from tests import forms_fixtures as shapes

TEAM = settings.default_team
FOLLOW_UP = "If yes, please provide details."
ASKED = "Do you have a documented incident response plan?"


def prior(question: str, score: float = 0.5) -> Evidence:
    return Evidence(
        source_type=SourceType.PRIOR_ANSWER,
        source_name="Answer memory",
        snippet=f"Q: {question}\nA: Yes.",
        score=score,
        entry_id=question[:16],
    )


def guideline(n: int, score: float = 0.6) -> Evidence:
    return Evidence(
        source_type=SourceType.GUIDELINE, source_name="Policy.pdf", snippet=f"Clause {n}.", chunk=n, score=score
    )


def _state(text: str, section: str = "") -> dict:
    return {
        "question": Question(id="1", text=text, section=section, language="en"),
        "language": "en",
        "team_id": TEAM,
        "product_id": "",
    }


# --- 1. the same words are not always the same question ---------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        FOLLOW_UP,
        "If so, describe it.",
        "Please provide evidence.",
        "Comments",
        "إذا كانت الإجابة نعم، يرجى التوضيح",
        "MFA?",
    ],
)
def test_a_follow_up_or_a_few_words_never_ask_on_their_own(question: str) -> None:
    assert not asks_on_its_own(question)
    assert not same_wording(question, question), "so never 'the same question' by its words"


def test_a_question_that_says_what_it_asks_still_does() -> None:
    assert asks_on_its_own(ASKED) and same_wording(ASKED, ASKED.lower())


def test_a_follow_ups_earlier_answer_is_not_put_first_for_another_topic() -> None:
    late = prior(FOLLOW_UP, score=0.05)
    evidence = [prior(f"Neighbour {n}?", score=0.8 - n / 100) for n in range(3)] + [late]
    evidence += [guideline(n) for n in range(12)]
    selected = select_evidence(evidence, limit=10, prior_cap=2, question=FOLLOW_UP)
    assert late not in selected
    assert "SAME QUESTION" not in prompts.format_sources_block([late], question=FOLLOW_UP)


def test_a_plan_is_kept_under_its_section_and_never_for_a_follow_up(monkeypatch) -> None:
    monkeypatch.setattr(settings, "reuse_search_plans", True)
    monkeypatch.setattr(settings, "query_expansion", True)
    kept_searches.keep(_state(ASKED, "Incident response"), [ASKED, "incident plan documented"])
    assert kept_searches.recall(_state(ASKED, "Incident response")) == [ASKED, "incident plan documented"]
    assert kept_searches.recall(_state(ASKED, "Business continuity")) is None, "another section is planned for itself"

    kept_searches.keep(_state(FOLLOW_UP, "Encryption"), [FOLLOW_UP, "encryption at rest"])
    assert kept_searches.recall(_state(FOLLOW_UP, "Encryption")) is None, "a follow-up is planned every time"


# --- 3. kept plans do not outlive the planner, or today's limit -------------------------------------


def test_a_plan_written_by_another_planner_is_planned_again(monkeypatch) -> None:
    search_plans.keep(TEAM, "", "en", ASKED, [ASKED, "incident response"])
    monkeypatch.setattr(prompts, "QUERY_PLAN_SYSTEM", prompts.QUERY_PLAN_SYSTEM + " Changed.")
    monkeypatch.setattr(search_plans, "QUERY_PLAN_SYSTEM", prompts.QUERY_PLAN_SYSTEM)
    assert search_plans.recall(TEAM, "", "en", ASKED) is None
    monkeypatch.undo()
    monkeypatch.setattr(settings, "groq_chat_model", "another/model")
    assert search_plans.recall(TEAM, "", "en", ASKED) is None


def test_a_kept_plan_is_cut_to_todays_limit(monkeypatch) -> None:
    monkeypatch.setattr(settings, "reuse_search_plans", True)
    monkeypatch.setattr(settings, "query_expansion", True)
    kept_searches.keep(_state(ASKED), [ASKED, "a one", "a two", "a three", "a four"])
    monkeypatch.setattr(settings, "max_search_queries", 2)
    assert kept_searches.recall(_state(ASKED)) == [ASKED, "a one"]


def test_an_evaluation_keeps_no_plans_and_reads_none(monkeypatch) -> None:
    import eval as evaluation

    monkeypatch.setattr(settings, "reuse_search_plans", True)
    importlib.reload(evaluation)
    assert settings.reuse_search_plans is True, "importing the package changes nothing"
    evaluation.plan_afresh()
    assert settings.reuse_search_plans is False, "each runner turns them off as it starts"


@pytest.mark.parametrize(
    "runner",
    [
        "scripts/run_house_eval.py",
        "eval/run_eval.py",
        "scripts/run_both_evals.py",
        "scripts/compare_memory_use.py",
        "scripts/probe_certifications.py",
        "scripts/measure_noise.py",
    ],
)
def test_every_evaluation_runner_plans_afresh(runner: str) -> None:
    from src.config import PROJECT_ROOT

    main = (PROJECT_ROOT / runner).read_text(encoding="utf-8").split("def main() -> int:", 1)[1].split("\ndef ", 1)[0]
    assert "evaluation.plan_afresh()" in main


# --- 4. the same question's answer survives the cut, wherever it ranks -------------------------------


def test_the_same_questions_answer_survives_a_reranked_order() -> None:
    mine = prior(ASKED, score=0.2)
    evidence = [guideline(n) for n in range(12)] + [mine]  # the cross-encoder's order: priors not first
    selected = select_evidence(evidence, limit=10, prior_cap=2, question=ASKED)
    assert selected[0] is mine and len(selected) == 10


# --- 2. a chat turn about a questionnaire deleted meanwhile is saved without it -----------------------


def test_a_turn_is_saved_though_its_questionnaire_was_deleted_meanwhile(tmp_path: Path) -> None:
    user = identity.local_user()
    with TestClient(app) as client:
        path = shapes.simple(tmp_path / "vendor.xlsx")
        opened = client.post("/api/forms", files={"file": (path.name, path.read_bytes())}, data={"product": ""}).json()
    conversation = conversations.create(user, "Answer the vendor file")
    conversation.batch_id = opened["id"]  # what open_questionnaire set, in the turn's memory
    batches.delete(opened["id"])  # deleted from "Or pick up" while the turn ran

    conversation.messages = [HumanMessage(content="Answer it"), AIMessage(content="Done.")]
    conversations.save(conversation)  # raised IntegrityError and lost the turn

    saved = conversations.load(conversation.id, team_id=user.team_id, actor_email=user.email)
    assert saved is not None and [m.content for m in saved.messages] == ["Answer it", "Done."]
    assert not saved.batch_id


# --- 5 and 6. delete takes the plans; the pass looks again before deleting ------------------------------


def test_deleting_a_questionnaire_takes_its_questions_kept_plans(tmp_path: Path) -> None:
    with TestClient(app) as client:
        path = shapes.simple(tmp_path / "vendor.xlsx")
        opened = client.post("/api/forms", files={"file": (path.name, path.read_bytes())}, data={"product": ""}).json()
        batch = batches.load(opened["id"])
        asked = [q for q in batch.form.questions if asks_on_its_own(q.text)]
        assert asked, "the fixture has questions that ask on their own"
        for question in asked:
            search_plans.keep(TEAM, "", "en", question.text, [question.text], question.section)
        search_plans.keep(TEAM, "", "en", ASKED, [ASKED])

        assert client.delete(f"/api/forms/{opened['id']}").status_code == 200

    assert all(search_plans.recall(TEAM, "", "en", q.text, q.section) is None for q in asked)
    assert search_plans.recall(TEAM, "", "en", ASKED) == [ASKED], "another question's plan stays"


def test_the_pass_spares_what_was_opened_after_it_listed_it(monkeypatch) -> None:
    monkeypatch.setattr(settings, "retention_days", 180)
    user = identity.local_user()
    conversation = conversations.create(user, "Old chat")
    old = "2020-01-01T00:00:00+00:00"
    conn = store.connect()
    conn.execute(
        "UPDATE conversations SET updated_at = ?, used_at = '' WHERE conversation_id = ?", (old, conversation.id)
    )
    conn.commit()
    [due] = [item for item in retention.due() if item.id == conversation.id]

    # Opened while the pass ran, as a reloading tab does at start-up.
    conn.execute("UPDATE conversations SET used_at = ? WHERE conversation_id = ?", (store.utcnow(), conversation.id))
    conn.commit()

    assert retention._remove(due) is None, "opened since it was listed: kept"
    assert conversations.load(conversation.id, team_id=user.team_id, actor_email=user.email) is not None
