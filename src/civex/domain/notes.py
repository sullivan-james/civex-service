"""Notes people leave on records, and the threads they make.

A **note** is a short plain text about one record ("value looks off, re-check
the calibration"), with who wrote it and when. A note on the record starts a
**thread** and others reply in it (one level: a reply to a reply joins the same
thread); a thread is resolved or opened again as a whole. Notes are a kind of
their own (`note`, history and sync like a saved filter's) and stay with their
record (a deleted record's notes are hidden with it and come back with it; a
record deleted for good takes them, and their history, with it).

What is open is found with the records' own filter: `@open_notes` (true or
false) is whether a record has a thread not yet resolved, and the explorer's
column of that name shows how many and the latest one's first line.

Pure: the vocabulary and its checks. `NoteService` stores notes, asks
permission and writes history.
"""

from __future__ import annotations

from typing import Any

from civex.domain.exceptions import ValidationError

#: The longest note, in characters.
NOTE_MAX_LENGTH = 4000
#: The longest first line a list shows of a record's latest open thread.
FIRST_LINE_MAX = 120

#: The filter tree's and the explorer's name for whether a record has threads
#: not yet resolved (a field's name can't start with `@`, so it never shadows
#: a field).
OPEN_NOTES_FILTER = "@open_notes"
#: The operators it takes.
FILTER_OPERATORS = ("eq",)


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


def first_line(body: str) -> str:
    """A note's first line, cut to `FIRST_LINE_MAX` characters (with an
    ellipsis when cut): what a list shows of it."""
    line = body.strip().split("\n", 1)[0].strip()
    if len(line) > FIRST_LINE_MAX:
        return line[: FIRST_LINE_MAX - 1].rstrip() + "…"
    return line
