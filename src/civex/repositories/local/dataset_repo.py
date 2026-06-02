from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from civex.db.models import Dataset
from civex.domain.dtos import DatasetDTO


class LocalDatasetRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get_by_name(self, name: str) -> DatasetDTO | None:
        row = self._s.query(Dataset).filter_by(name=name).first()
        return _to_dto(row) if row else None

    def get_by_id(self, id: uuid.UUID) -> DatasetDTO | None:
        row = self._s.query(Dataset).filter_by(id=id).first()
        return _to_dto(row) if row else None

    def list_all(self) -> list[DatasetDTO]:
        return [_to_dto(r) for r in self._s.query(Dataset).order_by(Dataset.created_at).all()]

    def create(
        self,
        name: str,
        description: str | None,
        schema_id: uuid.UUID,
    ) -> DatasetDTO:
        row = Dataset(name=name, description=description, schema_id=schema_id)
        self._s.add(row)
        self._s.flush()
        return _to_dto(row)

    def delete(self, id: uuid.UUID) -> None:
        row = self._s.query(Dataset).filter_by(id=id).first()
        if row:
            self._s.delete(row)
            self._s.flush()


def _to_dto(row: Dataset) -> DatasetDTO:
    return DatasetDTO(
        id=row.id,
        name=row.name,
        description=row.description,
        schema_id=row.schema_id,
        schema_name=row.schema.name,
        record_count=len(row.records),
        created_at=row.created_at,
    )
