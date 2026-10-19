"""Apply decided changes to the live answer memory: forget entries, move them between memories (plan 026).

    python -m scripts.memory_changes <changes.json> --by <email>            # what it would do
    python -m scripts.memory_changes <changes.json> --by <email> --apply    # do it, with the app stopped

The changes file names each entry and why:

    {"remove": [{"entry_id": "MEM-0519", "reason": "a routing note, not an answer"}],
     "move":   [{"entry_id": "MEM-0123", "product": "Ole5", "reason": "describes Ole5's hosting"}]}

These are the memory page's Forget and Move (`answer_memory.remove` and
`answer_memory.move`), recorded as the same events under the account of the
person who decided them, so the history reads as it would had they clicked.
A moved entry is compared again with its new neighbours the next time the app
sweeps the memory; this does not call the model itself.

The app must be stopped to apply. Both operations rewrite vectors, and two
processes writing one Chroma directory leave the server's in-memory index out
of step with the files on disk.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path

from pydantic import BaseModel, Field

from src import answer_memory, events, identity, products
from src.identity import User

SUBJECT = "memory_entry"
"""What the memory page's events say an entry is (`tools.SUBJECT_MEMORY`)."""


class Remove(BaseModel):
    entry_id: str
    reason: str = Field(min_length=3)


class Move(BaseModel):
    entry_id: str
    product: str = Field(description="A product's name; empty for the shared memory")
    reason: str = Field(min_length=3)


class Changes(BaseModel):
    remove: list[Remove] = []
    move: list[Move] = []


def app_running(port: int) -> bool:
    """Whether something is listening where the app serves."""
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def plan(changes: Changes, user: User) -> tuple[list[str], list[str]]:
    """(what would be done, why it cannot be) for these changes, without changing anything."""
    named = {p.name.casefold(): p for p in products.list_products(user.team_id)}
    steps: list[str] = []
    refused: list[str] = []
    for removal in changes.remove:
        entry = answer_memory.get(removal.entry_id, user.team_id)
        if entry is None:
            refused.append(f"{removal.entry_id}: not in the answer memory")
        else:
            steps.append(f"forget {removal.entry_id} ({removal.reason})")
    for move in changes.move:
        entry = answer_memory.get(move.entry_id, user.team_id)
        product = named.get(move.product.casefold()) if move.product else None
        if entry is None:
            refused.append(f"{move.entry_id}: not in the answer memory")
        elif move.product and product is None:
            refused.append(f"{move.entry_id}: no product {move.product!r} in team {user.team_id}")
        elif entry.product_id == (product.id if product else ""):
            refused.append(f"{move.entry_id}: already in {move.product or 'the shared memory'}")
        else:
            steps.append(f"move {move.entry_id} to {move.product or 'the shared memory'} ({move.reason})")
    return steps, refused


def apply(changes: Changes, user: User) -> int:
    """Make the changes and record them. Returns how many were made."""
    named = {p.name.casefold(): p.id for p in products.list_products(user.team_id)}
    made = 0
    for removal in changes.remove:
        if answer_memory.remove(removal.entry_id, user.team_id):
            events.record(user, events.MEMORY_REMOVED, subject_type=SUBJECT, subject_id=removal.entry_id,
                          reason=removal.reason, via="scripts.memory_changes")  # fmt: skip
            made += 1
    for move in changes.move:
        target = named[move.product.casefold()] if move.product else ""
        before = answer_memory.get(move.entry_id, user.team_id)
        moved = answer_memory.move(move.entry_id, target, user.team_id)
        if moved is not None and moved.product_id == target:
            # Where from, as the page records it: a product's delete counts the moves in from Shared (plan 027).
            events.record(user, events.MEMORY_EDITED, subject_type=SUBJECT, subject_id=move.entry_id,
                          moved_from=before.product_id if before else "", moved_to=target,
                          reason=move.reason, via="scripts.memory_changes")  # fmt: skip
            made += 1
    return made


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        prog="python -m scripts.memory_changes",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("changes", type=Path)
    parser.add_argument("--by", required=True, help="the account of the person who decided these changes")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--port", type=int, default=8000, help="where the app serves, to check it is stopped")
    args = parser.parse_args(argv)

    user = identity.find_user_any(args.by)
    if user is None:
        print(f"No account {args.by!r}.\n  FIX: pass --by the email of the person who decided these changes.")
        return 2
    changes = Changes.model_validate(json.loads(args.changes.read_text(encoding="utf-8")))
    steps, refused = plan(changes, user)
    for step in steps:
        print(f"  {step}")
    for reason in refused:
        print(f"  REFUSED {reason}")
    if refused:
        print(f"{len(refused)} change(s) cannot be made; nothing was changed.\n  FIX: correct the changes file.")
        return 1
    if not args.apply:
        print(f"{len(steps)} change(s) would be made. Run again with --apply, with the app stopped.")
        return 0
    if app_running(args.port):
        print(
            f"The app is answering on port {args.port}; nothing was changed.\n"
            "  FIX: stop the app first. Two processes writing the vector store at once can corrupt its index."
        )
        return 1
    made = apply(changes, user)
    print(f"{made} of {len(steps)} change(s) made, recorded under {user.email}.")
    return 0 if made == len(steps) else 1


if __name__ == "__main__":
    raise SystemExit(main())
