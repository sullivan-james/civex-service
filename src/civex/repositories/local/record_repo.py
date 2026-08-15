from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import cast, func, literal, or_, String
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.orm import Session

from civex.db.models import Record, Schema, WorkflowJob
from civex.domain.dtos import RecordDTO
from civex.domain.exceptions import NotFoundError


def _coerce_json_value(v: str) -> Any:
    """Parse v as JSON so JSONB @> containment is type-correct (e.g. "30" → 30)."""
    try:
        return json.loads(v)
    except (json.JSONDecodeError, ValueError):
        return v


class LocalRecordRepository:
    def __init__(self, session: Session, is_postgres: bool = False) -> None:
        self._s = session
        self._pg = is_postgres

    def get_by_id(
        self, id: uuid.UUID, include_deleted: bool = False
    ) -> RecordDTO | None:
        q = self._s.query(Record).filter_by(id=id)
        if not include_deleted:
            q = q.filter(Record.deleted_at.is_(None))
        row = q.first()
        return _to_dto(row) if row else None

    def get_by_prefix(
        self, prefix: str, include_deleted: bool = False
    ) -> RecordDTO | None:
        try:
            uid = uuid.UUID(prefix)
            q = self._s.query(Record).filter(Record.id == uid)
        except ValueError:
            q = self._s.query(Record).filter(
                cast(Record.id, String).like(f"{prefix.lower()}%")
            )
        if not include_deleted:
            q = q.filter(Record.deleted_at.is_(None))
        row = q.first()
        return _to_dto(row) if row else None

    def list_all(self) -> list[RecordDTO]:
        rows = (
            self._s.query(Record)
            .filter(Record.deleted_at.is_(None))
            .order_by(Record.created_at)
            .all()
        )
        return [_to_dto(r) for r in rows]

    def list_deleted(self, dataset_id: uuid.UUID | None = None) -> list[RecordDTO]:
        q = self._s.query(Record).filter(Record.deleted_at.is_not(None))
        if dataset_id is not None:
            q = q.filter(Record.dataset_id == dataset_id)
        rows = q.order_by(Record.deleted_at.desc()).all()
        return [_to_dto(r) for r in rows]

    def list_by_dataset(self, dataset_id: uuid.UUID) -> list[RecordDTO]:
        rows = (
            self._s.query(Record)
            .filter_by(dataset_id=dataset_id)
            .filter(Record.deleted_at.is_(None))
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
        q = _base_query(
            self._s,
            dataset_id,
            schema_id,
            parent_record_id,
            field_filters,
            search,
            self._pg,
        )
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
        q = _base_query(
            self._s,
            dataset_id,
            schema_id,
            parent_record_id,
            field_filters,
            search,
            self._pg,
        )
        return q.count()

    def list_by_schema(
        self, schema_id: uuid.UUID, search: str | None = None, limit: int = 20
    ) -> list[RecordDTO]:
        q = self._s.query(Record).filter(
            Record.schema_id == schema_id, Record.deleted_at.is_(None)
        )
        if search:
            q = q.filter(
                or_(
                    cast(Record.data, String).ilike(f"%{search}%"),
                    cast(Record.id, String).ilike(f"{search}%"),
                )
            )
        rows = q.order_by(Record.created_at.desc()).limit(limit).all()
        return [_to_dto(r) for r in rows]

    def list_ids_by_schema_ids(self, schema_ids: list[uuid.UUID]) -> list[uuid.UUID]:
        if not schema_ids:
            return []
        rows = self._s.query(Record.id).filter(Record.schema_id.in_(schema_ids)).all()
        return [r[0] for r in rows]

    def list_children(
        self, parent_id: uuid.UUID, include_deleted: bool = False
    ) -> list[RecordDTO]:
        q = self._s.query(Record).filter_by(parent_record_id=parent_id)
        if not include_deleted:
            q = q.filter(Record.deleted_at.is_(None))
        return [_to_dto(r) for r in q.all()]

    def list_referencing(
        self,
        target_ids: list[uuid.UUID],
        reference_field_ids: list[uuid.UUID],
        reference_list_field_ids: list[uuid.UUID],
    ) -> list[RecordDTO]:
        """Records holding a `reference`/`reference_list` value that points at
        any of target_ids, keyed by field id (data is stored id-keyed, not
        name-keyed -- see RecordService._names_to_ids)."""
        if not target_ids or not (reference_field_ids or reference_list_field_ids):
            return []
        target_strs = [str(t) for t in target_ids]

        if self._pg:
            # @> containment: for a nested array value, {"k": ["a","b"]} @> {"k": ["a"]}
            # is true iff "a" appears in the array -- exactly the reference_list case.
            clauses = [
                Record.data.op("@>")(cast(literal(json.dumps({str(fid): t})), PG_JSONB))
                for fid in reference_field_ids
                for t in target_strs
            ] + [
                Record.data.op("@>")(
                    cast(literal(json.dumps({str(fid): [t]})), PG_JSONB)
                )
                for fid in reference_list_field_ids
                for t in target_strs
            ]
            rows = (
                self._s.query(Record)
                .filter(Record.deleted_at.is_(None))
                .filter(or_(*clauses))
                .all()
            )
            return [_to_dto(r) for r in rows]

        # SQLite has no JSONB containment operator -- scan and check in Python.
        # Acceptable for target dataset sizes (see CIVEX-169).
        target_set = set(target_strs)
        ref_ids = {str(fid) for fid in reference_field_ids}
        ref_list_ids = {str(fid) for fid in reference_list_field_ids}
        result = []
        for row in self._s.query(Record).filter(Record.deleted_at.is_(None)).all():
            data = row.data or {}
            hit = any(data.get(fid) in target_set for fid in ref_ids)
            if not hit:
                hit = any(
                    isinstance(data.get(fid), list) and target_set & set(data[fid])
                    for fid in ref_list_ids
                )
            if hit:
                result.append(_to_dto(row))
        return result

    def count_by_schema(self, dataset_id: uuid.UUID) -> dict[str, int]:
        rows = (
            self._s.query(Schema.name, func.count(Record.id))
            .join(Schema, Record.schema_id == Schema.id)
            .filter(Record.dataset_id == dataset_id, Record.deleted_at.is_(None))
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
        # search_vector is maintained by a Postgres trigger (CIVEX-173) so it
        # can't go stale on writes that don't go through this repo; unused on
        # SQLite (see models._TSVECTOR).
        row = Record(
            dataset_id=dataset_id,
            schema_id=schema_id,
            data=data,
            parent_record_id=parent_record_id,
        )
        self._s.add(row)
        self._s.flush()
        return _to_dto(row)

    def update(self, id: uuid.UUID, data: dict[str, Any]) -> RecordDTO:
        row = self._s.query(Record).filter_by(id=id).first()
        if row is None:
            raise NotFoundError(f"Record '{id}' not found")
        row.data = data
        self._s.flush()
        return _to_dto(row)

    def delete(self, id: uuid.UUID) -> None:
        row = self._s.query(Record).filter_by(id=id).first()
        if row and row.deleted_at is None:
            row.deleted_at = datetime.now(timezone.utc)
            self._s.flush()

    def restore(self, id: uuid.UUID) -> RecordDTO:
        row = self._s.query(Record).filter_by(id=id).first()
        if row is None:
            raise NotFoundError(f"Record '{id}' not found")
        row.deleted_at = None
        self._s.flush()
        return _to_dto(row)

    def purge(self, id: uuid.UUID) -> None:
        """Permanently remove a single (already soft-deleted) record and its
        workflow jobs. Descendant purging is the caller's job (RecordService
        mirrors the recursion it already does for delete())."""
        row = self._s.query(Record).filter_by(id=id).first()
        if row is None:
            return
        self._s.query(WorkflowJob).filter_by(record_id=id).delete(
            synchronize_session=False
        )
        self._s.delete(row)
        self._s.flush()


def _base_query(
    session: Session,
    dataset_id: uuid.UUID,
    schema_id: uuid.UUID | None,
    parent_record_id: uuid.UUID | None,
    field_filters: list[tuple[str, str]],
    search: str | None = None,
    is_postgres: bool = False,
):
    q = session.query(Record).filter(
        Record.dataset_id == dataset_id, Record.deleted_at.is_(None)
    )
    if schema_id is not None:
        q = q.filter(Record.schema_id == schema_id)
    if parent_record_id is not None:
        q = q.filter(Record.parent_record_id == parent_record_id)
    for key, value in field_filters:
        if is_postgres:
            # @> containment uses the GIN index on PostgreSQL.
            # _coerce_json_value converts "30" → 30 so numeric/bool fields match correctly.
            doc = json.dumps({key: _coerce_json_value(value)})
            q = q.filter(Record.data.op("@>")(cast(literal(doc), PG_JSONB)))
        else:
            # SQLite: json_extract (via .as_string()) returns the *unquoted* scalar
            # but preserves its storage class, so a numeric field would compare as
            # INTEGER 30 != TEXT '30'. Casting the extracted value to TEXT normalises
            # both strings and numbers to match the string filter value.
            # (Plain cast(data[key], String) would instead yield the JSON form '"S02"'.)
            q = q.filter(cast(Record.data[key].as_string(), String) == value)
    if search:
        if is_postgres:
            q = q.filter(
                Record.search_vector.op("@@")(func.plainto_tsquery("simple", search))
            )
        else:
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
        deleted_at=row.deleted_at,
    )
