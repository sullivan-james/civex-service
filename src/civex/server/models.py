"""
Pydantic models for the HTTP boundary only.
DTOs (domain/dtos.py) stay as plain dataclasses throughout the service layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from civex.domain.dtos import (
    AuditLogDTO,
    DatasetDTO,
    FieldDTO,
    RecordDTO,
    SchemaDeleteImpactDTO,
    SchemaDTO,
    WorkflowJobDTO,
)
from civex.services.ai_usage_service import TokenUsageBucket
from civex.services.analytics_service import (
    AuditEventPoint,
    DurationDistribution,
    JobStatusPoint,
    PluginFailurePoint,
    RecordCount,
    RecordGrowthPoint,
    TriggerBreakdownPoint,
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
    deleted_at: datetime | None = Field(
        default=None,
        description="When this schema was soft-deleted. Null means live.",
    )

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
            deleted_at=dto.deleted_at,
        )


class SchemaDeleteImpactResponse(BaseModel):
    child_schema_count: int = Field(
        description="Schemas that inherit from this one, directly or transitively — informational only, they are not deleted along with it, but their presence blocks a later purge."
    )
    record_count: int = Field(
        description="Records typed by this schema itself, across every collection — deleted along with it."
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
    deleted_at: datetime | None = Field(
        default=None,
        description="When this collection was soft-deleted. Null means live.",
    )

    @classmethod
    def from_dto(cls, dto: DatasetDTO) -> DatasetResponse:
        return cls(
            id=str(dto.id),
            name=dto.name,
            description=dto.description,
            record_count=dto.record_count,
            deleted_at=dto.deleted_at,
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
    deleted_at: datetime | None = Field(
        default=None,
        description="When this record was soft-deleted. Null means live.",
    )

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
            deleted_at=dto.deleted_at,
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


# --- Audit ---


class AuditLogResponse(BaseModel):
    id: str
    commit_id: str | None = Field(
        default=None,
        description="Sync commit this entry was bundled into. Null until the next push.",
    )
    action: str = Field(description="One of: create, update, delete, purge.")
    entity_type: str = Field(description="One of: record, schema, field, dataset.")
    entity_id: str
    old_data: dict[str, Any] | None = Field(
        default=None,
        description="Full entity snapshot before the change. Null on create.",
    )
    new_data: dict[str, Any] | None = Field(
        default=None,
        description="Full entity snapshot after the change. Null on delete.",
    )
    timestamp: datetime

    @classmethod
    def from_dto(cls, dto: AuditLogDTO) -> AuditLogResponse:
        return cls(
            id=str(dto.id),
            commit_id=str(dto.commit_id) if dto.commit_id else None,
            action=dto.action,
            entity_type=dto.entity_type,
            entity_id=str(dto.entity_id),
            old_data=dto.old_data,
            new_data=dto.new_data,
            timestamp=dto.timestamp,
        )


class PaginatedAuditLogResponse(BaseModel):
    items: list[AuditLogResponse]
    total: int
    offset: int
    limit: int


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


class RetentionSettingsResponse(BaseModel):
    purge_after_days: int = Field(
        description="Soft-deleted items become eligible for permanent "
        "deletion this many days after being deleted."
    )


class UpdateRetentionSettingsRequest(BaseModel):
    purge_after_days: int = Field(ge=1)


# --- Analytics ---


class RecordCountResponse(BaseModel):
    dataset: str
    schema_name: str
    count: int

    @classmethod
    def from_dto(cls, d: RecordCount) -> RecordCountResponse:
        return cls(dataset=d.dataset, schema_name=d.schema, count=d.count)


class RecordCountsResponse(BaseModel):
    items: list[RecordCountResponse]


class RecordGrowthPointResponse(BaseModel):
    bucket: str = Field(description="ISO date the bucket starts on.")
    dataset: str
    schema_name: str
    count: int

    @classmethod
    def from_dto(cls, d: RecordGrowthPoint) -> RecordGrowthPointResponse:
        return cls(
            bucket=d.bucket, dataset=d.dataset, schema_name=d.schema, count=d.count
        )


class RecordGrowthResponse(BaseModel):
    bucket: str = Field(description="Bucket size applied: day, week, or month.")
    items: list[RecordGrowthPointResponse]


class JobStatusPointResponse(BaseModel):
    bucket: str
    status: str
    count: int

    @classmethod
    def from_dto(cls, d: JobStatusPoint) -> JobStatusPointResponse:
        return cls(bucket=d.bucket, status=d.status, count=d.count)


class JobStatusCountsResponse(BaseModel):
    bucket: str
    items: list[JobStatusPointResponse]


class DurationHistogramBinResponse(BaseModel):
    label: str = Field(description="Duration bucket, e.g. '1-2s' or '30s+'.")
    count: int


class DurationPercentileMarkerResponse(BaseModel):
    label: str = Field(description="e.g. 'p50', 'p90', 'p99'.")
    bin_label: str = Field(
        description="Which histogram bucket this percentile falls in."
    )


class JobDurationStatsResponse(BaseModel):
    count: int = Field(description="Number of step executions the stats are over.")
    avg_seconds: float | None
    min_seconds: float | None
    max_seconds: float | None
    p50_seconds: float | None
    p90_seconds: float | None
    p99_seconds: float | None
    bins: list[DurationHistogramBinResponse] = Field(
        description="Duration distribution, bucketed into fixed-width ranges."
    )
    percentile_markers: list[DurationPercentileMarkerResponse] = Field(
        description="Which bucket each of p50/p90/p99 falls in, for a chart "
        "to draw as reference lines over `bins`."
    )

    @classmethod
    def from_dto(cls, d: DurationDistribution) -> JobDurationStatsResponse:
        return cls(
            count=d.stats.count,
            avg_seconds=d.stats.avg_seconds,
            min_seconds=d.stats.min_seconds,
            max_seconds=d.stats.max_seconds,
            p50_seconds=d.stats.p50_seconds,
            p90_seconds=d.stats.p90_seconds,
            p99_seconds=d.stats.p99_seconds,
            bins=[
                DurationHistogramBinResponse(label=b.label, count=b.count)
                for b in d.bins
            ],
            percentile_markers=[
                DurationPercentileMarkerResponse(label=m.label, bin_label=m.bin_label)
                for m in d.percentile_markers
            ],
        )


class PluginFailurePointResponse(BaseModel):
    bucket: str
    plugin: str
    count: int

    @classmethod
    def from_dto(cls, d: PluginFailurePoint) -> PluginFailurePointResponse:
        return cls(bucket=d.bucket, plugin=d.plugin, count=d.count)


class PluginFailureCountsResponse(BaseModel):
    bucket: str
    items: list[PluginFailurePointResponse]


class TriggerBreakdownPointResponse(BaseModel):
    trigger: str = Field(description="One of: record_created, record_updated, manual.")
    count: int

    @classmethod
    def from_dto(cls, d: TriggerBreakdownPoint) -> TriggerBreakdownPointResponse:
        return cls(trigger=d.trigger, count=d.count)


class TriggerBreakdownResponse(BaseModel):
    items: list[TriggerBreakdownPointResponse]


class AuditEventPointResponse(BaseModel):
    bucket: str
    action: str = Field(description="One of: create, update, delete, purge.")
    entity_type: str = Field(description="One of: record, schema, field, dataset.")
    count: int

    @classmethod
    def from_dto(cls, d: AuditEventPoint) -> AuditEventPointResponse:
        return cls(
            bucket=d.bucket, action=d.action, entity_type=d.entity_type, count=d.count
        )


class AuditEventCountsResponse(BaseModel):
    bucket: str
    items: list[AuditEventPointResponse]


class TokenUsageBucketResponse(BaseModel):
    bucket: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int

    @classmethod
    def from_dto(cls, d: TokenUsageBucket) -> TokenUsageBucketResponse:
        return cls(
            bucket=d.bucket,
            provider=d.provider,
            model=d.model,
            input_tokens=d.input_tokens,
            output_tokens=d.output_tokens,
        )


class AiTokenUsageResponse(BaseModel):
    bucket: str
    items: list[TokenUsageBucketResponse]
