"""LangSmith tracing: the bridge into the environment, and what a trace says.

The bridge is the part worth testing. LangChain reads `os.environ`;
pydantic-settings populates a `Settings` object and nothing else, and no code
here calls `load_dotenv`. So `LANGSMITH_TRACING=true` in `.env` reaches
`settings.langsmith_tracing` and, without `configure_tracing`, is never seen by
any library — tracing that looks configured and silently does nothing.
"""

from __future__ import annotations

import os

import pytest

from src.config import Settings, configure_tracing
from src.graph.workflow import trace_config
from src.models import Question, QuestionType


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("LANGSMITH_TRACING", "LANGSMITH_ENDPOINT",
                 "LANGSMITH_API_KEY", "LANGSMITH_PROJECT"):
        monkeypatch.delenv(name, raising=False)


def configure(monkeypatch, **overrides) -> bool:
    """Run the bridge against a settings object built for this test."""
    import src.config as config

    monkeypatch.setattr(config, "settings", Settings(_env_file=None, **overrides))
    return configure_tracing()


# --- the bridge ------------------------------------------------------------


def test_settings_alone_do_not_switch_tracing_on(clean_env):
    """The trap this exists to close."""
    settings = Settings(_env_file=None, langsmith_tracing=True, langsmith_api_key="k")
    assert settings.langsmith_tracing is True
    assert "LANGSMITH_TRACING" not in os.environ


def test_the_bridge_publishes_every_variable(clean_env, monkeypatch):
    on = configure(
        monkeypatch,
        langsmith_tracing=True,
        langsmith_api_key="lsv2_test",
        langsmith_endpoint="https://eu.api.smith.langchain.com",
        langsmith_project="Proj",
    )

    assert on is True
    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_API_KEY"] == "lsv2_test"
    assert os.environ["LANGSMITH_ENDPOINT"] == "https://eu.api.smith.langchain.com"
    assert os.environ["LANGSMITH_PROJECT"] == "Proj"


def test_nothing_is_published_when_tracing_is_off(clean_env, monkeypatch):
    assert configure(monkeypatch, langsmith_tracing=False, langsmith_api_key="k") is False
    assert "LANGSMITH_TRACING" not in os.environ


def test_tracing_without_a_key_is_refused_rather_than_half_configured(clean_env, monkeypatch, caplog):
    """Publishing the switch without a key produces a client that fails on
    every call; better to stay off and say why."""
    assert configure(monkeypatch, langsmith_tracing=True, langsmith_api_key="") is False
    assert "LANGSMITH_TRACING" not in os.environ
    assert any("LANGSMITH_API_KEY" in record.message for record in caplog.records)


def test_the_real_environment_wins_over_the_file(clean_env, monkeypatch):
    """A shell export or a container's own configuration must not be
    overwritten by whatever happens to be in `.env`."""
    monkeypatch.setenv("LANGSMITH_PROJECT", "set-by-the-operator")

    configure(monkeypatch, langsmith_tracing=True, langsmith_api_key="k",
              langsmith_project="from-the-file")

    assert os.environ["LANGSMITH_PROJECT"] == "set-by-the-operator"


# --- what a trace carries --------------------------------------------------


def question(**overrides) -> Question:
    return Question(**{"id": "7", "text": "Do you encrypt data at rest?", **overrides})


def test_a_trace_is_named_for_its_question():
    """Every trace was called "LangGraph", which makes a project of a few
    thousand runs useless for finding the one that went wrong."""
    assert trace_config(question(), "en")["run_name"] == "answer[7]"


def test_the_tags_are_the_axes_worth_slicing_by():
    config = trace_config(question(question_type=QuestionType.YES_NO), "ar", run_id="batch-9")
    assert set(config["tags"]) == {"lang:ar", "type:yes_no", "run:batch-9"}


def test_a_question_answered_outside_a_batch_carries_no_run_tag():
    assert not any(t.startswith("run:") for t in trace_config(question(), "en")["tags"])


def test_the_batch_is_recorded_so_sibling_questions_can_be_found():
    """The first thing anyone looking at a failed run wants is the other
    questions from the same run."""
    assert trace_config(question(), "en", run_id="batch-9")["metadata"]["run_id"] == "batch-9"


def test_the_metadata_carries_no_answer_or_document_text():
    """The prompts already carry document text; the metadata must not add more
    of it, and must never carry the answer."""
    config = trace_config(question(section="4. Cryptography"), "en", run_id="r")
    values = " ".join(str(v) for v in config["metadata"].values())

    assert config["metadata"]["question_id"] == "7"
    assert "4. Cryptography" in values
    assert set(config["metadata"]) == {
        "question_id", "question", "language", "question_type", "run_id", "section"}


def test_a_very_long_question_is_truncated_in_the_metadata():
    config = trace_config(question(text="x" * 5000), "en")
    assert len(config["metadata"]["question"]) <= 300
