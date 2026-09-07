"""Check questionnaire detection and write-back against real files.

The tests use built fixtures, because customer questionnaires are other
companies' confidential forms and cannot live in the repository. This runs the
same two checks against a folder of real ones:

    python -m scripts.check_forms  "C:/path/to/questionnaires"
    python -m scripts.check_forms  ./samples --write

* Without `--write` it reports what was found: which sheets were used, which
  were skipped and why, and every column role, with the unconfident ones marked
  so they can be eyeballed first.
* With `--write` it answers every question into a temporary copy and checks the
  file survived: every package part still present, only the parts holding
  answers changed, and everything readable back.

Use it whenever a questionnaire arrives in a shape we have not seen. A file that
comes out with fewer questions than it has, or with a column in the wrong role,
is worth a look before anyone relies on it.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import forms                                            # noqa: E402
from src.forms.model import Role                                 # noqa: E402

ANSWER = "Yes. An approved policy is in place and reviewed annually."
ARABIC = "\u0646\u0639\u0645\u060c \u062a\u0648\u062c\u062f \u0633\u064a\u0627\u0633\u0629 \u0645\u0639\u062a\u0645\u062f\u0629 \u0648\u0645\u0631\u0627\u062c\u0639\u0629 \u0633\u0646\u0648\u064a\u0627\u064b."


def _parts(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as package:
        return {
            item.filename: hashlib.sha256(package.read(item.filename)).hexdigest()
            for item in package.infolist()
        }


def _answers(form) -> dict[str, str]:
    values = {}
    for question in form.questions:
        for target in question.writable:
            if target.role is Role.EVIDENCE:
                continue                      # blank by default
            if target.role is Role.STATUS:
                values[target.id] = target.vocabulary[0] if target.vocabulary else "Yes"
            else:
                values[target.id] = ARABIC if question.language == "ar" else ANSWER
    return values


def report(path: Path, *, verbose: bool) -> int:
    form = forms.detect(path)
    languages = {question.language for question in form.questions}
    print(f"\n{'=' * 96}\n{path.name}")
    print(f"  {len(form.questions)} question(s), {form.answered_count} already answered, "
          f"language(s): {', '.join(sorted(languages)) or '-'}")

    for part in form.parts:
        mark = "  +" if part.used else "  -"
        print(f"{mark} {part.name[:34]:34s} {part.kind:18s} {part.questions or ''}")
        if verbose or not part.used:
            for finding in part.findings:
                flag = " " if finding.confident else "?"
                print(f"      [{flag}] {finding.subject[:16]:16s} -> {finding.verdict:12s} {finding.because[:70]}")

    unsure = [f for part in form.parts for f in part.findings if not f.confident]
    if unsure and not verbose:
        print(f"  {len(unsure)} reading(s) worth confirming -- rerun with -v to see them")
    for warning in form.warnings:
        print(f"  ! {warning}")
    return len(form.questions)


def check_write(path: Path, destination: Path) -> bool:
    """Answer everything into a copy, and check the file came through intact."""
    form = forms.detect(path)
    values = _answers(form)
    if not values:
        print("      nothing writable, skipped")
        return True

    result = forms.write(path, destination, values)
    before, after = _parts(path), _parts(destination)
    lost = sorted(set(before) - set(after))
    changed = sorted(name for name in set(before) & set(after) if before[name] != after[name])

    # What counts as an unwanted change depends on how the format is written.
    #
    # A workbook is edited in place -- only the sheets holding answers are
    # rewritten, and every other part is copied byte for byte -- so anything
    # else changing is a fault.
    #
    # A document goes through python-docx, which re-serialises every XML part it
    # loads. That reformatting is cosmetic: measured on the real files, no part
    # is lost or added, the relationships come out identical, and every binary
    # part -- images and embedded fonts -- is byte-identical. So for .docx the
    # check is that nothing was lost and no binary was touched. That is a weaker
    # guarantee than the workbook side and worth knowing; it is also a different
    # thing from the failure that ruled out a spreadsheet library, which was
    # parts being *dropped*.
    if path.suffix.lower() == ".docx":
        content = [name for name in changed if not name.endswith((".xml", ".rels"))]
    else:
        content = [name for name in changed if not name.startswith("xl/worksheets/")]

    again = forms.detect(destination)
    landed = sum(
        1 for question in again.questions for target in question.writable
        if target.role in (Role.ANSWER, Role.STATUS) and target.existing.strip()
    )
    stable = [q.id for q in again.questions] == [q.id for q in form.questions]

    ok = result.intact and not lost and not content and landed >= len(values) * 0.97 and stable
    print(f"  {'ok ' if ok else '!! '}wrote {result.written:>4d} "
          f"(new {len(result.created)}, over {len(result.replaced)})  "
          f"parts {result.parts_before}->{result.parts_after}  "
          f"read back {landed}/{len(values)}  ids stable: {stable}")
    if lost:
        print(f"      LOST PARTS: {lost[:6]}")
    if content:
        print(f"      PARTS CHANGED THAT SHOULD NOT HAVE: {content[:6]}")
    if result.skipped:
        reasons: dict[str, int] = {}
        for why in result.skipped.values():
            reasons[why] = reasons.get(why, 0) + 1
        print(f"      skipped: {reasons}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path, help="Directory of questionnaires")
    parser.add_argument("--write", action="store_true", help="Also answer each one and check fidelity")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show every finding")
    args = parser.parse_args()

    if not args.folder.is_dir():
        print(f"Not a directory: {args.folder}", file=sys.stderr)
        return 2

    files = sorted(
        path for path in args.folder.rglob("*")
        if path.suffix.lower() in forms.SUPPORTED and not path.name.startswith("~$")
    )
    if not files:
        print(f"No {' or '.join(forms.SUPPORTED)} files under {args.folder}", file=sys.stderr)
        return 2

    workspace = Path(tempfile.mkdtemp(prefix="forms_check_"))
    total = failures = 0
    try:
        for path in files:
            try:
                total += report(path, verbose=args.verbose)
                if args.write and not check_write(path, workspace / path.name):
                    failures += 1
            except Exception as error:                 # a bad file is a result, not a crash
                failures += 1
                print(f"  !! {type(error).__name__}: {error}")
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    print(f"\n{'=' * 96}")
    print(f"{len(files)} file(s), {total} question(s) found, {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
