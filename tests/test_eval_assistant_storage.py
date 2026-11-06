"""The assistant's evaluation runs on scratch storage, the index included (TD-072).

It recorded into a scratch database but searched, and wrote, the deployment's own
index: a case that has the assistant write an answer by hand indexes it, and the
answer memory adopts what is indexed into the real database when it is next read.
"""

from __future__ import annotations

from scripts import eval_assistant
from src.config import settings


def test_the_run_searches_a_copy_of_the_index_and_its_writes_stay_there(tmp_path, monkeypatch) -> None:
    real = tmp_path / "chroma_db"
    real.mkdir()
    (real / "chroma.sqlite3").write_bytes(b"the team's index")
    monkeypatch.setattr(settings, "chroma_dir", real)
    monkeypatch.delenv("CHROMA_DIR", raising=False)
    at_exit: list = []
    monkeypatch.setattr("atexit.register", lambda call, *args, **kwargs: at_exit.append((call, args, kwargs)))

    copy = eval_assistant._use_a_scratch_index()

    assert copy is not None and copy != real
    assert settings.chroma_dir == copy
    assert (copy / "chroma.sqlite3").read_bytes() == b"the team's index", "the real corpus, so retrieval is measured"
    (copy / "chroma.sqlite3").write_bytes(b"an answer a case wrote")
    assert (real / "chroma.sqlite3").read_bytes() == b"the team's index"

    [(call, args, kwargs)] = at_exit
    call(*args, **kwargs)
    assert not copy.exists(), "removed when the run ends"


def test_an_index_named_on_purpose_is_used_as_it_is(tmp_path, monkeypatch) -> None:
    named = tmp_path / "kept"
    monkeypatch.setattr(settings, "chroma_dir", named)
    monkeypatch.setenv("CHROMA_DIR", str(named))

    assert eval_assistant._use_a_scratch_index() is None
    assert settings.chroma_dir == named
