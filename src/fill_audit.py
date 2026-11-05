"""Which filled files may hold answers the review gate holds back (plan 029, TD-052, TD-053).

    python -m src.cli inspect fills [--team T] [--json]

Read-only. Two lists, from the event log and the answers as they are today:

- **Fills that wrote held answers.** Before plan 029 the Workbench's Fill sent
  `include_unreviewed: true` on every click and recorded `held_back=0`. A fill
  that recorded 0, of a questionnaire with an answer the gate holds today that
  was last saved at or before the fill, wrote that answer: certain. An answer
  saved after the fill was in a state nothing recorded, so it is counted as
  unknown, and so is an answer cleared after it. A fill of a questionnaire that
  is no longer on the server is listed as unknown rather than dropped. Since
  the fix, a fill records the gate's count and `include_unreviewed`, and which
  held answers "Write them in anyway" wrote (`written_anyway`), so that is
  listed from its own record.
- **Approvals withdrawn before plan 029.** Withdrawing an approval left the answer
  released (TD-053). Those still pass the gate today although the review's own
  rule (`verification.assess`: any reason, or a score at or under the threshold)
  would hold them, and every fill since wrote them.

The server keeps only the last filled copy of each questionnaire; what reached
a customer is the file the person downloaded.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src import batches, events
from src.config import settings
from src.selection import _has_answer, confirmed_by_a_person, ready_to_write


@dataclass
class HeldFill:
    """One fill that wrote, or may have written, answers the gate holds back."""

    filled_at: str
    batch_id: str
    source_name: str
    filled_by: str
    owner: str
    written: int
    held_back_recorded: int
    include_unreviewed: bool | None
    """None: recorded before plan 029, when a fill did not say."""
    written_anyway: list[str] | None = None
    """The held answers "Write them in anyway" wrote, by question id; None: not recorded (before plan 029's review)."""
    held_unchanged: list[str] = field(default_factory=list)
    """Questions held by the gate today and last saved at or before the fill: written held."""
    changed_since: list[str] = field(default_factory=list)
    """Answers saved or cleared after the fill: what they were at the time is not known."""
    gone: bool = False
    """The questionnaire is no longer on the server, so what the fill wrote cannot be read back."""

    @property
    def wrote_anyway(self) -> bool:
        """Whether the record says held answers went in on purpose."""
        if self.include_unreviewed is not True:
            return False
        return bool(self.written_anyway) if self.written_anyway is not None else self.held_back_recorded > 0


@dataclass
class Released:
    """An answer whose approval was withdrawn before plan 029 and which the gate now lets through."""

    batch_id: str
    source_name: str
    owner: str
    question_id: str
    question: str
    confidence: float
    reasons: list[str]
    withdrawn_at: str
    withdrawn_by: str


def held_fills(team_id: str) -> list[HeldFill]:
    """The team's fills that wrote answers the gate holds back: certain ones first, then unknown ones."""
    found: list[HeldFill] = []
    removed = _removed_at(team_id)
    for event in events.of_kind(team_id, events.FILE_FILLED):
        recorded = event.payload
        include = recorded.get("include_unreviewed")
        if recorded.get("held_back", 0) and include is not True:
            continue  # the gate held them back, and the record says so
        anyway = recorded.get("written_anyway")
        batch = batches.load(event.subject_id, team_id=team_id)
        fill = HeldFill(
            filled_at=event.created_at,
            batch_id=event.subject_id,
            source_name=batch.source_name if batch else "",
            filled_by=event.actor_email,
            owner=batch.actor_email if batch else "",
            written=int(recorded.get("written", 0)),
            held_back_recorded=int(recorded.get("held_back", 0)),
            include_unreviewed=include,
            written_anyway=[str(q) for q in anyway] if isinstance(anyway, list) else None,
            gone=batch is None,
        )
        if batch is None:
            if fill.wrote_anyway or (include is None and fill.written):
                found.append(fill)  # what it held cannot be read back: unknown, not dropped
            continue
        answered, edits, saved = batches.answers(batch.id), batches.edited_by(batch.id), batches.saved_at(batch.id)
        for question in batch.form.questions:
            result = answered.get(question.id)
            if result is None:
                # Cleared, or "Leave blank" taken back, after the fill: what it was then is not known.
                if removed.get((batch.id, question.id), "") > event.created_at:
                    fill.changed_since.append(question.id)
                continue
            if saved.get(question.id, "") > event.created_at:
                fill.changed_since.append(question.id)
            elif (
                _has_answer(result)
                and not question.skip
                and not ready_to_write(result, edits.get(question.id, ""))[0]
                and (fill.written_anyway is None or question.id in fill.written_anyway)
            ):
                fill.held_unchanged.append(question.id)
        if fill.held_unchanged or fill.wrote_anyway or (include is None and fill.changed_since and fill.written):
            found.append(fill)
    return sorted(found, key=lambda fill: (fill.gone, not (fill.held_unchanged or fill.wrote_anyway)))


def _removed_at(team_id: str) -> dict[tuple[str, str], str]:
    """When each answer was last removed (cleared, or "Leave blank" taken back), by questionnaire and question."""
    removed: dict[tuple[str, str], str] = {}
    for event in events.of_kind(team_id, events.ANSWER_EDITED):
        if event.payload.get("cleared") is True or event.payload.get("blanked") is False:
            removed[(event.subject_id, str(event.payload.get("question_id", "")))] = event.created_at
    return removed


def released_by_withdrawal(team_id: str, *, threshold: float | None = None) -> list[Released]:
    """Answers left released by a withdrawn approval, which the review's own rule would hold."""
    floor = settings.review_confidence_threshold if threshold is None else threshold
    found: list[Released] = []
    seen: set[tuple[str, str]] = set()
    for event in reversed(events.of_kind(team_id, events.ANSWER_EDITED)):  # the latest withdrawal of each
        question_id = str(event.payload.get("question_id", ""))
        if event.payload.get("approved") is not False or (event.subject_id, question_id) in seen:
            continue
        seen.add((event.subject_id, question_id))
        batch = batches.load(event.subject_id, team_id=team_id)
        question = next((q for q in batch.form.questions if q.id == question_id), None) if batch else None
        if batch is None or question is None or question.skip:
            continue
        result = batches.answers(batch.id).get(question_id)
        if result is None or not _has_answer(result):
            continue
        if confirmed_by_a_person(result, batches.edited_by(batch.id).get(question_id, "")):
            continue
        passes = not result.needs_review and result.confidence >= floor
        if passes and (result.review_reasons or result.confidence <= floor):
            found.append(
                Released(
                    batch_id=batch.id,
                    source_name=batch.source_name,
                    owner=batch.actor_email,
                    question_id=question_id,
                    question=question.text,
                    confidence=result.confidence,
                    reasons=list(result.review_reasons),
                    withdrawn_at=event.created_at,
                    withdrawn_by=event.actor_email,
                )
            )
    return sorted(found, key=lambda released: released.withdrawn_at)


def _when(stamp: str) -> str:
    return stamp[:16].replace("T", " ")


def _some(ids: list[str], shown: int = 8) -> str:
    return ", ".join(ids[:shown]) + (", ..." if len(ids) > shown else "")


def report(fills: list[HeldFill], released: list[Released]) -> list[str]:
    """The two lists as lines a person reads (UTC times)."""
    lines = [f"Fills that wrote answers the review gate holds back: {len(fills)}"]
    for fill in fills:
        how = "before the fix" if fill.include_unreviewed is None else "written anyway"
        if fill.include_unreviewed is False:
            how = "gate kept"
        elif fill.written_anyway is not None:
            how = f"{len(fill.written_anyway)} written anyway"
        lines.append(
            f"{_when(fill.filled_at)}  {fill.source_name or 'questionnaire no longer on the server'}"
            f"  (batch {fill.batch_id})  filled by {fill.filled_by}"
            f"  wrote {fill.written}  recorded held {fill.held_back_recorded}, {how}"
        )
        if fill.gone:
            lines.append("    the questionnaire is gone, so what this fill wrote is not known")
        if fill.held_unchanged:
            count = len(fill.held_unchanged)
            lines.append(f"    held today and unchanged since the fill: {count}  ({_some(fill.held_unchanged)})")
        if fill.changed_since:
            lines.append(f"    saved or cleared after the fill, state then unknown: {len(fill.changed_since)}")
    lines += ["", f"Approvals withdrawn before the fix, written as if confident: {len(released)}"]
    for answer in released:
        reasons = "; ".join(answer.reasons) or "no reason recorded"
        lines.append(
            f"{_when(answer.withdrawn_at)}  {answer.source_name}  (batch {answer.batch_id})  {answer.question_id}"
            f"  confidence {answer.confidence:.0%}  {reasons}"
        )
        lines.append(f"    {answer.question[:120]}")
    return lines
