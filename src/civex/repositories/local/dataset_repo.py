from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from civex.db.models import Dataset, Record, WorkflowJob
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
        return [
            _to_dto(r)
            for r in self._s.query(Dataset).order_by(Dataset.created_at).all()
        ]

    def create(self, name: str, description: str | None) -> DatasetDTO:
        row = Dataset(name=name, description=description)
        self._s.add(row)
        self._s.flush()
        return _to_dto(row)

    def update(
        self, id: uuid.UUID, name: str | None, description: str | None
    ) -> DatasetDTO:
        row = self._s.query(Dataset).filter_by(id=id).first()
        if name is not None:
            row.name = name
        if description is not None:
            row.description = description
        self._s.flush()
        return _to_dto(row)

    def delete(self, id: uuid.UUID) -> None:
        # Bulk-delete dependents first so SQLAlchemy doesn't load every record into
        # memory and issue per-row DELETEs via ORM cascade.
        record_ids = self._s.query(Record.id).filter_by(dataset_id=id).subquery()
        self._s.query(WorkflowJob).filter(WorkflowJob.record_id.in_(record_ids)).delete(
            synchronize_session=False
        )
        # Clear parent_record_id before bulk-deleting records to satisfy the
        # self-referential FK on PostgreSQL (SQLite ignores it without PRAGMA).
        self._s.query(Record).filter_by(dataset_id=id).update(
            {"parent_record_id": None}, synchronize_session=False
        )
        self._s.query(Record).filter_by(dataset_id=id).delete(synchronize_session=False)
        row = self._s.query(Dataset).filter_by(id=id).first()
        if row:
            self._s.delete(row)
            self._s.flush()


def _to_dto(row: Dataset) -> DatasetDTO:
    return DatasetDTO(
        id=row.id,
        name=row.name,
        description=row.description,
        record_count=len(row.records),
        created_at=row.created_at,
    )
