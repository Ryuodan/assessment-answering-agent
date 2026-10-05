"""The eval-data vault: round trips, refusals, and a key that is never shown.

Every test works in tmp_path with freshly generated keys and made-up files;
nothing here reads the real .env or the real eval data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval import vault
from eval.vault import Vault, VaultError, new_key, write_key

NAMES = ("cases.json", "memory.json")


@pytest.fixture
def box(tmp_path: Path) -> Vault:
    plain = tmp_path / "eval"
    plain.mkdir()
    (plain / "cases.json").write_text(json.dumps([{"q": "Do you encrypt?", "a": "Yes"}]), encoding="utf-8")
    (plain / "memory.json").write_text(json.dumps([{"q": "سؤال", "a": "نعم"}], ensure_ascii=False), encoding="utf-8")
    return Vault(plain_dir=plain, sealed_dir=plain / "sealed", names=NAMES)


def originals(box: Vault) -> dict[str, bytes]:
    return {name: (box.plain_dir / name).read_bytes() for name in NAMES}


def test_seal_then_unlock_returns_the_same_bytes(box, tmp_path):
    key, before = new_key(), originals(box)
    assert box.seal(key) == ["cases.json: sealed", "memory.json: sealed"]
    out = tmp_path / "out"
    box.unlock(key, dest=out)
    assert {name: (out / name).read_bytes() for name in NAMES} == before


def test_the_sealed_file_does_not_contain_the_plaintext(box):
    box.seal(new_key())
    sealed = box.sealed_path("cases.json").read_bytes()
    assert b"encrypt" not in sealed and sealed.startswith(vault.MAGIC)


def test_sealing_an_unchanged_file_writes_nothing(box):
    key = new_key()
    box.seal(key)
    first = box.sealed_path("cases.json").read_bytes()
    assert box.seal(key) == ["cases.json: unchanged", "memory.json: unchanged"]
    assert box.sealed_path("cases.json").read_bytes() == first


def test_a_changed_plaintext_is_resealed_and_status_says_so(box):
    key = new_key()
    box.seal(key)
    (box.plain_dir / "cases.json").write_text("[]", encoding="utf-8")
    assert "CHANGED since sealing" in box.status()[0]
    assert box.seal(key)[0] == "cases.json: sealed"
    assert box.status()[0] == "cases.json: sealed, unlocked, in step"


def test_a_wrong_key_fails_and_writes_nothing(box, tmp_path):
    box.seal(new_key())
    with pytest.raises(VaultError, match="not the one it was sealed with") as caught:
        box.unlock(new_key(), dest=tmp_path / "out")
    assert caught.value.fix
    assert not (tmp_path / "out").exists()


def test_a_tampered_file_fails(box, tmp_path):
    box.seal(new_key())
    blob = bytearray(box.sealed_path("cases.json").read_bytes())
    blob[-1] ^= 1
    box.sealed_path("cases.json").write_bytes(bytes(blob))
    with pytest.raises(VaultError, match="altered"):
        box.unlock(new_key(), dest=tmp_path / "out")


def test_two_sealed_files_cannot_be_swapped(box, tmp_path):
    key = new_key()
    box.seal(key)
    a, b = box.sealed_path("cases.json"), box.sealed_path("memory.json")
    a_bytes, b_bytes = a.read_bytes(), b.read_bytes()
    a.write_bytes(b_bytes)
    b.write_bytes(a_bytes)
    with pytest.raises(VaultError):
        box.unlock(key, dest=tmp_path / "out")


@pytest.mark.parametrize("key", ["", "   ", "not-base64!!", "c2hvcnQ="])
def test_a_missing_or_malformed_key_is_refused_with_a_fix(box, key):
    with pytest.raises(VaultError) as caught:
        box.seal(key)
    assert caught.value.fix
    if key.strip():
        assert key.strip() not in str(caught.value)


def test_unlock_will_not_overwrite_a_local_copy_that_differs(box):
    key = new_key()
    box.seal(key)
    (box.plain_dir / "cases.json").write_text("[1]", encoding="utf-8")
    with pytest.raises(VaultError, match="refusing to overwrite") as caught:
        box.unlock(key)
    assert "eval-seal" in caught.value.fix
    assert (box.plain_dir / "cases.json").read_text(encoding="utf-8") == "[1]"
    box.unlock(key, force=True)
    assert (box.plain_dir / "cases.json").read_text(encoding="utf-8") != "[1]"


def test_sealing_with_a_different_key_than_the_folder_uses_is_refused(box):
    box.seal(new_key())
    (box.plain_dir / "cases.json").write_text("[]", encoding="utf-8")
    with pytest.raises(VaultError, match="not the one it was sealed with"):
        box.seal(new_key())


def test_rekeying_needs_every_plaintext_present(box):
    key = new_key()
    box.seal(key)
    (box.plain_dir / "memory.json").unlink()
    with pytest.raises(VaultError, match="has no plaintext here"):
        box.seal(new_key(), force=True)


def test_status_needs_no_key(box):
    assert box.status() == [
        "cases.json: plaintext only, not sealed (run `uv run poe eval-seal`)",
        "memory.json: plaintext only, not sealed (run `uv run poe eval-seal`)",
    ]
    box.seal(new_key())
    (box.plain_dir / "cases.json").unlink()
    assert box.status()[0] == "cases.json: sealed, locked (run `uv run poe eval-unlock`)"


def test_keygen_appends_a_key_it_never_prints(tmp_path, capsys):
    env = tmp_path / ".env"
    env.write_bytes(b"GROQ_API_KEY=\r\nOTHER=1\r\n")
    message = write_key(env)
    text = env.read_bytes().decode("utf-8")  # bytes: read_text would hide the line endings
    [line] = [line for line in text.splitlines() if line.startswith("EVAL_DATA_KEY=")]
    key = line.split("=", 1)[1]
    assert len(vault.key_bytes(key)) == 32
    assert text.startswith("GROQ_API_KEY=\r\nOTHER=1\r\n"), "existing lines must be untouched"
    assert key not in message and key not in capsys.readouterr().out


def test_keygen_fills_an_empty_line_and_refuses_to_replace_a_key(tmp_path):
    env = tmp_path / ".env"
    env.write_text("EVAL_DATA_KEY=\nX=1\n", encoding="utf-8")
    write_key(env)
    assert env.read_text(encoding="utf-8").splitlines()[1] == "X=1"
    with pytest.raises(VaultError, match="already has"):
        write_key(env)


def test_require_says_how_to_unlock(tmp_path):
    with pytest.raises(FileNotFoundError, match="eval-unlock"):
        vault.require(tmp_path / "house_set.json")
