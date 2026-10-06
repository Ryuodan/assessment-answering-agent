"""Load the security team's own answers into the corpus as prior answers.

    python -m scripts.index_answer_memory            # what it would do
    python -m scripts.index_answer_memory --apply
    python -m scripts.index_answer_memory --clear    # take them out again

Only `eval/answer_memory.json` -- 698 answers from twelve questionnaires. The
135 in `eval/house_set.json` are deliberately excluded: they are what the system
is graded against, and indexing them would be handing over the answer key.

Provenance is recorded per entry so an answer can say where it came from. For
this first import two of those fields are honestly empty: nothing in the source
files records *when* an answer was written or *who* wrote it. The file dates are
when somebody copied them into a folder, which is not the same thing and is not
worth pretending otherwise. Both are fields to fill going forward, from the
person who approves an answer, rather than to backfill with a guess.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain_core.documents import Document

from src.config import PROJECT_ROOT, configure_logging
from src.knowledge import get_store
from src.models import SourceType

MEMORY = PROJECT_ROOT / "eval" / "answer_memory.json"
SOURCE_NAME = "Answer memory — the security team's own answers"


def build(rows: list[dict]) -> list[Document]:
    """One document per remembered answer.

    The embedded text is the question and the answer together. Retrieval matches
    a new question against a remembered one, so the question has to be in the
    vector -- and the answer has to be there too, because two questions can be
    worded alike and answered differently.
    """
    return [
        Document(
            page_content=f"Q: {row['question']}\nA: {row['answer']}",
            metadata={
                "source_type": SourceType.PRIOR_ANSWER.value,
                "source_name": SOURCE_NAME,
                # Ours by definition: it is what this organisation said.
                "authority": "ours",
                "chunk": index,
                "entry_id": row["test_id"],
                "question": row["question"],
                "answer": row["answer"],
                "section": row.get("section", ""),
                "from_file": row.get("file", ""),
                # Unknown for this import, and left empty rather than guessed.
                # A file's modification date is when it was copied, not when the
                # answer was written or by whom.
                "answered_on": "",
                "author": "",
            },
        )
        for index, row in enumerate(rows)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--clear", action="store_true")
    args = parser.parse_args()
    configure_logging()

    store = get_store()
    if args.clear:
        store.delete_source(SOURCE_NAME)
        print(f"Removed {SOURCE_NAME!r} from the corpus.")
        print("counts by type:", store.counts_by_type())
        return 0

    rows = json.loads(MEMORY.read_text(encoding="utf-8"))
    graded = {
        r["question"].strip().casefold()
        for r in json.loads((PROJECT_ROOT / "eval" / "house_set.json").read_text(encoding="utf-8"))
    }
    leaked = [r for r in rows if r["question"].strip().casefold() in graded]
    if leaked:
        print(f"REFUSING: {len(leaked)} memory entries repeat a graded question verbatim.")
        for r in leaked[:5]:
            print(f"   {r['test_id']}  {r['question'][:70]}")
        return 1

    print(f"{len(rows)} answers from {len(Counter(r['file'] for r in rows))} questionnaires")
    print(f"  none of them repeats a graded question")
    print(f"  answered_on and author are empty: the source files record neither")
    if not args.apply:
        print("\nNothing written. Pass --apply.")
        return 0

    indexed = store._replace_source(SOURCE_NAME, build(rows))  # noqa: SLF001 - an operator's re-index, not app code
    print(f"\nIndexed {indexed} remembered answers.")
    print("counts by type:", store.counts_by_type())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
