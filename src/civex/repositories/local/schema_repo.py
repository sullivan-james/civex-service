from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import nulls_last
from sqlalchemy.orm import Session

from civex.db.models import Field, Schema
from civex.domain.dtos import FieldDTO, SchemaDTO
from civex.domain.exceptions import NotFoundError


class LocalSchemaRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_by_name(self, name: str) -> SchemaDTO | None:
        row = self._s.query(Schema).filter_by(name=name).first()
        return _schema_to_dto(row) if row else None

    def get_by_id(self, id: uuid.UUID) -> SchemaDTO | None:
        row = self._s.query(Schema).filter_by(id=id).first()
        return _schema_to_dto(row) if row else None

    def list_all(self) -> list[SchemaDTO]:
        return [
            _schema_to_dto(r)
            for r in self._s.query(Schema).order_by(Schema.created_at).all()
        ]

    def get_fields(self, schema_id: uuid.UUID) -> list[FieldDTO]:
        rows = (
            self._s.query(Field)
            .filter_by(schema_id=schema_id)
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
    ) -> SchemaDTO:
        row = Schema(name=name, description=description, parent_id=parent_id)
        self._s.add(row)
        self._s.flush()
        return _schema_to_dto(row)

    _SENTINEL = object()

    def update(
        self,
        id: uuid.UUID,
        name: str | None,
        description: str | None,
        display_field=_SENTINEL,
    ) -> SchemaDTO:
        row = self._s.query(Schema).filter_by(id=id).first()
        if row is None:
            raise NotFoundError(f"Schema '{id}' not found")
        if name is not None:
            row.name = name
        if description is not None:
            row.description = description
        if display_field is not self._SENTINEL:
            row.display_field = display_field  # None clears it; a string sets it
        self._s.flush()
        return _schema_to_dto(row)

    def delete(self, id: uuid.UUID) -> None:
        row = self._s.query(Schema).filter_by(id=id).first()
        if row:
            self._s.delete(row)
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
    ) -> FieldDTO:
        row = Field(
            schema_id=schema_id,
            name=name,
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
    ) -> FieldDTO:
        row = self._s.query(Field).filter_by(id=field_id).first()
        if row is None:
            raise NotFoundError(f"Field '{field_id}' not found")
        if name is not None:
            row.name = name
        if required is not None:
            row.required = required
        if restrictions is not None:
            row.restrictions = restrictions
        if default_value is not self._SENTINEL:
            row.default_value = default_value  # None clears it; a value sets it
        self._s.flush()
        return _field_to_dto(row)

    def delete_field(self, field_id: uuid.UUID) -> None:
        row = self._s.query(Field).filter_by(id=field_id).first()
        if row:
            self._s.delete(row)
            self._s.flush()

    def reorder_fields(
        self, schema_id: uuid.UUID, field_ids: list[uuid.UUID]
    ) -> list[FieldDTO]:
        for i, fid in enumerate(field_ids):
            row = self._s.query(Field).filter_by(id=fid, schema_id=schema_id).first()
            if row:
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
        dtype=row.dtype,
        required=row.required,
        restrictions=row.restrictions or {},
        default_value=row.default_value,
        position=row.position,
        created_at=row.created_at,
    )


def _schema_to_dto(row: Schema) -> SchemaDTO:
    return SchemaDTO(
        id=row.id,
        name=row.name,
        description=row.description,
        parent_id=row.parent_id,
        display_field=row.display_field,
        created_at=row.created_at,
        fields=[_field_to_dto(f) for f in row.fields],
    )
