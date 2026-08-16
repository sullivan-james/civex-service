from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from civex.db.models import Schema, View
from civex.domain.dtos import ViewDTO
from civex.domain.exceptions import NotFoundError


class LocalViewRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get_by_id(self, id: uuid.UUID) -> ViewDTO | None:
        row = self._s.query(View).filter_by(id=id).first()
        return _to_dto(row) if row else None

    def get_by_name(self, schema_id: uuid.UUID, name: str) -> ViewDTO | None:
        row = self._s.query(View).filter_by(schema_id=schema_id, name=name).first()
        return _to_dto(row) if row else None

    def list_by_schema(self, schema_id: uuid.UUID) -> list[ViewDTO]:
        return [
            _to_dto(r)
            for r in self._s.query(View)
            .filter_by(schema_id=schema_id)
            .order_by(View.created_at)
            .all()
        ]

    def list_all(self) -> list[ViewDTO]:
        return [
            _to_dto(r)
            for r in self._s.query(View)
            .join(Schema, View.schema_id == Schema.id)
            .order_by(Schema.name, View.name)
            .all()
        ]

    def create(
        self,
        schema_id: uuid.UUID,
        name: str,
        columns: list[str],
        filter_tree: dict[str, Any] | None,
        sort: list[dict[str, Any]],
    ) -> ViewDTO:
        row = View(
            schema_id=schema_id,
            name=name,
            columns=columns,
            filter_tree=filter_tree,
            sort=sort,
        )
        self._s.add(row)
        self._s.flush()
        return _to_dto(row)

    _SENTINEL = object()

    def update(
        self,
        id: uuid.UUID,
        name: str | None,
        columns=_SENTINEL,
        filter_tree=_SENTINEL,
        sort=_SENTINEL,
    ) -> ViewDTO:
        row = self._s.query(View).filter_by(id=id).first()
        if row is None:
            raise NotFoundError(f"View '{id}' not found")
        if name is not None:
            row.name = name
        if columns is not self._SENTINEL:
            row.columns = columns
        if filter_tree is not self._SENTINEL:
            row.filter_tree = filter_tree
        if sort is not self._SENTINEL:
            row.sort = sort
        self._s.flush()
        return _to_dto(row)

    def delete(self, id: uuid.UUID) -> None:
        row = self._s.query(View).filter_by(id=id).first()
        if row is None:
            return
        self._s.delete(row)
        self._s.flush()


def _to_dto(row: View) -> ViewDTO:
    return ViewDTO(
        id=row.id,
        schema_id=row.schema_id,
        schema_name=row.schema.name,
        name=row.name,
        columns=row.columns or [],
        filter_tree=row.filter_tree,
        sort=row.sort or [],
        created_at=row.created_at,
    )
