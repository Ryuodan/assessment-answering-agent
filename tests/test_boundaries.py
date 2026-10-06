"""Data from outside is validated where it arrives (plan 007)."""

from __future__ import annotations

import json
import typing

import pytest
from pydantic import ValidationError

from src import organisation
from src.config import Settings, settings
from src.docling_client import DoclingError, _await_task, _markdown
from src.forms.reading import STRATEGIES

# --- settings ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("detection_strategy", "guardd"),
        ("groq_reasoning_format", "thinking"),
        ("docling_image_export_mode", "inline"),
        ("log_level", "LOUD"),
    ],
)
def test_a_setting_outside_its_vocabulary_fails_at_startup_naming_it(name, value):
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, **{name: value})
    assert caught.value.errors()[0]["loc"] == (name,)


def test_the_log_level_may_be_written_in_any_case():
    assert Settings(_env_file=None, log_level="warning").log_level == "WARNING"


def test_the_strategy_vocabulary_is_the_readers_own():
    assert set(typing.get_args(Settings.model_fields["detection_strategy"].annotation)) == set(STRATEGIES)


# --- the organisation profile ----------------------------------------------------


def test_a_valid_profile_is_read_and_unknown_keys_are_ignored():
    settings.organisation_path.write_text(
        json.dumps({"short_name": "Contoso", "certifications": ["ISO 27001"], "unknown": 1}), encoding="utf-8"
    )
    profile = organisation.load()
    assert (profile.short_name, profile.certifications) == ("Contoso", ["ISO 27001"])


@pytest.mark.parametrize(
    "content",
    [
        '{"certifications": "ISO 27001"}',  # a string where a list belongs: once read letter by letter
        '{"short_name": 42}',
        "not json at all",
        "[]",
    ],
)
def test_a_malformed_profile_falls_back_to_the_built_in_one_and_says_so(content, caplog):
    settings.organisation_path.write_text(content, encoding="utf-8")
    assert organisation.load() == organisation.Organisation()
    assert "organisation.profile_unreadable" in caplog.text


def test_a_saved_profile_reads_back_the_same():
    profile = organisation.Organisation(short_name="Contoso", certifications=["SOC 2"], notes="Two offices.")
    organisation.save(profile)
    assert organisation.load() == profile


# --- Docling's responses -----------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "success", "document": "# not an object"},
        {"status": "success", "document": {"md_content": ["a", "list"]}},
        ["not", "an", "object"],
    ],
)
def test_a_result_of_the_wrong_shape_is_a_docling_error_so_the_fallback_applies(payload):
    with pytest.raises(DoclingError, match="unexpected conversion result"):
        _markdown(payload, "a.pdf")


async def test_a_task_of_the_wrong_shape_is_a_docling_error():
    with pytest.raises(DoclingError, match="unexpected task"):
        await _await_task({"task_id": {"nested": True}}, "a.pdf")
