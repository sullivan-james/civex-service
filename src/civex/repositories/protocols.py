"""
Storage interface protocols.

Both LocalRepository (SQLAlchemy) and a future RemoteRepository (HTTP client)
satisfy these interfaces via structural subtyping — no inheritance required.
Services only import from here, never from civex.db.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from civex.domain.dtos import (
    AiUsageEventDTO,
    DatasetDTO,
    FieldDTO,
    FileRef,
    RecordDTO,
    SchemaDTO,
    WorkflowJobDTO,
)


@runtime_checkable
class SchemaRepository(Protocol):
    def get_by_name(self, name: str) -> SchemaDTO | None: ...
    def get_by_id(self, id: uuid.UUID) -> SchemaDTO | None: ...
    def list_all(self) -> list[SchemaDTO]: ...
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
    def get_by_name(self, name: str) -> DatasetDTO | None: ...
    def get_by_id(self, id: uuid.UUID) -> DatasetDTO | None: ...
    def list_all(self) -> list[DatasetDTO]: ...
    def create(self, name: str, description: str | None) -> DatasetDTO: ...
    def update(
        self, id: uuid.UUID, name: str | None, description: str | None
    ) -> DatasetDTO: ...
    def delete(self, id: uuid.UUID) -> None: ...


@runtime_checkable
class RecordRepository(Protocol):
    def get_by_id(self, id: uuid.UUID) -> RecordDTO | None: ...
    def get_by_prefix(self, prefix: str) -> RecordDTO | None: ...
    def list_all(self) -> list[RecordDTO]: ...
    def list_by_dataset(self, dataset_id: uuid.UUID) -> list[RecordDTO]: ...
    def list_filtered(
        self,
        dataset_id: uuid.UUID,
        schema_id: uuid.UUID | None,
        parent_record_id: uuid.UUID | None,
        field_filters: list[tuple[str, str]],
        search: str | None,
        offset: int,
        limit: int,
    ) -> list[RecordDTO]: ...
    def count(
        self,
        dataset_id: uuid.UUID,
        schema_id: uuid.UUID | None,
        parent_record_id: uuid.UUID | None,
        field_filters: list[tuple[str, str]],
        search: str | None,
    ) -> int: ...
    def count_by_schema(self, dataset_id: uuid.UUID) -> dict[str, int]: ...
    def list_by_schema(
        self, schema_id: uuid.UUID, search: str | None = None, limit: int = 20
    ) -> list[RecordDTO]: ...
    def list_ids_by_schema_ids(
        self, schema_ids: list[uuid.UUID]
    ) -> list[uuid.UUID]: ...
    def list_children(self, parent_id: uuid.UUID) -> list[RecordDTO]: ...
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
    ) -> list[WorkflowJobDTO]: ...
    def count(
        self,
        status: str | None = None,
        record_id: str | None = None,
        affected_record_id: str | None = None,
    ) -> int: ...
    def get_by_id(self, job_id: uuid.UUID) -> WorkflowJobDTO | None: ...
    def count_active_for_workflow(self, workflow_name: str) -> int: ...
    def failure_counts_by_plugin(self) -> dict[str, int]: ...


@runtime_checkable
class AiUsageRepository(Protocol):
    def add(
        self, provider: str, model: str, input_tokens: int, output_tokens: int
    ) -> AiUsageEventDTO: ...
    def list_all(self, since: datetime | None = None) -> list[AiUsageEventDTO]: ...


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


@runtime_checkable
class FileObjectStore(Protocol):
    """
    Content-addressed blob store.
    Implementations: LocalFileObjectStore (_civex/objects/), future S3Store.
    """

    def put(self, data: bytes, original_filename: str) -> FileRef: ...
    def get(self, sha256: str) -> bytes: ...
    def exists(self, sha256: str) -> bool: ...
    def object_path(self, sha256: str) -> Path: ...
