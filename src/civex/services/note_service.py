"""Notes people leave on records (`civex.domain.review`).

A note belongs to one record and is written, resolved and deleted by anyone who
may write records in that record's collection; only its author may change its
words. Every change is a history entry about the note (kind `note`), so notes
show in Activity and sync. A deleted record's notes are hidden with it (nothing
is stamped on them, so they come back with it) and a record deleted for good
takes them, and their history, with it (the foreign key and
`AuditRepository.forget_records`).
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime, timezone
from typing import Any

from civex.domain import permissions
from civex.domain import review as review_rules
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
    """Notes not yet resolved among the records a query lists."""

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
        """A live record's notes, oldest first (resolved ones too unless
        `include_resolved` is false)."""
        record = self._record(record_id)
        self._permissions.require(permissions.READ, record.dataset_id)
        return self._repo.for_record(record.id, include_resolved)

    def get(self, note_id: str) -> NoteDTO:
        note = self._repo.get_by_prefix(note_id)
        if note is None or note.deleted_at is not None:
            raise NotFoundError(f"Note '{note_id}' not found")
        self._permissions.require(
            permissions.READ, self._record(str(note.record_id)).dataset_id
        )
        return note

    def open_notes(self, query: RecordQuery) -> OpenNotesDTO:
        """How many notes are not yet resolved, and on how many records, among
        the records `query` lists. One query whatever the size."""
        self._permissions.require(permissions.READ)
        notes, records = self._records.count_open_notes(self._resolve(query))
        return OpenNotesDTO(notes=notes, records=records)

    # -- writing ---------------------------------------------------------------

    def add(self, record_id: str, body: str) -> NoteDTO:
        """Leave a note on a live record, as this person."""
        record = self._record(record_id)
        self._permissions.require(permissions.WRITE_RECORDS, record.dataset_id)
        note = self._repo.create(record.id, review_rules.check_body(body), self._actor)
        self._log("create", None, note)
        return note

    def edit(self, note_id: str, body: str) -> NoteDTO:
        """Change a note's words. Only its author may."""
        note, _ = self._writable(note_id)
        if note.author != self._actor:
            raise NotAllowedError(
                f"Only {note.author or 'whoever wrote it'} can change the words "
                "of this note: reply with a note of your own"
            )
        text = review_rules.check_body(body)
        if text == note.body:
            return note
        after = self._repo.update(
            note.id, body=text, edited_at=datetime.now(timezone.utc)
        )
        self._log("update", note, after)
        return after

    def resolve(self, note_id: str, resolved: bool = True) -> NoteDTO:
        """Mark a note resolved (dealt with), or open again."""
        note, _ = self._writable(note_id)
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
        """Delete a note (it stays in history, and can be restored)."""
        note, _ = self._writable(note_id)
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
        """Bring back a deleted note on a live record."""
        note = self._repo.get_by_prefix(note_id)
        if note is None:
            raise NotFoundError(f"Note '{note_id}' not found")
        if note.deleted_at is None:
            return note
        record = self._record(str(note.record_id))
        self._permissions.require(permissions.WRITE_RECORDS, record.dataset_id)
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
            review_rules.check_body(state.get("body"))
        record = self._records.get_by_id(record_id, include_deleted=True)
        if record is None:
            raise ValidationError("The record the note is on is not on the server")
        return record.dataset_id

    # -- helpers ---------------------------------------------------------------

    def _record(self, record_id: str) -> RecordDTO:
        record = self._records.get_by_prefix(record_id)
        if record is None:
            raise NotFoundError(f"Record '{record_id}' not found")
        return record

    def _writable(self, note_id: str) -> tuple[NoteDTO, RecordDTO]:
        note = self._repo.get_by_prefix(note_id)
        if note is None or note.deleted_at is not None:
            raise NotFoundError(f"Note '{note_id}' not found")
        record = self._record(str(note.record_id))
        self._permissions.require(permissions.WRITE_RECORDS, record.dataset_id)
        return note, record

    def _log(self, action: str, before: NoteDTO | None, after: NoteDTO) -> None:
        if self._audit is not None:
            self._audit.log_change(
                action,
                "note",
                after.id,
                before.to_dict() if before else None,
                after.to_dict(),
            )
