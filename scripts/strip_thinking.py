"""Take a reasoning model's thinking out of answers that were already stored.

    python -m scripts.strip_thinking                 # say what would change
    python -m scripts.strip_thinking --apply         # change it
    python -m scripts.strip_thinking --apply --db data/app.db

While `GROQ_REASONING_FORMAT` was unset and the model was one that reasons,
Groq returned the thinking inside the message -- `<think>...</think>` in front
of the answer -- and every rewording (Brief, a house style, a skill, "make
these shorter") stored that as the answer. `src.formatting.without_reasoning`
stops new ones; this repairs what is already saved.

It touches the answers that can reach a customer's file or a person's screen:
the answers stored against a questionnaire, the answers of a saved run, and the
answer memory. Conversations are left alone -- a reply is a record of what was
said, and rewriting somebody's history is not a repair.

Nothing is deleted: an answer that is *only* thinking is left as it is and
reported, because there is no answer underneath it to keep and a blank cell is
not obviously better than an obvious mistake. Take a copy of the database
first; `--apply` writes in place.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.formatting import without_reasoning  # noqa: E402

# Each table, the column holding the JSON, and the fields in it worth cleaning.
STORES = [
    ("batch_answers", "batch_id", "payload", ("answer", "brief", "drafted")),
    ("run_answers", "run_id", "payload", ("answer", "brief", "drafted")),
]

MARKS = ("<think", "<thinking", "<reasoning")


def _marked(text: object) -> bool:
    return isinstance(text, str) and any(mark in text.lower() for mark in MARKS)


def clean(connection: sqlite3.Connection, *, apply: bool) -> tuple[int, int]:
    """Returns how many answers carry thinking, and how many are only thinking."""
    connection.row_factory = sqlite3.Row
    found = empty = 0

    for table, key, column, fields in STORES:
        rows = connection.execute(f"SELECT rowid, {key}, {column} FROM {table}").fetchall()
        for row in rows:
            try:
                payload = json.loads(row[column])
            except (TypeError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            changed = False
            for field in fields:
                text = payload.get(field)
                if not _marked(text):
                    continue
                found += 1
                cleaned = without_reasoning(text)
                if not cleaned:
                    empty += 1
                    print(f"  {table} {row[key]}: {field} is thinking with no answer after it — left alone")
                    continue
                print(f"  {table} {row[key]}: {field} {len(text) - len(cleaned)} characters of thinking")
                payload[field] = cleaned
                changed = True
            if changed and apply:
                connection.execute(
                    f"UPDATE {table} SET {column} = ? WHERE rowid = ?",
                    (json.dumps(payload, ensure_ascii=False), row["rowid"]),
                )

    remembered = connection.execute(
        "SELECT team_id, entry_id, answer FROM memory_entries"
    ).fetchall()
    for row in remembered:
        if not _marked(row["answer"]):
            continue
        found += 1
        cleaned = without_reasoning(row["answer"])
        if not cleaned:
            empty += 1
            print(f"  memory_entries {row['entry_id']}: thinking with no answer after it — left alone")
            continue
        print(f"  memory_entries {row['entry_id']}: {len(row['answer']) - len(cleaned)} characters of thinking")
        if apply:
            connection.execute(
                "UPDATE memory_entries SET answer = ? WHERE team_id = ? AND entry_id = ?",
                (cleaned, row["team_id"], row["entry_id"]),
            )

    if apply:
        connection.commit()
    return found, empty


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default="", help="the database (default: DB_PATH from the settings)")
    parser.add_argument("--apply", action="store_true", help="write the changes; otherwise only report")
    args = parser.parse_args()

    from src.config import settings

    path = Path(args.db) if args.db else settings.db_path
    if not path.is_file():
        print(f"No database at {path}")
        return 1

    print(f"{'Cleaning' if args.apply else 'Checking'} {path}")
    connection = sqlite3.connect(path)
    try:
        found, empty = clean(connection, apply=args.apply)
    finally:
        connection.close()

    if not found:
        print("No stored answer carries a model's thinking.")
        return 0
    print(f"\n{found} answer(s) carry thinking; {empty} of them are thinking and nothing else.")
    if not args.apply:
        print("Nothing was written. Re-run with --apply to clean them.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
