"""Curating records as a team: a record's review status and the notes left on it.

A record's **review** is one small value (`records.review`): whether it needs a
check or has been checked, by whom and when, or nothing (None, shown as "Not
reviewed"). It is part of the record, so it is in the record's history and
syncs with it, but it is not one of its values: setting it is not an edit of the
record (`updated_at` stays), fires no workflow and is never a conflict: the
latest person to look at a record decides (`merge.LATEST_WINS`).

A **note** is a short plain text about one record ("value looks off, re-check
the calibration"), with who wrote it and when, and whether it has been
resolved. Notes are a kind of their own (`note`, history and sync like a saved
filter's), stay with their record (a deleted record's notes are hidden with it
and come back with it; a record deleted for good takes them, and their history,
with it).

Pure: the vocabulary and its checks. `RecordService.set_review` and
`NoteService` store them, ask permission and write history.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from civex.domain.exceptions import ValidationError

NEEDS_CHECK = "needs_check"
CHECKED = "checked"
#: Not reviewed: what a record with no review holds (stored as None).
NONE = "none"
STATUSES = (NEEDS_CHECK, CHECKED)
#: Every value a person may set or filter by, `NONE` clearing it.
CHOICES = (NONE, NEEDS_CHECK, CHECKED)
#: The words the app, the CLI and history use.
LABELS = {NONE: "Not reviewed", NEEDS_CHECK: "Needs a check", CHECKED: "Checked"}

#: The longest note, in characters.
NOTE_MAX_LENGTH = 4000

#: The filter tree's names for these (a field's name can't start with `@`, so
#: they never shadow a field): the record's review status (`none`,
#: `needs_check`, `checked`) and whether it has notes not yet resolved.
REVIEW_FILTER = "@review"
OPEN_NOTES_FILTER = "@open_notes"
FILTERS = (REVIEW_FILTER, OPEN_NOTES_FILTER)
#: The operators each takes.
FILTER_OPERATORS = {
    REVIEW_FILTER: ("eq", "ne", "in"),
    OPEN_NOTES_FILTER: ("eq",),
}


def status_of(review: dict[str, Any] | None) -> str:
    """A stored review's status: `NONE` when there is none."""
    return (review or {}).get("status") or NONE


def check_status(status: str) -> str:
    """A status a person may set, or a `ValidationError` naming the choices."""
    if status not in CHOICES:
        raise ValidationError(
            f"Unknown review status '{status}'. Choose one of: {', '.join(CHOICES)}"
        )
    return status


def review_value(status: str, by: str | None, at: datetime) -> dict[str, Any] | None:
    """What a record stores for `status` set by `by` at `at` (None clears it)."""
    check_status(status)
    if status == NONE:
        return None
    return {"status": status, "by": by, "at": at.isoformat()}


def check_review(value: Any) -> None:
    """A stored review's shape: None, or {status, by, at} with a known status.
    Held to it when one arrives over sync, like any value a device sends."""
    if value is None:
        return
    if not isinstance(value, dict) or set(value) - {"status", "by", "at"}:
        raise ValidationError("A review is {status, by, at}")
    if value.get("status") not in STATUSES:
        raise ValidationError(f"Unknown review status '{value.get('status')}'")
    if value.get("by") is not None and not isinstance(value["by"], str):
        raise ValidationError("A review's 'by' is a name")
    try:
        datetime.fromisoformat(str(value.get("at")))
    except ValueError as e:
        raise ValidationError("A review's 'at' is a time") from e


def check_body(body: Any) -> str:
    """A note's text, trimmed: not empty and at most `NOTE_MAX_LENGTH`."""
    if not isinstance(body, str):
        raise ValidationError("A note is text")
    text = body.strip()
    if not text:
        raise ValidationError("A note can't be empty")
    if len(text) > NOTE_MAX_LENGTH:
        raise ValidationError(
            f"A note can be at most {NOTE_MAX_LENGTH} characters "
            f"(this one is {len(text)})"
        )
    return text
