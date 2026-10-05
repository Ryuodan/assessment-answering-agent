"""Snapshots, and settings pinned to their declared defaults.

`snapshot(name, data)` compares `data` with `snapshots/<name>.json`. Snapshots
are written only when the environment says `UPDATE_SNAPSHOTS=1`, which is what
`uv run poe snapshots` sets; a missing or different snapshot fails with the
diff and a FIX line.

`default_settings` resets every setting to the default declared in
`src/config.py`, so the developer's `.env` cannot change what these tests see
(TD-011). Storage paths stay where `isolated_storage` put them, and the
questionnaire reader stays on the rules, which make no model calls.
"""

from __future__ import annotations

import difflib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from src.config import Settings, settings

SNAPSHOTS = Path(__file__).parent / "snapshots"
_KEEP = {"detection_strategy", "allowed_emails", "admin_email", "admin_password"}


@pytest.fixture
def default_settings(monkeypatch):
    defaults = Settings(_env_file=None)
    for name in Settings.model_fields:
        current = getattr(settings, name)
        if name in _KEEP or isinstance(current, Path):
            continue
        monkeypatch.setattr(settings, name, getattr(defaults, name))
    return settings


def scrub(data: Any, tmp_path: Path) -> Any:
    """Replace the per-test temporary directory with a stable placeholder."""
    text = json.dumps(data, ensure_ascii=False)
    for form in {str(tmp_path), tmp_path.as_posix(), str(tmp_path).replace("\\", "\\\\")}:
        text = text.replace(form, "<tmp>")
    return json.loads(text)


_CLAIMED: dict[str, str] = {}


@pytest.fixture
def snapshot(tmp_path, request):
    def match(name: str, data: Any) -> None:
        # Two tests writing one snapshot overwrite each other silently: the
        # .docx and .pdf of one fixture once shared a name by file stem.
        owner = _CLAIMED.setdefault(name, request.node.nodeid)
        if owner != request.node.nodeid:
            pytest.fail(
                f"snapshot '{name}' is already used by {owner}\n"
                "  FIX: give each test its own snapshot name (include whatever distinguishes the cases)"
            )
        path = SNAPSHOTS / f"{name}.json"
        text = json.dumps(scrub(data, tmp_path), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        if os.environ.get("UPDATE_SNAPSHOTS") == "1":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            return
        where = path.relative_to(SNAPSHOTS.parent.parent.parent).as_posix()
        if not path.exists():
            pytest.fail(
                f"no snapshot at {where}\n"
                "  FIX: run `uv run poe snapshots` to record it, then read it: it is the behaviour being pinned"
            )
        expected = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        if expected != text:
            diff = "".join(
                difflib.unified_diff(
                    expected.splitlines(keepends=True), text.splitlines(keepends=True), "snapshot", "now", n=2
                )
            )
            pytest.fail(
                f"behaviour changed: {where} no longer matches.\n{diff[:4000]}\n"
                "  FIX: if the change is intended, run `uv run poe snapshots`, review `git diff`, and say why in "
                "the commit; if it is not, the last change broke this path"
            )

    return match
