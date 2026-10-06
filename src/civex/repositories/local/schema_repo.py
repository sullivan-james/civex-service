from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import nulls_last, select
from sqlalchemy.orm import Session, joinedload, selectinload

from civex.repositories.local._jobs import bulk_delete_jobs
from civex.db.models import Field, Record, Schema, View, WorkflowJob
from civex.domain.dtos import FieldDTO, SchemaDTO
from civex.domain.exceptions import NotFoundError


class LocalSchemaRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_by_name(self, name: str, include_deleted: bool = False) -> SchemaDTO | None:
        q = (
            self._s.query(Schema)
            .options(joinedload(Schema.fields))
            .filter_by(name=name)
        )
        if not include_deleted:
            q = q.filter(Schema.deleted_at.is_(None))
        row = q.first()
        return _schema_to_dto(row) if row else None

    def get_by_id(
        self, id: uuid.UUID, include_deleted: bool = False
    ) -> SchemaDTO | None:
        q = self._s.query(Schema).options(joinedload(Schema.fields)).filter_by(id=id)
        if not include_deleted:
            q = q.filter(Schema.deleted_at.is_(None))
        row = q.first()
        return _schema_to_dto(row) if row else None

    def list_all(self) -> list[SchemaDTO]:
        return [
            _schema_to_dto(r)
            for r in self._s.query(Schema)
            .options(selectinload(Schema.fields))
            .filter(Schema.deleted_at.is_(None))
            .order_by(Schema.created_at)
            .all()
        ]

    def list_deleted(self) -> list[SchemaDTO]:
        return [
            _schema_to_dto(r)
            for r in self._s.query(Schema)
            .options(selectinload(Schema.fields))
            .filter(Schema.deleted_at.is_not(None))
            .order_by(Schema.deleted_at.desc())
            .all()
        ]

    def get_fields(self, schema_id: uuid.UUID) -> list[FieldDTO]:
        rows = (
            self._s.query(Field)
            .filter_by(schema_id=schema_id)
            .filter(Field.deleted_at.is_(None))
            .order_by(nulls_last(Field.position), Field.created_at)
            .all()
        )
        return [_field_to_dto(r) for r in rows]

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def create(
        self,
        name: str,
        description: str | None,
        parent_id: uuid.UUID | None,
        label: str | None = None,
    ) -> SchemaDTO:
        row = Schema(
            name=name, label=label, description=description, parent_id=parent_id
        )
        self._s.add(row)
        self._s.flush()
        return _schema_to_dto(row)

    _SENTINEL = object()

    def update(
        self,
        id: uuid.UUID,
        name: str | None,
        description: str | None,
        display_template=_SENTINEL,
        label=_SENTINEL,
        unique_keys=_SENTINEL,
    ) -> SchemaDTO:
        row = self._s.query(Schema).filter_by(id=id).first()
        if row is None:
            raise NotFoundError(f"Schema '{id}' not found")
        if name is not None:
            row.name = name
        if description is not None:
            row.description = description
        if display_template is not self._SENTINEL:
            row.display_template = display_template or None  # None/"" clears it
        if label is not self._SENTINEL:
            row.label = label or None  # None/"" reverts to the derived label
        if unique_keys is not self._SENTINEL:
            row.unique_keys = unique_keys or None
        self._s.flush()
        return _schema_to_dto(row)

    def delete(self, id: uuid.UUID, stamp: datetime | None = None) -> None:
        """Soft-delete: mark the schema deleted and cascade to every record
        typed by it (across every collection) so it doesn't silently orphan
        its own records. Does not touch records of other schemas that hang
        off a now-hidden record via parent_record_id -- those stay visible,
        pointing at a soft-deleted parent, until it's restored or that
        record is individually restored too."""
        row = self._s.query(Schema).filter_by(id=id).first()
        if row is None or row.deleted_at is not None:
            return
        now = stamp or datetime.now(timezone.utc)
        row.deleted_at = now
        # A delete is not an edit: the records keep the date they were last
        # changed (and so every copy of a synced project agrees on it).
        self._s.query(Record).filter(
            Record.schema_id == id, Record.deleted_at.is_(None)
        ).update(
            {"deleted_at": now, "updated_at": Record.updated_at},
            synchronize_session=False,
        )
        self._s.flush()

    def restore(self, id: uuid.UUID) -> SchemaDTO:
        """Undo delete(): clears the schema's deleted_at and restores the
        records deleted *with* it -- those stamped with the same moment. A
        record deleted on its own beforehand stays in Recently Deleted."""
        row = self._s.query(Schema).filter_by(id=id).first()
        if row is None:
            raise NotFoundError(f"Schema '{id}' not found")
        cascade = self._cascade_query(id, row.deleted_at)
        row.deleted_at = None
        if cascade is not None:
            cascade.update(
                {"deleted_at": None, "updated_at": Record.updated_at},
                synchronize_session=False,
            )
        self._s.flush()
        return _schema_to_dto(row)

    def cascade_count(self, id: uuid.UUID) -> int:
        """How many records restoring this deleted schema would bring back."""
        row = self._s.query(Schema).filter_by(id=id).first()
        cascade = self._cascade_query(id, row.deleted_at) if row else None
        return cascade.count() if cascade is not None else 0

    def _cascade_query(self, id: uuid.UUID, deleted_at: datetime | None):
        if deleted_at is None:
            return None
        return self._s.query(Record).filter(
            Record.schema_id == id, Record.deleted_at == deleted_at
        )

    def purge(self, id: uuid.UUID) -> None:
        """Permanently remove a soft-deleted schema: its fields (ORM
        cascade), every view defined against it, every record it typed,
        those records' workflow jobs, and parent_record_id links from other
        records pointing at them."""
        row = self._s.query(Schema).filter_by(id=id).first()
        if row is None:
            return
        self._s.query(View).filter_by(schema_id=id).delete(synchronize_session=False)
        # The schema's records as a subquery, not a list of ids pulled into
        # Python -- a large schema would otherwise be a huge IN (...) (and past
        # SQLite's bound-variable limit, an error).
        typed = select(Record.id).where(Record.schema_id == id)
        self._s.query(Record).filter(Record.parent_record_id.in_(typed)).update(
            {"parent_record_id": None}, synchronize_session=False
        )
        bulk_delete_jobs(self._s, WorkflowJob.record_id.in_(typed))
        self._s.query(Record).filter_by(schema_id=id).delete(synchronize_session=False)
        self._s.delete(row)  # cascades to Field rows via ORM relationship
        self._s.flush()

    def add_field(
        self,
        schema_id: uuid.UUID,
        name: str,
        dtype: str,
        required: bool,
        restrictions: dict[str, Any],
        default_value: Any = None,
        position: int | None = None,
        label: str | None = None,
    ) -> FieldDTO:
        row = Field(
            schema_id=schema_id,
            name=name,
            label=label,
            dtype=dtype,
            required=required,
            restrictions=restrictions,
            default_value=default_value,
            position=position,
        )
        self._s.add(row)
        self._s.flush()
        return _field_to_dto(row)

    def update_field(
        self,
        field_id: uuid.UUID,
        *,
        name: str | None = None,
        required: bool | None = None,
        restrictions: dict | None = None,
        default_value: Any = _SENTINEL,
        label: Any = _SENTINEL,
    ) -> FieldDTO:
        row = self._s.query(Field).filter_by(id=field_id).first()
        if row is None:
            raise NotFoundError(f"Field '{field_id}' not found")
        if name is not None:
            row.name = name
        if label is not self._SENTINEL:
            row.label = label or None  # None/"" reverts to the derived label
        if required is not None:
            row.required = required
        if restrictions is not None:
            row.restrictions = restrictions
        if default_value is not self._SENTINEL:
            row.default_value = default_value  # None clears it; a value sets it
        self._s.flush()
        return _field_to_dto(row)

    def delete_field(self, field_id: uuid.UUID, stamp: datetime | None = None) -> None:
        """Soft-delete: the field disappears from its schema but keeps its row,
        and every record keeps the values it holds for it (keyed by this id)."""
        row = self._s.query(Field).filter_by(id=field_id).first()
        if row and row.deleted_at is None:
            row.deleted_at = stamp or datetime.now(timezone.utc)
            self._s.flush()

    def restore_field(self, field_id: uuid.UUID) -> FieldDTO:
        """Undo delete_field(): the field is back, and so are its values."""
        row = self._s.query(Field).filter_by(id=field_id).first()
        if row is None:
            raise NotFoundError(f"Field '{field_id}' not found")
        row.deleted_at = None
        self._s.flush()
        return _field_to_dto(row)

    def find_fields(self, ids: set[uuid.UUID]) -> dict[uuid.UUID, FieldDTO]:
        """Fields by id, deleted ones included; ids that are gone are left out."""
        found: dict[uuid.UUID, FieldDTO] = {}
        for start in range(0, len(ids), 500):
            chunk = list(ids)[start : start + 500]
            for row in self._s.query(Field).filter(Field.id.in_(chunk)):
                found[row.id] = _field_to_dto(row)
        return found

    def reorder_fields(
        self, schema_id: uuid.UUID, field_ids: list[uuid.UUID]
    ) -> list[FieldDTO]:
        for i, fid in enumerate(field_ids):
            row = self._s.query(Field).filter_by(id=fid, schema_id=schema_id).first()
            if row and row.deleted_at is None:
                row.position = i
        self._s.flush()
        return self.get_fields(schema_id)


# ------------------------------------------------------------------
# DTO converters (private to this module)
# ------------------------------------------------------------------


def _field_to_dto(row: Field) -> FieldDTO:
    return FieldDTO(
        id=row.id,
        schema_id=row.schema_id,
        name=row.name,
        label=row.label,
        dtype=row.dtype,
        required=row.required,
        restrictions=row.restrictions or {},
        default_value=row.default_value,
        position=row.position,
        created_at=row.created_at,
        deleted_at=row.deleted_at,
    )


def _schema_to_dto(row: Schema) -> SchemaDTO:
    return SchemaDTO(
        id=row.id,
        name=row.name,
        label=row.label,
        description=row.description,
        parent_id=row.parent_id,
        display_template=row.display_template,
        unique_keys=row.unique_keys or [],
        created_at=row.created_at,
        fields=[_field_to_dto(f) for f in row.fields if f.deleted_at is None],
        deleted_at=row.deleted_at,
        deleted_fields=[_field_to_dto(f) for f in row.fields if f.deleted_at],
    )
