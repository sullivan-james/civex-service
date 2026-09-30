from __future__ import annotations

import uuid

from civex.domain.dtos import DatasetDTO
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError
from civex.domain.timezones import validate_timezone
from civex.repositories.protocols import AuditRepository, DatasetRepository


class DatasetService:
    def __init__(
        self, dataset_repo: DatasetRepository, audit_repo: AuditRepository | None = None
    ) -> None:
        self._datasets = dataset_repo
        self._audit = audit_repo

    def create(
        self,
        name: str,
        description: str | None = None,
        timezone: str | None = None,
    ) -> DatasetDTO:
        if self._datasets.get_by_name(name):
            raise AlreadyExistsError(f"Dataset '{name}' already exists")
        if timezone:
            timezone = validate_timezone(timezone)
        dto = self._datasets.create(
            name=name, description=description, timezone=timezone or None
        )
        if self._audit:
            self._audit.log_change("create", "dataset", dto.id, None, dto.to_dict())
        return dto

    def get(self, name: str) -> DatasetDTO:
        dto = self._datasets.get_by_name(name)
        if not dto:
            raise NotFoundError(f"Dataset '{name}' not found")
        return dto

    def get_by_id(self, dataset_id: uuid.UUID) -> DatasetDTO:
        dto = self._datasets.get_by_id(dataset_id)
        if not dto:
            raise NotFoundError(f"Dataset '{dataset_id}' not found")
        return dto

    def list_all(self) -> list[DatasetDTO]:
        return self._datasets.list_all()

    def update(
        self,
        name: str,
        new_name: str | None = None,
        description: str | None = None,
        timezone: str | None = None,
    ) -> DatasetDTO:
        """`timezone`: None = unchanged, "" = clear, otherwise an IANA zone."""
        if timezone:
            timezone = validate_timezone(timezone)
        dataset = self.get(name)
        if new_name and new_name != name:
            if self._datasets.get_by_name(new_name):
                raise AlreadyExistsError(f"Dataset '{new_name}' already exists")
        old_dict = dataset.to_dict()
        updated = self._datasets.update(
            dataset.id, name=new_name, description=description, timezone=timezone
        )
        if self._audit:
            self._audit.log_change(
                "update", "dataset", updated.id, old_dict, updated.to_dict()
            )
        return updated

    def delete(self, name: str) -> None:
        """Soft-delete: the collection (and every record in it — see
        DatasetRepository.delete) moves to Recently Deleted, reversible via
        restore() within the retention window."""
        dataset = self.get(name)
        if self._audit:
            self._audit.log_change(
                "delete", "dataset", dataset.id, dataset.to_dict(), None
            )
        self._datasets.delete(dataset.id)

    def list_deleted(self) -> list[DatasetDTO]:
        return self._datasets.list_deleted()

    def restore(self, name: str) -> DatasetDTO:
        """Undo delete(): the collection and the records cascade-deleted
        with it become live again (see DatasetRepository.restore)."""
        dataset = self._datasets.get_by_name(name, include_deleted=True)
        if dataset is None:
            raise NotFoundError(f"Dataset '{name}' not found")
        if dataset.deleted_at is None:
            raise ValidationError(f"Dataset '{name}' is not deleted")
        restored = self._datasets.restore(dataset.id)
        if self._audit:
            self._audit.log_change(
                "restore",
                "dataset",
                restored.id,
                dataset.to_dict(),
                restored.to_dict(),
            )
        return restored

    def purge(self, name: str) -> None:
        """Permanently remove a collection that's already in Recently
        Deleted — a separate, explicit action from delete(). Irreversible."""
        dataset = self._datasets.get_by_name(name, include_deleted=True)
        if dataset is None:
            raise NotFoundError(f"Dataset '{name}' not found")
        if dataset.deleted_at is None:
            raise ValidationError(
                f"Dataset '{name}' must be deleted before it can be purged"
            )
        if self._audit:
            self._audit.log_change(
                "purge", "dataset", dataset.id, dataset.to_dict(), None
            )
        self._datasets.purge(dataset.id)
