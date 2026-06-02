from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import cast, String
from sqlalchemy.orm import Session

from civex.db.models import Record
from civex.domain.dtos import RecordDTO


class LocalRecordRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get_by_id(self, id: uuid.UUID) -> RecordDTO | None:
        row = self._s.query(Record).filter_by(id=id).first()
        return _to_dto(row) if row else None

    def get_by_prefix(self, prefix: str) -> RecordDTO | None:
        """
        Try exact UUID parse first (index hit on PostgreSQL native UUID type),
        then fall back to a text-cast prefix match.
        """
        try:
            uid = uuid.UUID(prefix)
            row = self._s.query(Record).filter(Record.id == uid).first()
        except ValueError:
            row = (
                self._s.query(Record)
                .filter(cast(Record.id, String).like(f"{prefix.lower()}%"))
                .first()
            )
        return _to_dto(row) if row else None

    def list_by_dataset(self, dataset_id: uuid.UUID) -> list[RecordDTO]:
        rows = (
            self._s.query(Record)
            .filter_by(dataset_id=dataset_id)
            .order_by(Record.created_at)
            .all()
        )
        return [_to_dto(r) for r in rows]

    def create(self, dataset_id: uuid.UUID, data: dict[str, Any]) -> RecordDTO:
        row = Record(dataset_id=dataset_id, data=data)
        self._s.add(row)
        self._s.flush()
        return _to_dto(row)

    def update(self, id: uuid.UUID, data: dict[str, Any]) -> RecordDTO:
        row = self._s.query(Record).filter_by(id=id).first()
        row.data = data
        self._s.flush()
        return _to_dto(row)

    def delete(self, id: uuid.UUID) -> None:
        row = self._s.query(Record).filter_by(id=id).first()
        if row:
            self._s.delete(row)
            self._s.flush()


def _to_dto(row: Record) -> RecordDTO:
    return RecordDTO(
        id=row.id,
        dataset_id=row.dataset_id,
        data=row.data or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
