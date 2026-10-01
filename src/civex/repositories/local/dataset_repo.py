from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from civex.repositories.local._jobs import bulk_delete_jobs
from civex.db.models import Dataset, DatasetSchema, Record, Schema, WorkflowJob
from civex.domain.dtos import DatasetDTO
from civex.domain.exceptions import NotFoundError


class LocalDatasetRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get_by_name(
        self, name: str, include_deleted: bool = False
    ) -> DatasetDTO | None:
        q = self._s.query(Dataset).filter_by(name=name)
        if not include_deleted:
            q = q.filter(Dataset.deleted_at.is_(None))
        row = q.first()
        return _to_dto(self._s, row) if row else None

    def get_by_id(
        self, id: uuid.UUID, include_deleted: bool = False
    ) -> DatasetDTO | None:
        q = self._s.query(Dataset).filter_by(id=id)
        if not include_deleted:
            q = q.filter(Dataset.deleted_at.is_(None))
        row = q.first()
        return _to_dto(self._s, row) if row else None

    def list_all(self) -> list[DatasetDTO]:
        return [
            _to_dto(self._s, r)
            for r in self._s.query(Dataset)
            .filter(Dataset.deleted_at.is_(None))
            .order_by(Dataset.created_at)
            .all()
        ]

    def list_deleted(self) -> list[DatasetDTO]:
        return [
            _to_dto(self._s, r)
            for r in self._s.query(Dataset)
            .filter(Dataset.deleted_at.is_not(None))
            .order_by(Dataset.deleted_at.desc())
            .all()
        ]

    def create(
        self,
        name: str,
        description: str | None,
        timezone: str | None = None,
        scope: str = "local",
    ) -> DatasetDTO:
        row = Dataset(
            name=name,
            description=description,
            timezone=timezone or None,
            scope=scope,
        )
        self._s.add(row)
        self._s.flush()
        return _to_dto(self._s, row)

    def update(
        self,
        id: uuid.UUID,
        name: str | None,
        description: str | None,
        timezone: str | None = None,
        scope: str | None = None,
    ) -> DatasetDTO:
        """None leaves a field unchanged. For `timezone`, an empty string
        clears it back to unset (None can't, since it means "no change")."""
        row = self._s.query(Dataset).filter_by(id=id).first()
        if row is None:
            raise NotFoundError(f"Dataset '{id}' not found")
        if name is not None:
            row.name = name
        if description is not None:
            row.description = description
        if timezone is not None:
            row.timezone = timezone or None
        if scope is not None:
            row.scope = scope
        self._s.flush()
        return _to_dto(self._s, row)

    def set_schemas(self, id: uuid.UUID, schema_names: list[str]) -> DatasetDTO:
        row = self._s.query(Dataset).filter_by(id=id).first()
        if row is None:
            raise NotFoundError(f"Dataset '{id}' not found")
        wanted = set(schema_names)
        schemas = (
            self._s.query(Schema)
            .filter(Schema.name.in_(wanted), Schema.deleted_at.is_(None))
            .all()
            if wanted
            else []
        )
        missing = wanted - {s.name for s in schemas}
        if missing:
            raise NotFoundError(f"Schema '{sorted(missing)[0]}' not found")
        row.schema_links = [
            DatasetSchema(dataset_id=id, schema_id=s.id) for s in schemas
        ]
        self._s.flush()
        return _to_dto(self._s, row)

    def schemas_in_use(self, id: uuid.UUID) -> set[str]:
        rows = (
            self._s.query(Schema.name)
            .join(Record, Record.schema_id == Schema.id)
            .filter(Record.dataset_id == id, Record.deleted_at.is_(None))
            .distinct()
            .all()
        )
        return {name for (name,) in rows}

    def delete(self, id: uuid.UUID) -> None:
        """Soft-delete: mark the dataset deleted and cascade to every record
        in it (a record's whole parent_record_id chain always lives in the
        same dataset, so this can't leave a child pointing at a live parent
        in a different, still-visible collection)."""
        row = self._s.query(Dataset).filter_by(id=id).first()
        if row is None or row.deleted_at is not None:
            return
        now = datetime.now(timezone.utc)
        row.deleted_at = now
        self._s.query(Record).filter(
            Record.dataset_id == id, Record.deleted_at.is_(None)
        ).update({"deleted_at": now}, synchronize_session=False)
        self._s.flush()

    def restore(self, id: uuid.UUID) -> DatasetDTO:
        """Undo delete(): clears the dataset's deleted_at and restores every
        record cascade-deleted with it (see SchemaRepository.restore for the
        same documented simplification around records deleted independently
        beforehand)."""
        row = self._s.query(Dataset).filter_by(id=id).first()
        if row is None:
            raise NotFoundError(f"Dataset '{id}' not found")
        row.deleted_at = None
        self._s.query(Record).filter(
            Record.dataset_id == id, Record.deleted_at.is_not(None)
        ).update({"deleted_at": None}, synchronize_session=False)
        self._s.flush()
        return _to_dto(self._s, row)

    def purge(self, id: uuid.UUID) -> None:
        """Permanently remove a soft-deleted dataset and everything in it."""
        row = self._s.query(Dataset).filter_by(id=id).first()
        if row is None:
            return
        # Bulk-delete dependents first so SQLAlchemy doesn't load every record into
        # memory and issue per-row DELETEs via ORM cascade.
        record_ids = self._s.query(Record.id).filter_by(dataset_id=id).scalar_subquery()
        bulk_delete_jobs(self._s, WorkflowJob.record_id.in_(record_ids))
        # Clear parent_record_id before bulk-deleting records to satisfy the
        # composite self-referential FK (parent_record_id, dataset_id) ->
        # (records.id, records.dataset_id). A child can only ever point to a
        # parent in the same dataset, so nulling every record in this dataset
        # can't strand a reference from another dataset.
        self._s.query(Record).filter_by(dataset_id=id).update(
            {"parent_record_id": None}, synchronize_session=False
        )
        self._s.query(Record).filter_by(dataset_id=id).delete(synchronize_session=False)
        self._s.delete(row)
        self._s.flush()


def _to_dto(session: Session, row: Dataset) -> DatasetDTO:
    record_count = (
        session.query(func.count(Record.id))
        .filter(Record.dataset_id == row.id, Record.deleted_at.is_(None))
        .scalar()
    )
    schema_names = [
        name
        for (name,) in session.query(Schema.name)
        .join(DatasetSchema, DatasetSchema.schema_id == Schema.id)
        .filter(DatasetSchema.dataset_id == row.id)
        .order_by(Schema.name)
        .all()
    ]
    return DatasetDTO(
        id=row.id,
        name=row.name,
        description=row.description,
        record_count=record_count or 0,
        created_at=row.created_at,
        deleted_at=row.deleted_at,
        timezone=row.timezone,
        scope=row.scope,
        schemas=schema_names,
    )
