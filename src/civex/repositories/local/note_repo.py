from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from civex.db.models import RecordNote
from civex.domain.dtos import NoteDTO
from civex.repositories.local._ids import prefix_span


class LocalNoteRepository:
    """Notes left on records (`civex.domain.review`). Plain storage: the
    rules, permissions and history are `NoteService`'s."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, id: uuid.UUID) -> NoteDTO | None:
        row = self._s.get(RecordNote, id)
        return _to_dto(row) if row is not None else None

    def get_by_prefix(self, prefix: str) -> NoteDTO | None:
        """A note by its id or the start of it (at least 4 hex digits), when
        exactly one matches."""
        try:
            return self.get(uuid.UUID(prefix))
        except ValueError:
            pass
        span = prefix_span(prefix)
        if span is None or len(prefix.replace("-", "")) < 4:
            return None
        rows = (
            self._s.query(RecordNote)
            .filter(RecordNote.id.between(*span))
            .limit(2)
            .all()
        )
        return _to_dto(rows[0]) if len(rows) == 1 else None

    def for_record(
        self, record_id: uuid.UUID, include_resolved: bool = True
    ) -> list[NoteDTO]:
        """A record's live notes, oldest first."""
        q = self._s.query(RecordNote).filter(
            RecordNote.record_id == record_id, RecordNote.deleted_at.is_(None)
        )
        if not include_resolved:
            q = q.filter(RecordNote.resolved_at.is_(None))
        return [_to_dto(r) for r in q.order_by(RecordNote.created_at, RecordNote.id)]

    def create(
        self,
        record_id: uuid.UUID,
        body: str,
        author: str | None,
        id: uuid.UUID | None = None,
    ) -> NoteDTO:
        row = RecordNote(
            id=id or uuid.uuid4(),
            record_id=record_id,
            body=body,
            author=author,
            created_at=datetime.now(timezone.utc),
        )
        self._s.add(row)
        self._s.flush()
        return _to_dto(row)

    def update(self, id: uuid.UUID, **values: Any) -> NoteDTO:
        """Set these columns (body, edited_at, resolved_at, resolved_by,
        deleted_at) on the note."""
        row = self._s.get(RecordNote, id)
        if row is None:
            raise KeyError(id)
        for name, value in values.items():
            setattr(row, name, value)
        self._s.flush()
        return _to_dto(row)


def _to_dto(row: RecordNote) -> NoteDTO:
    return NoteDTO(
        id=row.id,
        record_id=row.record_id,
        body=row.body,
        author=row.author,
        created_at=row.created_at,
        edited_at=row.edited_at,
        resolved_at=row.resolved_at,
        resolved_by=row.resolved_by,
        deleted_at=row.deleted_at,
    )
