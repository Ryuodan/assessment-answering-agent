"""The cleanup-round tools: gc's candidates and the grade letters, on small trees in tmp_path."""

from __future__ import annotations

from pathlib import Path

from harness import gc, grades


def write(root: Path, name: str, text: str) -> None:
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(text, encoding="utf-8")


def test_gc_finds_each_kind_of_candidate(tmp_path: Path) -> None:
    block = "".join(f"    total = total + {n} * factor_{n}\n" for n in range(9))
    write(
        tmp_path,
        "src/a.py",
        f"def used():\n    return 1\n\n\ndef forgotten():\n    total = 0\n{block}    return total\n",
    )
    write(
        tmp_path,
        "src/b.py",
        f"from src.a import used\n\n\ndef again():\n    total = 0\n{block}    return used()  # TODO drop\n",
    )
    write(
        tmp_path,
        "src/c.py",
        "def checked():\n    return 2\n\n\nx = 1  # type: ignore\ny = 2  # noqa: E501 - a long URL\n",
    )
    write(tmp_path, "tests/test_c.py", "from src.c import checked\n")
    write(tmp_path, "README.md", "See `src/a.py`, `src/gone.py` and `src/.../x.py`.\n")

    found = gc.candidates(tmp_path)

    assert "UNUSED src/a.py:5: forgotten" in found
    assert "TEST-ONLY src/c.py:1: checked" in found
    assert not any(line.startswith("UNUSED") and "used" == line.rsplit(" ", 1)[1] for line in found)
    assert any(line.startswith("DUPLICATE src/a.py:") and "src/b.py:" in line for line in found)
    assert len([line for line in found if line.startswith("DUPLICATE")]) == 1, "one block, reported once"
    assert found.count("SUPPRESS src/c.py:5: type: ignore without a reason") == 1
    assert not any("src/c.py:6" in line for line in found), "a suppression with a reason is fine"
    assert "STALE-PATH README.md:1: `src/gone.py` does not exist" in found
    assert not any("src/.../x.py" in line for line in found)
    assert any(line.startswith("TODO src/b.py:") for line in found)


def test_grade_letters_follow_fixed_bands() -> None:
    assert [grades._letter(v, (90, 80, 70), True) for v in (95, 85, 75, 10)] == ["A", "B", "C", "D"]
    assert [grades._letter(v, (0, 3, 8), False) for v in (0, 2, 8, 9)] == ["A", "B", "C", "D"]
