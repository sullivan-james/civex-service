from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import cast, func, String
from sqlalchemy.orm import Session

from civex.db.models import Record, Schema
from civex.domain.dtos import RecordDTO


class LocalRecordRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get_by_id(self, id: uuid.UUID) -> RecordDTO | None:
        row = self._s.query(Record).filter_by(id=id).first()
        return _to_dto(row) if row else None

    def get_by_prefix(self, prefix: str) -> RecordDTO | None:
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

    def list_filtered(
        self,
        dataset_id: uuid.UUID,
        schema_id: uuid.UUID | None,
        parent_record_id: uuid.UUID | None,
        field_filters: list[tuple[str, str]],
        search: str | None,
        offset: int,
        limit: int,
    ) -> list[RecordDTO]:
        q = _base_query(self._s, dataset_id, schema_id, parent_record_id, field_filters, search)
        rows = q.order_by(Record.created_at).offset(offset).limit(limit).all()
        return [_to_dto(r) for r in rows]

    def count(
        self,
        dataset_id: uuid.UUID,
        schema_id: uuid.UUID | None,
        parent_record_id: uuid.UUID | None,
        field_filters: list[tuple[str, str]],
        search: str | None,
    ) -> int:
        q = _base_query(self._s, dataset_id, schema_id, parent_record_id, field_filters, search)
        return q.count()

    def count_by_schema(self, dataset_id: uuid.UUID) -> dict[str, int]:
        rows = (
            self._s.query(Schema.name, func.count(Record.id))
            .join(Schema, Record.schema_id == Schema.id)
            .filter(Record.dataset_id == dataset_id)
            .group_by(Schema.name)
            .all()
        )
        return {name: count for name, count in rows}

    def create(
        self,
        dataset_id: uuid.UUID,
        schema_id: uuid.UUID,
        data: dict[str, Any],
        parent_record_id: uuid.UUID | None = None,
    ) -> RecordDTO:
        row = Record(dataset_id=dataset_id, schema_id=schema_id, data=data, parent_record_id=parent_record_id)
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


def _base_query(
    session: Session,
    dataset_id: uuid.UUID,
    schema_id: uuid.UUID | None,
    parent_record_id: uuid.UUID | None,
    field_filters: list[tuple[str, str]],
    search: str | None = None,
):
    q = session.query(Record).filter(Record.dataset_id == dataset_id)
    if schema_id is not None:
        q = q.filter(Record.schema_id == schema_id)
    if parent_record_id is not None:
        q = q.filter(Record.parent_record_id == parent_record_id)
    for key, value in field_filters:
        # cast(data[key], String) compiles to:
        #   SQLite:     CAST(json_extract(data, '$.key') AS VARCHAR)
        #   PostgreSQL: CAST(data ->> 'key' AS VARCHAR)
        q = q.filter(cast(Record.data[key], String) == value)
    if search:
        # Full-text search across the entire JSON data blob.
        # ilike compiles to LOWER(col) LIKE LOWER(pattern) on SQLite,
        # and col ILIKE pattern on PostgreSQL.
        q = q.filter(cast(Record.data, String).ilike(f"%{search}%"))
    return q


def _to_dto(row: Record) -> RecordDTO:
    return RecordDTO(
        id=row.id,
        dataset_id=row.dataset_id,
        schema_id=row.schema_id,
        schema_name=row.schema.name if row.schema else "unknown",
        parent_record_id=row.parent_record_id,
        data=row.data or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
