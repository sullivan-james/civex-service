"""Notes people leave on records (`civex.domain.notes`).

A note belongs to one record and is written, resolved and deleted by anyone who
may write records in that record's collection; only its author may change its
words. Every change is a history entry about the note (kind `note`), so notes
show in Activity and sync. A deleted record's notes are hidden with it (nothing
is stamped on them, so they come back with it) and a record deleted for good
takes them, and their history, with it (the foreign key and
`AuditRepository.forget_records`).

Notes are threaded, one level deep: a note on the record starts a thread and
`reply` adds to it (a reply to a reply joins the same thread). A thread is
resolved or reopened as a whole (on its first note), and a reply to a resolved
thread opens it again, since the conversation has started again. A reply is
deleted and restored by itself; deleting a thread's first note hides the
thread, and restoring it brings back its replies (nothing is stamped on them,
so a reply deleted by itself earlier stays deleted).
"""

from __future__ import annotations

import contextlib
import dataclasses
import uuid
from datetime import datetime, timezone
from typing import Any

from civex.domain import permissions
from civex.domain import notes as note_rules
from civex.domain.dtos import NoteDTO, RecordDTO
from civex.domain.exceptions import NotAllowedError, NotFoundError, ValidationError
from civex.domain.permissions import EVERYTHING, Permissions
from civex.domain.query import RecordQuery
from civex.repositories.protocols import (
    AuditRepository,
    NoteRepository,
    RecordRepository,
)


@dataclasses.dataclass
class OpenNotesDTO:
    """Threads not yet resolved among the records a query lists (a note and
    its replies count once)."""

    notes: int
    records: int

    def to_dict(self) -> dict[str, Any]:
        return {"notes": self.notes, "records": self.records}


