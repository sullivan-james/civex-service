"""
Storage interface protocols.

Both LocalRepository (SQLAlchemy) and a future RemoteRepository (HTTP client)
satisfy these interfaces via structural subtyping — no inheritance required.
Services only import from here, never from civex.db.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from pathlib import Path
from typing import (
    Any,
    AsyncIterable,
    ContextManager,
    Iterable,
    Iterator,
    Protocol,
    runtime_checkable,
)

from civex.domain.dtos import (
    AiUsageEventDTO,
    DatasetDTO,
    FieldDTO,
    FileRef,
    RecordDTO,
    SchemaDTO,
    StoredObjectInfo,
    ViewDTO,
    WorkflowJobDTO,
)
from civex.domain.query import ResolvedQuery

# (day, dataset_name, schema_name, count) -- see LocalRecordRepository.growth_by_period
RecordGrowthRow = tuple[date, str, str, int]
# (day, status, count) -- see LocalWorkflowJobRepository.status_counts_by_period
JobStatusRow = tuple[date, str, int]
# (bucket_start, plugin, count) -- already bucketed, see
# LocalWorkflowJobRepository.failure_counts_by_plugin
PluginFailureRow = tuple[str, str, int]
# (day, action, entity_type, count) -- see LocalAuditRepository.event_counts_by_period
AuditEventRow = tuple[date, str, str, int]
# (trigger, count) -- see LocalWorkflowJobRepository.trigger_counts
TriggerCountRow = tuple[str, int]


@runtime_checkable
class SchemaRepository(Protocol):
    def get_by_name(
        self, name: str, include_deleted: bool = False
    ) -> SchemaDTO | None: ...
    def get_by_id(
        self, id: uuid.UUID, include_deleted: bool = False
    ) -> SchemaDTO | None: ...
    def list_all(self) -> list[SchemaDTO]: ...
    def list_deleted(self) -> list[SchemaDTO]: ...
    def create(
        self,
        name: str,
        description: str | None,
        parent_id: uuid.UUID | None,
        label: str | None = None,
    ) -> SchemaDTO: ...
    def update(
        self,
        id: uuid.UUID,
        name: str | None,
        description: str | None,
        display_fields: list[str] | None = ...,
        label: str | None = ...,
    ) -> SchemaDTO: ...
    def delete(self, id: uuid.UUID) -> None: ...
    def restore(self, id: uuid.UUID) -> SchemaDTO: ...
    def purge(self, id: uuid.UUID) -> None: ...
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
    ) -> FieldDTO: ...
    def update_field(
        self,
        field_id: uuid.UUID,
        *,
        name: str | None = None,
        required: bool | None = None,
        restrictions: dict | None = None,
        default_value: Any = ...,
        label: str | None = ...,
    ) -> FieldDTO: ...
    def delete_field(self, field_id: uuid.UUID) -> None: ...
    def get_fields(self, schema_id: uuid.UUID) -> list[FieldDTO]: ...
    def reorder_fields(
        self, schema_id: uuid.UUID, field_ids: list[uuid.UUID]
    ) -> list[FieldDTO]: ...


@runtime_checkable
class DatasetRepository(Protocol):
    def get_by_name(
        self, name: str, include_deleted: bool = False
    ) -> DatasetDTO | None: ...
    def get_by_id(
        self, id: uuid.UUID, include_deleted: bool = False
    ) -> DatasetDTO | None: ...
    def list_all(self) -> list[DatasetDTO]: ...
    def list_deleted(self) -> list[DatasetDTO]: ...
    def create(
        self,
        name: str,
        description: str | None,
        timezone: str | None = None,
        scope: str = "local",
    ) -> DatasetDTO: ...
    def update(
        self,
        id: uuid.UUID,
        name: str | None,
        description: str | None,
        timezone: str | None = None,
        scope: str | None = None,
    ) -> DatasetDTO: ...
    def set_schemas(self, id: uuid.UUID, schema_names: list[str]) -> DatasetDTO:
        """Replace the collection's schema list (names must be live schemas)."""
        ...

    def schemas_in_use(self, id: uuid.UUID) -> set[str]:
        """Names of the schemas live records in the collection are typed by."""
        ...

    def delete(self, id: uuid.UUID) -> None: ...
    def restore(self, id: uuid.UUID) -> DatasetDTO: ...
    def purge(self, id: uuid.UUID) -> None: ...


