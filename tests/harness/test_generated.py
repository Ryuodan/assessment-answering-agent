"""Generated documents are never stale (GP-12)."""

from __future__ import annotations

import pytest

from harness import gen
from harness.report import rel


@pytest.fixture(scope="module")
def generated():
    """Every document, built once: each build imports the app and reads the code (plan 015, TD-017)."""
    return gen.documents()


@pytest.mark.parametrize("path", sorted(gen.documents(), key=str), ids=lambda p: p.name)
def test_generated_document_is_current(path, generated):
    expected = generated[path]
    actual = path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.exists() else ""
    assert actual == expected, (
        f"{rel(path)} is stale: the code it is generated from has changed.\n"
        "  FIX: run `uv run poe gen` and commit the result; never edit the file by hand"
    )


def test_the_settings_catalogue_lists_every_setting():
    catalogue = gen.settings_md()
    from harness.arch import settings_fields

    missing = [name for name in settings_fields(gen.CONFIG) if f"`{name.upper()}`" not in catalogue]
    assert not missing