class NoteService:
    def __init__(
        self,
        repo: NoteRepository,
        records: RecordRepository,
        resolve: Any,
        audit_repo: AuditRepository | None = None,
        permissions: Permissions = EVERYTHING,
        actor: str | None = None,
    ) -> None:
        self._repo = repo
        self._records = records
        # RecordService.resolve: a query's names to ids, for `open_notes`.
        self._resolve = resolve
        self._audit = audit_repo
        self._permissions = permissions
        self._actor = actor

    # -- reading ---------------------------------------------------------------

    def notes(self, record_id: str, include_resolved: bool = True) -> list[NoteDTO]:
        """A live record's threads, oldest first, each with its replies in
        `replies`, oldest first (resolved threads too unless `include_resolved`
        is false). One query for every thread and reply."""
        record = self._record(record_id)
        self._permissions.require(permissions.READ, record.dataset_id)
        return self._repo.for_record(record.id, include_resolved)

    def get(self, note_id: str) -> NoteDTO:
        note, _, record = self._live(note_id)
        self._permissions.require(permissions.READ, record.dataset_id)
        return note

    def open_notes(self, query: RecordQuery) -> OpenNotesDTO:
        """How many threads are not yet resolved, and on how many records,
        among the records `query` lists. One query whatever the size."""
        self._permissions.require_somewhere(permissions.READ)
        notes, records = self._records.count_open_notes(self._resolve(query))
        return OpenNotesDTO(notes=notes, records=records)

    # -- writing ---------------------------------------------------------------

    def add(self, record_id: str, body: str) -> NoteDTO:
        """Leave a note on a live record, as this person."""
        record = self._record(record_id)
        self._permissions.require(permissions.NOTES, record.dataset_id)
        note = self._repo.create(record.id, note_rules.check_body(body), self._actor)
        self._log("create", None, note)
        return note

    def reply(self, note_id: str, body: str) -> NoteDTO:
        """Reply in the thread `note_id` is in (the note that starts it, or any
        reply in it), as this person. A resolved thread opens again; the reply
        and the reopening are one action."""
        _, thread, _ = self._writable(note_id)
        text = note_rules.check_body(body)
        with self._one_action():
            reply = self._repo.create(
                thread.record_id, text, self._actor, thread_id=thread.id
            )
            self._log("create", None, reply)
            if thread.resolved_at is not None:
                self._log(
                    "update",
                    thread,
                    self._repo.update(thread.id, resolved_at=None, resolved_by=None),
                )
        return reply

    def edit(self, note_id: str, body: str) -> NoteDTO:
        """Change a note's or a reply's words. Only its author may."""
        note, _, _ = self._writable(note_id)
        if note.author != self._actor:
            raise NotAllowedError(
                f"Only {note.author or 'whoever wrote it'} can change the words "
                "of this note: reply instead"
            )
        text = note_rules.check_body(body)
        if text == note.body:
            return note
        after = self._repo.update(
            note.id, body=text, edited_at=datetime.now(timezone.utc)
        )
        self._log("update", note, after)
        return after

    def resolve(self, note_id: str, resolved: bool = True) -> NoteDTO:
        """Mark the thread `note_id` is in resolved (dealt with), or open it
        again. Answers the thread's first note."""
        _, note, _ = self._writable(note_id)
        if (note.resolved_at is not None) == resolved:
            return note
        after = self._repo.update(
            note.id,
            resolved_at=datetime.now(timezone.utc) if resolved else None,
            resolved_by=self._actor if resolved else None,
        )
        self._log("update", note, after)
        return after

    def delete(self, note_id: str) -> NoteDTO:
        """Delete a note or a reply (it stays in history, and can be
        restored). A thread's first note hides its replies with it."""
        note, _, _ = self._writable(note_id)
        after = self._repo.update(note.id, deleted_at=datetime.now(timezone.utc))
        if self._audit is not None:
            self._audit.log_change(
                "delete",
                "note",
                note.id,
                note.to_dict(),
                None,
                timestamp=after.deleted_at,
            )
        return after

    def restore(self, note_id: str) -> NoteDTO:
        """Bring back a deleted note on a live record (a thread's first note
        brings back its replies but those deleted by themselves). A reply comes
        back only into a thread that is there."""
        note = self._repo.get_by_prefix(note_id)
        if note is None:
            raise NotFoundError(f"Note '{note_id}' not found")
        if note.deleted_at is None:
            return note
        record = self._record(str(note.record_id))
        self._permissions.require(permissions.NOTES, record.dataset_id)
        if note.thread_id is not None:
            thread = self._repo.get(note.thread_id)
            if thread is None or thread.deleted_at is not None:
                raise ValidationError(
                    "The note this replies to is deleted: restore it first"
                )
        after = self._repo.update(note.id, deleted_at=None)
        self._log("restore", note, after)
        return after

    # -- for sync --------------------------------------------------------------

    def collection_of(self, state: dict[str, Any]) -> uuid.UUID:
        """The collection of the record a note sent by another device is on,
        refusing one that can't be taken: no such record here, or text a
        person's note couldn't have."""
        try:
            record_id = uuid.UUID(str(state["record_id"]))
        except (KeyError, ValueError):
            raise ValidationError("The note's record is not valid") from None
        if not state.get("deleted_at"):
            note_rules.check_body(state.get("body"))
        record = self._records.get_by_id(record_id, include_deleted=True)
        if record is None:
            raise ValidationError("The record the note is on is not on the server")
        if state.get("thread_id"):
            try:
                thread = self._repo.get(uuid.UUID(str(state["thread_id"])))
            except ValueError:
                thread = None
            if (
                thread is None
                or thread.record_id != record_id
                or thread.thread_id is not None
            ):
                raise ValidationError(
                    "The note this replies to is not on the server, or not on "
                    "the same record"
                )
        return record.dataset_id

    # -- helpers ---------------------------------------------------------------

    def _record(self, record_id: str) -> RecordDTO:
        record = self._records.get_by_prefix(record_id)
        if record is None:
            raise NotFoundError(f"Record '{record_id}' not found")
        return record

    def _live(self, note_id: str) -> tuple[NoteDTO, NoteDTO, RecordDTO]:
        """(the note, the note that starts its thread (itself for one that
        starts it), its record) for a note that can be seen: not deleted, and
        not in a thread whose first note is."""
        note = self._repo.get_by_prefix(note_id)
        if note is None or note.deleted_at is not None:
            raise NotFoundError(f"Note '{note_id}' not found")
        thread = note if note.thread_id is None else self._repo.get(note.thread_id)
        if thread is None or thread.deleted_at is not None:
            raise NotFoundError(f"Note '{note_id}' not found")
        return note, thread, self._record(str(note.record_id))

    def _writable(self, note_id: str) -> tuple[NoteDTO, NoteDTO, RecordDTO]:
        note, thread, record = self._live(note_id)
        self._permissions.require(permissions.NOTES, record.dataset_id)
        return note, thread, record

    def _one_action(self) -> Any:
        return (
            self._audit.operation()
            if self._audit is not None
            else contextlib.nullcontext()
        )

    def _log(self, action: str, before: NoteDTO | None, after: NoteDTO) -> None:
        if self._audit is not None:
            self._audit.log_change(
                action,
                "note",
                after.id,
                before.to_dict() if before else None,
                after.to_dict(),
            )
