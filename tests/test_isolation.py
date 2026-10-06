"""The suite runs on defaults and temporary directories, never on real configuration or data (plan 006)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src import config
from src.config import PROJECT_ROOT, Settings, settings
from tests.conftest import paths_inside_project

# Changed per test by tests/conftest.py's isolated_storage, deliberately.
PINNED = {"allowed_emails", "admin_email", "admin_password", "detection_strategy", "hybrid_search"}


def test_no_env_file_is_read_during_tests():
    assert config._env_file() is None


def test_every_setting_is_its_declared_default():
    """A developer's .env or shell cannot reach a test (TD-011)."""
    defaults = Settings(_env_file=None)
    different = [
        name
        for name in Settings.model_fields
        if name not in PINNED
        and not isinstance(getattr(settings, name), Path)
        and getattr(settings, name) != getattr(defaults, name)
    ]
    assert not different


def test_no_path_setting_points_into_the_project():
    assert paths_inside_project(settings) == []


def test_the_guard_catches_a_path_left_pointing_into_the_project(tmp_path):
    forgotten = SimpleNamespace(db_path=tmp_path / "app.db", organisation_path=PROJECT_ROOT / "data" / "o.json")
    assert paths_inside_project(forgotten) == ["organisation_path"]


def test_the_env_file_switch(monkeypatch, tmp_path):
    monkeypatch.delenv("ASSESSMENT_ANSWER_ENV_FILE")
    assert config._env_file() == PROJECT_ROOT / ".env"
    other = tmp_path / "other.env"
    monkeypatch.setenv("ASSESSMENT_ANSWER_ENV_FILE", str(other))
    assert config._env_file() == other
    other.write_text("MAX_EVIDENCE_CHUNKS=99\n", encoding="utf-8")
    assert Settings(_env_file=config._env_file()).max_evidence_chunks == 99
    monkeypatch.setenv("ASSESSMENT_ANSWER_ENV_FILE", "")
    assert config._env_file() is None


def test_the_organisation_profile_is_read_from_its_setting(tmp_path):
    from src import organisation

    assert settings.organisation_path.parent != PROJECT_ROOT / "data"
    settings.organisation_path.write_text('{"short_name": "Contoso"}', encoding="utf-8")
    assert organisation.load().short_name == "Contoso"
