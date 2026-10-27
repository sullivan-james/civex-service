from __future__ import annotations

from datetime import datetime, timezone

import uuid
from typing import TYPE_CHECKING, Callable

from contextlib import contextmanager, nullcontext

from civex.services.cascades import States, log_cascade, record_states
from civex.domain.dtos import DatasetDTO, RestorePlanDTO
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError
from civex.domain import permissions
from civex.domain.permissions import EVERYTHING, Permissions
from civex.domain.scopes import GLOBAL, LOCAL, validate_scope
from civex.domain.timezones import validate_timezone
from civex.repositories.protocols import AuditRepository, DatasetRepository

if TYPE_CHECKING:
    from civex.services.record_service import RecordService


@contextmanager
def _both(first, second):
    with first, second:
        yield


class DatasetService:
    def __init__(
        self,
        dataset_repo: DatasetRepository,
        audit_repo: AuditRepository | None = None,
        record_svc: RecordService | None = None,
        on_purge: Callable[[uuid.UUID], object] | None = None,
        permissions: Permissions = EVERYTHING,
    ) -> None:
        self._permissions = permissions
        self._datasets = dataset_repo
        self._audit = audit_repo
        self._record_svc = record_svc
        # Called with the id of every purged collection, so anything keyed by
        # collection id elsewhere (storage placement) can drop it.
        self._on_purge = on_purge

    def _check_not_referenced(self, dataset: DatasetDTO, action: str) -> None:
        """A global collection that records in other collections reference
        can't be made local or deleted: the references would dangle."""
        if dataset.scope != GLOBAL or self._record_svc is None:
            return
        total, referrers = self._record_svc.collection_referrers(dataset.id)
        if not total:
            return
        shown = [f"{rec.schema_name} record {str(rec.id)[:8]}" for rec, _ in referrers]
        msg = (
            f"Cannot {action} '{dataset.name}': "
            f"{total} record(s) in other collections reference it: " + "; ".join(shown)
        )
        if total > len(shown):
            msg += f" and {total - len(shown)} more"
        raise ValidationError(msg)

    def create(
        self,
        name: str,
        description: str | None = None,
        timezone: str | None = None,
        scope: str = LOCAL,
    ) -> DatasetDTO:
        self._permissions.require(permissions.CHANGE_STRUCTURE)
        if self._datasets.get_by_name(name):
            raise AlreadyExistsError(f"Dataset '{name}' already exists")
        if timezone:
            timezone = validate_timezone(timezone)
        scope = validate_scope(scope)
        dto = self._datasets.create(
            name=name, description=description, timezone=timezone or None, scope=scope
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

    def id_of(self, ref: str) -> uuid.UUID:
        """A collection's id from its name or id, deleted or not (its history
        outlives it). Raises NotFoundError."""
        try:
            dto = self._datasets.get_by_id(
                uuid.UUID(ref),
                include_deleted=True,
                with_count=False,
            )
        except ValueError:
            dto = self._datasets.get_by_name(
                ref, include_deleted=True, with_count=False
            )
        if dto is None:
            raise NotFoundError(f"Dataset '{ref}' not found")
        return dto.id

    def find(self, ids: set[uuid.UUID]) -> dict[uuid.UUID, DatasetDTO]:
        """Collections by id, deleted ones included; ids that are gone are left out."""
        found: dict[uuid.UUID, DatasetDTO] = {}
        for dataset_id in ids:
            dto = self._datasets.get_by_id(
                dataset_id, include_deleted=True, with_count=False
            )
            if dto:
                found[dataset_id] = dto
        return found

    def list_all(self, with_count: bool = True) -> list[DatasetDTO]:
        """Every live collection. `with_count=False` skips the record counts
        (left at 0) for callers that only need names, ids or scopes."""
        return self._datasets.list_all(with_count=with_count)

    def update(
        self,
        name: str,
        new_name: str | None = None,
        description: str | None = None,
        timezone: str | None = None,
        scope: str | None = None,
    ) -> DatasetDTO:
        """`timezone`: None = unchanged, "" = clear, otherwise an IANA zone.
        `scope`: None = unchanged."""
        self._permissions.require(permissions.CHANGE_STRUCTURE)
        if timezone:
            timezone = validate_timezone(timezone)
        dataset = self.get(name)
        if new_name and new_name != name:
            if self._datasets.get_by_name(new_name):
                raise AlreadyExistsError(f"Dataset '{new_name}' already exists")
        if scope is not None:
            scope = validate_scope(scope)
            if scope == LOCAL and dataset.scope == GLOBAL:
                self._check_not_referenced(dataset, "make local")
        old_dict = dataset.to_dict()
        updated = self._datasets.update(
            dataset.id,
            name=new_name,
            description=description,
            timezone=timezone,
            scope=scope,
        )
        if self._audit:
            self._audit.log_change(
                "update", "dataset", updated.id, old_dict, updated.to_dict()
            )
        return updated

    def delete(self, name: str) -> None:
        """Soft-delete: the collection (and every record in it — see
        DatasetRepository.delete) moves to Recently Deleted, reversible via
        restore() within the retention window. A global collection that other
        collections reference can't be deleted."""
        self._permissions.require(permissions.DELETE)
        dataset = self.get(name)
        self._check_not_referenced(dataset, "delete")
        stamp = datetime.now(
            timezone.utc
        )  # the entry's time and the stamp: one instant
        before = self._cascade_before(dataset.id)
        with self._one_event("delete", before, None):
            if self._audit:
                self._audit.log_change(
                    "delete",
                    "dataset",
                    dataset.id,
                    dataset.to_dict(),
                    None,
                    timestamp=stamp,
                )
            self._datasets.delete(dataset.id, stamp)
            self._log_cascade(dataset.id, before)

    def _records_repo(self):
        return self._record_svc.records_repo if self._record_svc else None

    def _cascade_before(self, dataset_id: uuid.UUID) -> States:
        records = self._records_repo()
        return record_states(records, dataset_id=dataset_id) if records else {}

    def _log_cascade(self, dataset_id: uuid.UUID, before: States) -> None:
        """An entry for each of the collection's records its delete or restore
        changed (`services/cascades`)."""
        records = self._records_repo()
        if records:
            log_cascade(records, self._audit, before, dataset_id=dataset_id)

    def _one_event(self, kind: str, before: States, stamp: datetime | None):
        if not self._audit:
            return nullcontext()
        # Shown as one event only when it takes records with it.
        many = any(
            (at is None) if kind == "delete" else (stamp is not None and at == stamp)
            for at in before.values()
        )
        return _both(
            self._audit.operation(),
            self._audit.batch(kind) if many else nullcontext(),
        )

    def list_deleted(self) -> list[DatasetDTO]:
        return self._datasets.list_deleted()

    def restore_plan(self, name: str) -> RestorePlanDTO:
        """What restoring this deleted collection would bring back: it and the
        records deleted with it, not those deleted on their own earlier."""
        dataset = self._deleted(name)
        return RestorePlanDTO(
            kind="collection",
            id=dataset.id,
            name=dataset.name,
            records=self._datasets.cascade_count(dataset.id),
            deleted_at=dataset.deleted_at,
        )

    def _deleted(self, name: str) -> DatasetDTO:
        dataset = self._datasets.get_by_name(name, include_deleted=True)
        if dataset is None:
            raise NotFoundError(f"Dataset '{name}' not found")
        if dataset.deleted_at is None:
            raise ValidationError(f"Dataset '{name}' is not deleted")
        return dataset

    def restore(self, name: str) -> DatasetDTO:
        """Undo delete(): the collection and the records cascade-deleted
        with it become live again (see DatasetRepository.restore)."""
        self._permissions.require(permissions.CHANGE_STRUCTURE)
        dataset = self._datasets.get_by_name(name, include_deleted=True)
        if dataset is None:
            raise NotFoundError(f"Dataset '{name}' not found")
        if dataset.deleted_at is None:
            raise ValidationError(f"Dataset '{name}' is not deleted")
        before = self._cascade_before(dataset.id)
        with self._one_event("restore", before, dataset.deleted_at):
            restored = self._datasets.restore(dataset.id)
            if self._audit:
                self._audit.log_change(
                    "restore",
                    "dataset",
                    restored.id,
                    dataset.to_dict(),
                    restored.to_dict(),
                )
            self._log_cascade(dataset.id, before)
        return restored

    def purge(self, name: str) -> None:
        """Permanently remove a collection that's already in Recently
        Deleted — a separate, explicit action from delete(). Irreversible."""
        self._permissions.require(permissions.DELETE)
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
            # Its records go with it, and so does their history.
            self._audit.forget_records_matching(f'"dataset_id": "{dataset.id}"')
        self._datasets.purge(dataset.id)
        if self._on_purge:
            self._on_purge(dataset.id)
