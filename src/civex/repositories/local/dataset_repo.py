from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from civex.repositories.local.record_repo import parent_allows_restore
from sqlalchemy.orm import Session

from civex.repositories.local._jobs import bulk_delete_jobs
from civex.db.models import Dataset, Record, WorkflowJob
from civex.domain.dtos import DatasetDTO
from civex.domain.exceptions import NotFoundError


class LocalDatasetRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get_by_name(
        self,
        name: str,
        include_deleted: bool = False,
        with_count: bool = True,
    ) -> DatasetDTO | None:
        q = self._s.query(Dataset).filter_by(name=name)
        if not include_deleted:
            q = q.filter(Dataset.deleted_at.is_(None))
        row = q.first()
        return _to_dto(self._s, row, with_count) if row else None

    def get_by_id(
        self,
        id: uuid.UUID,
        include_deleted: bool = False,
        with_count: bool = True,
    ) -> DatasetDTO | None:
        q = self._s.query(Dataset).filter_by(id=id)
        if not include_deleted:
            q = q.filter(Dataset.deleted_at.is_(None))
        row = q.first()
        return _to_dto(self._s, row, with_count) if row else None

    def list_all(self, with_count: bool = True) -> list[DatasetDTO]:
        return _to_dtos(
            self._s,
            self._s.query(Dataset)
            .filter(Dataset.deleted_at.is_(None))
            .order_by(Dataset.created_at)
            .all(),
            with_count,
        )

    def list_deleted(self) -> list[DatasetDTO]:
        return _to_dtos(
            self._s,
            self._s.query(Dataset)
            .filter(Dataset.deleted_at.is_not(None))
            .order_by(Dataset.deleted_at.desc())
            .all(),
        )

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

    def delete(self, id: uuid.UUID, stamp: datetime | None = None) -> None:
        """Soft-delete: mark the dataset deleted and cascade to every record
        in it (a record's whole parent_record_id chain always lives in the
        same dataset, so this can't leave a child pointing at a live parent
        in a different, still-visible collection)."""
        row = self._s.query(Dataset).filter_by(id=id).first()
        if row is None or row.deleted_at is not None:
            return
        now = stamp or datetime.now(timezone.utc)
        row.deleted_at = now
        self._s.query(Record).filter(
            Record.dataset_id == id, Record.deleted_at.is_(None)
        ).update(
            {"deleted_at": now, "updated_at": Record.updated_at},
            synchronize_session=False,
        )
        self._s.flush()

    def restore(self, id: uuid.UUID) -> DatasetDTO:
        """Undo delete(): clears the dataset's deleted_at and restores the
        records deleted *with* it -- those stamped with the same moment. A
        record deleted on its own beforehand stays in Recently Deleted."""
        row = self._s.query(Dataset).filter_by(id=id).first()
        if row is None:
            raise NotFoundError(f"Dataset '{id}' not found")
        cascade = self._cascade_query(id, row.deleted_at)
        row.deleted_at = None
        if cascade is not None:
            cascade.update(
                {"deleted_at": None, "updated_at": Record.updated_at},
                synchronize_session=False,
            )
        self._s.flush()
        return _to_dto(self._s, row)

    def cascade_count(self, id: uuid.UUID) -> int:
        """How many records restoring this deleted dataset would bring back."""
        row = self._s.query(Dataset).filter_by(id=id).first()
        cascade = self._cascade_query(id, row.deleted_at) if row else None
        return cascade.count() if cascade is not None else 0

    def _cascade_query(self, id: uuid.UUID, deleted_at: datetime | None):
        """The records restoring the collection brings back: deleted with it,
        and not beneath a record still deleted on its own (see
        `parent_allows_restore`). A parent deleted with the collection comes
        back with it, so its children may too."""
        if deleted_at is None:
            return None
        return self._s.query(Record).filter(
            Record.dataset_id == id,
            Record.deleted_at == deleted_at,
            parent_allows_restore(Record, deleted_at),
        )

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


def _to_dto(
    session: Session,
    row: Dataset,
    with_count: bool = True,
) -> DatasetDTO:
    return _to_dtos(session, [row], with_count)[0]


def _to_dtos(
    session: Session,
    rows: list[Dataset],
    with_count: bool = True,
) -> list[DatasetDTO]:
    """DTOs for `rows`. The live-record count scans a collection's records, so
    a caller that only needs the collections themselves (every record write
    looks one up) skips it, leaving `record_count` at 0."""
    if not rows:
        return []
    counts: dict[uuid.UUID, int] = {}
    if with_count:
        # One indexed count per collection, not a single GROUP BY: counted
        # per collection the query is answered from the live-record covering
        # index (ix_records_live_dataset_created) -- a GROUP BY over the lot
        # was measured ~5x slower, the planner picking a scan plus a sort.
        for row in rows:
            counts[row.id] = (
                session.query(func.count(Record.id))
                .filter(Record.dataset_id == row.id, Record.deleted_at.is_(None))
                .scalar()
                or 0
            )
    return [
        DatasetDTO(
            id=row.id,
            name=row.name,
            description=row.description,
            record_count=counts.get(row.id, 0),
            created_at=row.created_at,
            deleted_at=row.deleted_at,
            timezone=row.timezone,
            scope=row.scope,
        )
        for row in rows
    ]
