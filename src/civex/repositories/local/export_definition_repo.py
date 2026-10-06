from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from civex.db.models import ExportDefinition, Schema
from civex.domain.dtos import ExportDefinitionDTO
from civex.domain.exceptions import NotFoundError


class LocalExportDefinitionRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get_by_name(
        self, schema_id: uuid.UUID, name: str
    ) -> ExportDefinitionDTO | None:
        row = (
            self._s.query(ExportDefinition)
            .filter_by(schema_id=schema_id, name=name)
            .first()
        )
        return _to_dto(row) if row else None

    def list_by_schema(self, schema_id: uuid.UUID) -> list[ExportDefinitionDTO]:
        return [
            _to_dto(r)
            for r in self._s.query(ExportDefinition)
            .filter_by(schema_id=schema_id)
            .order_by(ExportDefinition.created_at, ExportDefinition.name)
            .all()
        ]

    def list_for_schemas(
        self, schema_ids: list[uuid.UUID]
    ) -> list[ExportDefinitionDTO]:
        """Every definition attached to any of these schemas, in one query."""
        if not schema_ids:
            return []
        return [
            _to_dto(r)
            for r in self._s.query(ExportDefinition)
            .join(Schema, ExportDefinition.schema_id == Schema.id)
            .filter(ExportDefinition.schema_id.in_(schema_ids))
            .order_by(Schema.name, ExportDefinition.name)
            .all()
        ]

    def list_all(self) -> list[ExportDefinitionDTO]:
        return [
            _to_dto(r)
            for r in self._s.query(ExportDefinition)
            .join(Schema, ExportDefinition.schema_id == Schema.id)
            .order_by(Schema.name, ExportDefinition.name)
            .all()
        ]

    def create(
        self,
        schema_id: uuid.UUID,
        name: str,
        holder_id: uuid.UUID | None,
        fields: list[str],
        filter_tree: dict[str, Any] | None,
        files_layout: str,
        include_files: bool = True,
        tables: list[dict[str, Any]] | None = None,
    ) -> ExportDefinitionDTO:
        row = ExportDefinition(
            schema_id=schema_id,
            name=name,
            holder_schema_id=holder_id,
            fields=fields,
            filter_tree=filter_tree,
            files_layout=files_layout,
            include_files=include_files,
            tables=tables or [],
        )
        self._s.add(row)
        self._s.flush()
        return _to_dto(row)

    _SENTINEL = object()

    def update(
        self,
        id: uuid.UUID,
        name: str | None = None,
        holder_id=_SENTINEL,
        fields=_SENTINEL,
        filter_tree=_SENTINEL,
        files_layout=_SENTINEL,
        include_files=_SENTINEL,
        tables=_SENTINEL,
    ) -> ExportDefinitionDTO:
        row = self._s.query(ExportDefinition).filter_by(id=id).first()
        if row is None:
            raise NotFoundError(f"Export '{id}' not found")
        if name is not None:
            row.name = name
        if holder_id is not self._SENTINEL:
            row.holder_schema_id = holder_id
        if fields is not self._SENTINEL:
            row.fields = fields
        if filter_tree is not self._SENTINEL:
            row.filter_tree = filter_tree
        if files_layout is not self._SENTINEL:
            row.files_layout = files_layout
        if include_files is not self._SENTINEL:
            row.include_files = include_files
        if tables is not self._SENTINEL:
            row.tables = tables
        self._s.flush()
        return _to_dto(row)

    def delete(self, id: uuid.UUID) -> None:
        row = self._s.query(ExportDefinition).filter_by(id=id).first()
        if row is not None:
            self._s.delete(row)
            self._s.flush()


def _to_dto(row: ExportDefinition) -> ExportDefinitionDTO:
    return ExportDefinitionDTO(
        id=row.id,
        schema_id=row.schema_id,
        schema_name=row.schema.name,
        name=row.name,
        holder_id=row.holder_schema_id,
        holder=row.holder.name if row.holder is not None else None,
        fields=row.fields or [],
        filter_tree=row.filter_tree,
        files_layout=row.files_layout or "tree",
        created_at=row.created_at,
        include_files=row.include_files is not False,
        tables=row.tables or [],
    )
