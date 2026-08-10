"""
Pydantic models for the HTTP boundary only.
DTOs (domain/dtos.py) stay as plain dataclasses throughout the service layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from civex.domain.dtos import (
    DatasetDTO,
    FieldDTO,
    RecordDTO,
    SchemaDeleteImpactDTO,
    SchemaDTO,
    WorkflowJobDTO,
)


# --- Schemas ---


class FieldResponse(BaseModel):
    id: str
    name: str
    label: str | None = Field(
        default=None,
        description=(
            "Human-facing display name. Null means none was set — render "
            "the name title-cased instead."
        ),
    )
    type: str
    required: bool
    restrictions: dict[str, Any] = {}
    default: Any | None = None

    @classmethod
    def from_dto(cls, dto: FieldDTO) -> FieldResponse:
        return cls(
            id=str(dto.id),
            name=dto.name,
            label=dto.label,
            type=dto.dtype,
            required=dto.required,
            restrictions=dto.restrictions,
            default=dto.default_value,
        )


class SchemaResponse(BaseModel):
    id: str
    name: str
    label: str | None = Field(
        default=None,
        description=(
            "Human-facing display name. Null means none was set — render "
            "the name title-cased instead."
        ),
    )
    description: str | None
    parent_id: str | None
    display_fields: list[str]
    fields: list[FieldResponse]

    @classmethod
    def from_dto(cls, dto: SchemaDTO) -> SchemaResponse:
        return cls(
            id=str(dto.id),
            name=dto.name,
            label=dto.label,
            description=dto.description,
            parent_id=str(dto.parent_id) if dto.parent_id else None,
            display_fields=dto.display_fields,
            fields=[FieldResponse.from_dto(f) for f in dto.fields],
        )


class SchemaDeleteImpactResponse(BaseModel):
    child_schema_count: int = Field(
        description="Schemas that inherit from this one, directly or transitively — they are deleted along with it."
    )
    record_count: int = Field(
        description="Records of this schema, a descendant schema, or nested under one of those records — all deleted along with it."
    )

    @classmethod
    def from_dto(cls, dto: SchemaDeleteImpactDTO) -> SchemaDeleteImpactResponse:
        return cls(
            child_schema_count=dto.child_schema_count, record_count=dto.record_count
        )


class AddFieldRequest(BaseModel):
    name: str = Field(
        description=(
            "Machine key: lowercase letters, digits and underscores, not "
            "starting with a digit. This is what workflows and CSV headers "
            "reference."
        )
    )
    label: str | None = Field(
        default=None,
        description="Optional human-facing display name; free text.",
    )
    type: str
    required: bool = False
    restrictions: dict[str, Any] | None = None
    default: Any | None = None


class CreateSchemaRequest(BaseModel):
    name: str = Field(
        description=(
            "Machine key: lowercase letters, digits and underscores, not "
            "starting with a digit."
        )
    )
    label: str | None = Field(
        default=None,
        description="Optional human-facing display name; free text.",
    )
    description: str | None = None
    parent: str | None = None
    fields: list[AddFieldRequest] | None = None


class UpdateSchemaRequest(BaseModel):
    rename: str | None = None
    label: str | None = Field(
        default=None,
        description=(
            "New display name. Send an empty string to clear it and fall "
            "back to the derived label; omit the key to leave it unchanged."
        ),
    )
    description: str | None = None
    display_fields: list[str] | None = None


class UpdateFieldRequest(BaseModel):
    rename: str | None = None
    label: str | None = Field(
        default=None,
        description=(
            "New display name. Send an empty string to clear it and fall "
            "back to the derived label; omit the key to leave it unchanged."
        ),
    )
    required: bool | None = None
    restrictions: dict[str, Any] | None = None
    default: Any | None = None


class ReorderFieldsRequest(BaseModel):
    order: list[str]  # list of field UUIDs as strings


# --- Datasets ---


class DatasetResponse(BaseModel):
    id: str
    name: str
    description: str | None
    record_count: int

    @classmethod
    def from_dto(cls, dto: DatasetDTO) -> DatasetResponse:
        return cls(
            id=str(dto.id),
            name=dto.name,
            description=dto.description,
            record_count=dto.record_count,
        )


class CreateDatasetRequest(BaseModel):
    name: str
    description: str | None = None


class UpdateDatasetRequest(BaseModel):
    rename: str | None = None
    description: str | None = None


# Collection aliases (user-facing rename of Dataset → Collection)
CollectionResponse = DatasetResponse
CreateCollectionRequest = CreateDatasetRequest
UpdateCollectionRequest = UpdateDatasetRequest


# --- Records ---


class RecordResponse(BaseModel):
    id: str
    dataset_id: str
    schema_name: str
    parent_record_id: str | None
    data: dict[str, Any]
    natural_name: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dto(cls, dto: RecordDTO) -> RecordResponse:
        return cls(
            id=str(dto.id),
            dataset_id=str(dto.dataset_id),
            schema_name=dto.schema_name,
            parent_record_id=str(dto.parent_record_id)
            if dto.parent_record_id
            else None,
            data=dto.data,
            natural_name=dto.natural_name,
            created_at=dto.created_at,
            updated_at=dto.updated_at,
        )


class PaginatedRecordResponse(BaseModel):
    items: list[RecordResponse]
    total: int
    offset: int
    limit: int


class CreateRecordRequest(BaseModel):
    schema_name: str
    data: dict[str, Any] = {}
    parent_record_id: str | None = None


class UpdateRecordRequest(BaseModel):
    data: dict[str, Any]


# --- Files ---


class FileRefResponse(BaseModel):
    sha256: str
    filename: str
    size: int
    volume: str = "default"


class VolumeStatsResponse(BaseModel):
    name: str
    path: str
    allocated_gb: float | None
    civex_used_bytes: int | None
    disk_free_bytes: int | None
    disk_total_bytes: int | None
    available: bool
    warning: bool
    in_queue: bool


class AddVolumeRequest(BaseModel):
    name: str
    path: str
    allocated_gb: float | None = None


class UpdateVolumeRequest(BaseModel):
    path: str | None = None
    allocated_gb: float | None = None
    clear_allocation: bool = False


class SetQueueRequest(BaseModel):
    queue: list[str]


# --- Workflows ---


class WorkflowInputResponse(BaseModel):
    type: str
    label: str | None
    description: str | None


class WorkflowResponse(BaseModel):
    name: str
    description: str | None
    steps: int
    filename: str
    stem: str
    record_schema: str | None = None
    inputs: dict[str, WorkflowInputResponse] | None = None


class WorkflowTriggerResponse(BaseModel):
    schema_name: str
    fields: list[str] | None = None


# Readable-summary counterpart to the raw YAML `content` — lets the UI
# render steps/inputs/outputs without parsing YAML client-side.
class WorkflowStepResponse(BaseModel):
    id: str
    plugin: str
    config: dict
    inputs: dict[str, str]  # input_name -> "step_id.output_name"
    condition: str | None = None


class WorkflowDetailResponse(BaseModel):
    name: str
    description: str | None
    steps: int
    filename: str
    stem: str
    record_schema: str | None = None
    inputs: dict[str, WorkflowInputResponse] | None = None
    content: str  # raw YAML
    step_list: list[WorkflowStepResponse] = []
    triggers: dict[str, WorkflowTriggerResponse] | None = None


class WorkflowSaveRequest(BaseModel):
    content: str  # raw YAML


# --- Jobs ---


class WorkflowJobResponse(BaseModel):
    id: str
    workflow_name: str
    record_id: str
    schema_name: str
    trigger: str
    status: str
    error: str | None
    # Structured {kind, message, retryable, step} for a failed job
    # (CIVEX-143); null for jobs that succeeded or predate it.
    error_details: dict | None
    log: str | None
    # Per-step execution records (CIVEX-117): [{step_id, plugin, status,
    # inputs, outputs, duration_seconds, error}, ...] in execution order;
    # null for jobs still pending/running or that predate this field.
    step_executions: list[dict] | None
    # Records this run created or updated: [{record_id, schema_name,
    # natural_name, action}, ...] in touch order; null for jobs still
    # pending/running or that predate this field.
    affected_records: list[dict] | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def from_dto(cls, dto: WorkflowJobDTO) -> WorkflowJobResponse:
        return cls(
            id=str(dto.id),
            workflow_name=dto.workflow_name,
            record_id=str(dto.record_id),
            schema_name=dto.schema_name,
            trigger=dto.trigger,
            status=dto.status,
            error=dto.error,
            error_details=dto.error_details,
            log=dto.log,
            step_executions=dto.step_executions,
            affected_records=dto.affected_records,
            created_at=dto.created_at,
            started_at=dto.started_at,
            finished_at=dto.finished_at,
        )


# --- Status ---


class DBStatusResponse(BaseModel):
    ok: bool = True


# --- Database management ---


class MigrationStatusResponse(BaseModel):
    current_revision: str | None
    head_revision: str | None
    up_to_date: bool
    error: str | None = None


class DockerStatusResponse(BaseModel):
    name: str
    exists: bool
    running: bool
    volume_exists: bool


class DbStatusResponse(BaseModel):
    url: str
    dialect: str
    docker_managed: bool
    migration: MigrationStatusResponse
    docker: DockerStatusResponse | None


class SetDbUrlRequest(BaseModel):
    url: str


# --- Legal ---


class LicenseResponse(BaseModel):
    text: str


class PolicyResponse(BaseModel):
    stem: str
    title: str
    content: str


# --- UI settings ---


class UISettingsResponse(BaseModel):
    show_advanced: bool


class UpdateUISettingsRequest(BaseModel):
    show_advanced: bool