@runtime_checkable
class ViewRepository(Protocol):
    def get_by_id(self, id: uuid.UUID) -> ViewDTO | None: ...
    def get_by_name(self, schema_id: uuid.UUID, name: str) -> ViewDTO | None: ...
    def list_by_schema(self, schema_id: uuid.UUID) -> list[ViewDTO]: ...
    def list_all(self) -> list[ViewDTO]: ...
    def create(
        self,
        schema_id: uuid.UUID,
        name: str,
        columns: list[str],
        filter_tree: dict[str, Any] | None,
        sort: list[dict[str, Any]],
    ) -> ViewDTO: ...
    def update(
        self,
        id: uuid.UUID,
        name: str | None,
        columns: list[str] = ...,
        filter_tree: dict[str, Any] | None = ...,
        sort: list[dict[str, Any]] = ...,
    ) -> ViewDTO: ...
    def delete(self, id: uuid.UUID) -> None: ...


@runtime_checkable
class RecordRepository(Protocol):
    def get_by_id(
        self, id: uuid.UUID, include_deleted: bool = False
    ) -> RecordDTO | None: ...
    def get_by_prefix(
        self, prefix: str, include_deleted: bool = False
    ) -> RecordDTO | None: ...
    def list_all(self) -> list[RecordDTO]: ...
    def list_deleted(
        self,
        dataset_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[RecordDTO]: ...
    def list_by_dataset(self, dataset_id: uuid.UUID) -> list[RecordDTO]: ...
    def list_by_ids(self, ids: list[uuid.UUID]) -> list[RecordDTO]: ...
    def list_filtered(
        self, query: ResolvedQuery, offset: int, limit: int
    ) -> list[RecordDTO]: ...
    def count(self, query: ResolvedQuery) -> int: ...
    def count_by_schema(self, query: ResolvedQuery) -> dict[str, int]: ...
    def count_children(
        self, parent_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, dict[str, int]]: ...
    def growth_by_period(
        self,
        dataset_id: uuid.UUID | None,
        schema_id: uuid.UUID | None,
        start: datetime | None,
        end: datetime | None,
    ) -> list[RecordGrowthRow]: ...
    def list_by_schema(
        self,
        schema_id: uuid.UUID,
        search: str | None = None,
        limit: int = 20,
        dataset_ids: list[uuid.UUID] | None = None,
    ) -> list[RecordDTO]: ...
    def search_all(
        self,
        search: str,
        limit: int = 20,
        dataset_id: uuid.UUID | None = None,
    ) -> list[RecordDTO]: ...
    def count_schema_matches(
        self, schema_id: uuid.UUID, search: str | None = None
    ) -> int: ...
    def list_ids_by_schema_ids(
        self, schema_ids: list[uuid.UUID]
    ) -> list[uuid.UUID]: ...
    def list_children(
        self, parent_id: uuid.UUID, include_deleted: bool = False
    ) -> list[RecordDTO]: ...
    def list_referencing(
        self,
        target_ids: list[uuid.UUID],
        reference_field_ids: list[uuid.UUID],
        reference_list_field_ids: list[uuid.UUID],
    ) -> list[RecordDTO]: ...
    def create(
        self,
        dataset_id: uuid.UUID,
        schema_id: uuid.UUID,
        data: dict[str, Any],
        parent_record_id: uuid.UUID | None = None,
    ) -> RecordDTO: ...
    def update(self, id: uuid.UUID, data: dict[str, Any]) -> RecordDTO: ...
    def delete(self, id: uuid.UUID) -> None: ...
    def restore(self, id: uuid.UUID) -> RecordDTO: ...
    def purge(self, id: uuid.UUID) -> None: ...


@runtime_checkable
class WorkflowJobRepository(Protocol):
    def enqueue(
        self,
        workflow_name: str,
        record_id: uuid.UUID,
        trigger: str,
        input_data: dict | None = None,
        depth: int = 0,
    ) -> WorkflowJobDTO: ...
    def claim_pending(self) -> WorkflowJobDTO | None: ...
    def mark_completed(
        self,
        job_id: uuid.UUID,
        log: str | None = None,
        step_executions: list[dict] | None = None,
        affected_records: list[dict] | None = None,
    ) -> None: ...
    def mark_failed(
        self,
        job_id: uuid.UUID,
        error_details: dict,
        log: str | None = None,
        step_executions: list[dict] | None = None,
        affected_records: list[dict] | None = None,
    ) -> None: ...
    def list_all(
        self,
        status: str | None = None,
        record_id: str | None = None,
        affected_record_id: str | None = None,
        offset: int = 0,
        limit: int | None = None,
        affected_schema: str | None = None,
    ) -> list[WorkflowJobDTO]: ...
    def count(
        self,
        status: str | None = None,
        record_id: str | None = None,
        affected_record_id: str | None = None,
        affected_schema: str | None = None,
    ) -> int: ...
    def get_by_id(self, job_id: uuid.UUID) -> WorkflowJobDTO | None: ...
    def count_active_for_workflow(self, workflow_name: str) -> int: ...
    def failure_counts_by_plugin(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        bucket: str | None = None,
    ) -> dict[str, int] | list[PluginFailureRow]: ...
    def status_counts_by_period(
        self,
        start: datetime | None,
        end: datetime | None,
        workflow_name: str | None,
        trigger: str | None,
        status: str | None,
    ) -> list[JobStatusRow]: ...
    def step_durations(
        self,
        start: datetime | None,
        end: datetime | None,
        plugin: str | None,
        status: str | None,
    ) -> list[float]: ...
    def trigger_counts(
        self,
        start: datetime | None,
        end: datetime | None,
        workflow_name: str | None,
        status: str | None,
        trigger: str | None,
    ) -> list[TriggerCountRow]: ...


@runtime_checkable
class AiUsageRepository(Protocol):
    def add(
        self, provider: str, model: str, input_tokens: int, output_tokens: int
    ) -> AiUsageEventDTO: ...
    def list_all(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> list[AiUsageEventDTO]: ...


@runtime_checkable
class AuditRepository(Protocol):
    """Write-side audit interface used by services to record changes."""

    def log_change(
        self,
        action: str,
        entity_type: str,
        entity_id: uuid.UUID,
        old_data: dict | None,
        new_data: dict | None,
    ) -> None: ...
    def event_counts_by_period(
        self,
        start: datetime | None,
        end: datetime | None,
        entity_type: str | None = None,
        action: str | None = None,
    ) -> list[AuditEventRow]: ...


@runtime_checkable
class FileObjectStore(Protocol):
    """
    Content-addressed blob store.
    Implementations: LocalFileObjectStore (_civex/objects/), future S3Store.
    """

    def put(self, data: bytes, original_filename: str) -> FileRef: ...
    async def put_stream(
        self,
        chunks: AsyncIterable[bytes],
        original_filename: str,
        size_hint: int | None = None,
    ) -> FileRef: ...
    def get(self, sha256: str) -> bytes: ...
    def exists(self, sha256: str) -> bool: ...
    def object_path(self, sha256: str) -> Path: ...
    def list_objects(self) -> list[StoredObjectInfo]: ...
    def iter_objects(self) -> Iterator[StoredObjectInfo]: ...
    def put_path(self, path: Path, original_filename: str | None = None) -> FileRef: ...
    def reconcile_inventory(self) -> dict[str, int]: ...
    def delete(self, sha256: str, volume: str | None = None) -> bool: ...
    def sweep_stale_scratch(
        self, older_than_seconds: float, dry_run: bool = False
    ) -> int: ...
    def gc_lock(self) -> ContextManager[None]: ...


class FileReferenceRepository(Protocol):
    """Which blobs are referenced by live records / workflow job inputs."""

    def referenced_subset(self, shas: Iterable[str]) -> set[str]: ...
    def count_referenced(self) -> int: ...
    def rebuild(self) -> int: ...
