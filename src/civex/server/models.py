"""
Pydantic models for the HTTP boundary only.
DTOs (domain/dtos.py) stay as plain dataclasses throughout the service layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from civex.domain.dtos import (
    AuditLogDTO,
    DatasetDTO,
    FieldDTO,
    NameIssue,
    RecordDTO,
    ReferrerGroupDTO,
    SchemaDeleteImpactDTO,
    SchemaDTO,
    ViewDTO,
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


class NameIssueResponse(BaseModel):
    kind: str = Field(description="'schema' or 'field'.")
    schema_name: str
    name: str
    suggestion: str | None = Field(
        default=None, description="Slugified alternative; null if undecidable."
    )

    @classmethod
    def from_dto(cls, dto: NameIssue) -> NameIssueResponse:
        return cls(
            kind=dto.kind,
            schema_name=dto.schema_name,
            name=dto.name,
            suggestion=dto.suggestion,
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


# --- Views ---


class ViewResponse(BaseModel):
    id: str
    schema_id: str
    schema_name: str
    name: str
    columns: list[str] = Field(
        description="Base schema field names to show, in order (own or "
        "inherited). May also include single-hop reference-field joins as "
        "'ref_field.target_field' (e.g. 'customer.email')."
    )
    filter_tree: dict[str, Any] | None = Field(
        default=None,
        description="AND/OR filter tree, same shape as the records 'filter' "
        "query parameter (conditions may name an ancestor or descendant "
        "schema).",
    )
    sort: list[dict[str, Any]] = Field(
        description="Ordered list of {field, direction} entries; direction "
        "is 'asc' or 'desc'."
    )

    @classmethod
    def from_dto(cls, dto: ViewDTO) -> ViewResponse:
        return cls(
            id=str(dto.id),
            schema_id=str(dto.schema_id),
            schema_name=dto.schema_name,
            name=dto.name,
            columns=dto.columns,
            filter_tree=dto.filter_tree,
            sort=dto.sort,
        )


class CreateViewRequest(BaseModel):
    name: str = Field(
        description=(
            "What the view is called, in your own words -- spaces, capitals "
            "and punctuation are fine. Only '/', '\\' and control "
            "characters are refused. Unique per schema."
        )
    )
    columns: list[str] | None = Field(
        default=None,
        description="Base schema field names to show, in order. May also "
        "include single-hop reference-field joins as 'ref_field.target_field'.",
    )
    filter_tree: dict[str, Any] | None = Field(
        default=None,
        description="AND/OR filter tree, same shape as the records 'filter' "
        "query parameter (conditions may name an ancestor or descendant "
        "schema).",
    )
    sort: list[dict[str, Any]] | None = Field(
        default=None,
        description="Ordered list of {field, direction} entries; direction "
        "is 'asc' or 'desc'.",
    )


class UpdateViewRequest(BaseModel):
    rename: str | None = Field(
        default=None, description="New name; same rules as when creating."
    )
    columns: list[str] | None = Field(
        default=None,
        description="Replace the column list; omit the key to leave it unchanged.",
    )
    filter_tree: dict[str, Any] | None = Field(
        default=None,
        description="Replace the filter tree; send null to clear it, omit "
        "the key to leave it unchanged.",
    )
    sort: list[dict[str, Any]] | None = Field(
        default=None,
        description="Replace the sort order; omit the key to leave it unchanged.",
    )


class PreviewViewRequest(BaseModel):
    columns: list[str] | None = Field(
        default=None,
        description="Same shape as a view's 'columns' -- base schema field "
        "names and/or single-hop reference-field joins. Validated the same "
        "way, but not persisted.",
    )
    filter_tree: dict[str, Any] | None = Field(
        default=None,
        description="Same shape as a view's 'filter_tree'.",
    )
    sort: list[dict[str, Any]] | None = Field(
        default=None,
        description="Same shape as a view's 'sort': the schema's own or an "
        "inherited field, each ascending or descending.",
    )
    limit: int = Field(default=50, le=1000, ge=1)
    offset: int = Field(default=0, ge=0)


class PreviewViewResponse(BaseModel):
    rows: list[dict[str, Any]] = Field(
        description="One dict per matching record, keyed by column (joined "
        "columns use the 'ref_field.target_field' key)."
    )
    total: int = Field(
        description="Total matching records regardless of 'limit'/'offset'."
    )


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
    timezone: str | None = Field(
        default=None,
        description=(
            "IANA timezone (e.g. 'America/Chicago') that datetime values in "
            "this collection are read and shown in. Null means unset: "
            "offset-less input is read as UTC and the UI uses the viewer's "
            "own zone. A datetime field's own `timezone` restriction "
            "overrides this."
        ),
    )
    scope: str = Field(
        default="local",
        description=(
            "Who may reference this collection's records: 'local' (only "
            "records in this collection) or 'global' (records in any "
            "collection)."
        ),
    )
    schemas: list[str] = Field(
        default_factory=list,
        description=(
            "Names of the schemas this collection is for. Records in it can "
            "only be of these schemas."
        ),
    )

    @classmethod
    def from_dto(cls, dto: DatasetDTO) -> DatasetResponse:
        return cls(
            id=str(dto.id),
            name=dto.name,
            description=dto.description,
            record_count=dto.record_count,
            deleted_at=dto.deleted_at,
            timezone=dto.timezone,
            scope=dto.scope,
            schemas=list(dto.schemas),
        )


class CreateDatasetRequest(BaseModel):
    name: str
    description: str | None = None
    timezone: str | None = Field(
        default=None,
        description="IANA timezone for datetime values in this collection. Omit or null to leave unset.",
    )
    scope: str = Field(
        default="local",
        description="'local' (default) or 'global' -- see the collection's `scope`.",
    )
    schemas: list[str] = Field(
        default_factory=list,
        description=(
            "Names of the schemas the collection is for. A child schema's "
            "parent schema must be listed too."
        ),
    )


class UpdateDatasetRequest(BaseModel):
    rename: str | None = None
    description: str | None = None
    timezone: str | None = Field(
        default=None,
        description=(
            "IANA timezone for datetime values in this collection. Omit or "
            "null to leave unchanged; an empty string clears it back to unset."
        ),
    )
    scope: str | None = Field(
        default=None,
        description=(
            "'local' or 'global'. Omit or null to leave unchanged. A global "
            "collection that other collections reference can't become local."
        ),
    )
    schemas: list[str] | None = Field(
        default=None,
        description=(
            "Replace the collection's schema list. Omit or null to leave "
            "unchanged. A schema with records in the collection can't be "
            "removed."
        ),
    )


# Collection aliases (user-facing rename of Dataset → Collection)
CollectionResponse = DatasetResponse
CreateCollectionRequest = CreateDatasetRequest
UpdateCollectionRequest = UpdateDatasetRequest


# --- Records ---


class RecordRef(BaseModel):
    id: str
    schema_name: str
    natural_name: str | None


class ReferrerGroupResponse(BaseModel):
    dataset_id: str = Field(description="Id of the collection the referrers live in.")
    collection: str = Field(description="Name of that collection.")
    schema_name: str = Field(
        description="Schema of the referring records; it owns the field."
    )
    field_name: str = Field(
        description="The reference field that points at the record."
    )
    dtype: str = Field(description="'reference' or 'reference_list'.")
    count: int = Field(
        description="Live records of this schema, in this collection, referencing it."
    )

    @classmethod
    def from_dto(cls, dto: ReferrerGroupDTO) -> "ReferrerGroupResponse":
        return cls(
            dataset_id=str(dto.dataset_id),
            collection=dto.dataset_name,
            schema_name=dto.schema_name,
            field_name=dto.field_name,
            dtype=dto.dtype,
            count=dto.count,
        )


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
    reference_labels: dict[str, str | None] | None = Field(
        default=None,
        description=(
            "For every reference/reference_list value on this record, the "
            "target record's id mapped to its natural_name (null if the "
            "target has none). Lets clients render a reference as a link "
            "with a readable label without a lookup per value."
        ),
    )
    collection: str | None = Field(
        default=None,
        description="Name of the collection this record lives in.",
    )
    reference_collections: dict[str, str] | None = Field(
        default=None,
        description=(
            "For reference/reference_list targets that live in a different "
            "collection (a global one), the target's id mapped to that "
            "collection's name. Targets in the record's own collection are "
            "left out."
        ),
    )
    child_counts: dict[str, int] | None = Field(
        default=None,
        description="Only when requested ('child_counts=true'): how many live "
        "child records this record has, per child schema name.",
    )
    derived: dict[str, Any] | None = Field(
        default=None,
        description="Only when 'columns' were requested: the requested "
        "columns this record's own 'data' can't answer -- fields inherited "
        "from an ancestor record, and 'ref_field.target_field' joins -- keyed "
        "by column.",
    )
    ancestors: list[RecordRef] | None = Field(
        default=None,
        description="Only on a single-record fetch: the parent chain, root "
        "first, for breadcrumbs.",
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
            reference_labels=dto.reference_labels,
            collection=dto.dataset_name,
            reference_collections=dto.reference_collections,
            child_counts=dto.child_counts,
            derived=dto.derived,
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
    available: bool = Field(
        description="True if the volume's files can be read right now (online, read-only or retired)."
    )
    state: str = Field(
        description=(
            "online, offline (path not there, e.g. drive unplugged), wrong_drive "
            "(something else is mounted there), readonly or retired."
        )
    )
    reason: str = Field(
        description="What civex expected versus what it found; empty when online."
    )
    fix: str = Field(
        description="A plain-language next step for an offline or wrong-drive volume; empty otherwise."
    )
    warning: bool
    in_queue: bool
    network: bool = Field(
        default=False, description="The volume's folder is on a network drive."
    )


class PlacementResponse(BaseModel):
    collection_id: str = Field(
        description="Id of the collection this placement is for."
    )
    collection_name: str | None = Field(
        description="The collection's name, or null if it no longer exists."
    )
    volume: str = Field(description="The collection's home volume.")
    on_unavailable: str = Field(
        description=(
            "spill: use the general write queue when the home volume can't take a "
            "file. fail: refuse the upload instead."
        )
    )


class SetPlacementRequest(BaseModel):
    volume: str = Field(description="Name of the volume that becomes the home.")
    on_unavailable: str = Field(default="spill", description="spill (default) or fail.")


class DirectoryEntryResponse(BaseModel):
    name: str
    path: str = Field(description="Absolute path of the folder.")


class FileCopyResponse(BaseModel):
    volume: str
    path: str = Field(description="Where the object is, or would be, on that volume.")
    present: bool | None = Field(
        description="True if it is there; null if it is recorded there but the volume can't be checked now."
    )
    state: str = Field(
        description="The volume's state: online, offline, wrong_drive, readonly or retired."
    )
    network: bool = Field(description="The volume is on a network drive.")


class CollectionUseResponse(BaseModel):
    id: str
    name: str | None = Field(description="Null if the collection no longer exists.")
    records: int = Field(description="Records in that collection that use the file.")


class FileInfoResponse(BaseModel):
    sha256: str
    size: int | None = Field(description="Size in bytes, if known.")
    copies: list[FileCopyResponse] = Field(
        description="Every place the content is, or is recorded to be."
    )
    records: int = Field(
        description="Records that use this file, across all collections."
    )
    jobs: int = Field(description="Workflow runs that took it as an input.")
    collections: list[CollectionUseResponse]


class StorageLocationResponse(BaseModel):
    label: str
    path: str
    kind: str = Field(description="project, home or drive.")
    free_bytes: int | None = Field(
        description="Free space; null if unknown, and not read for network drives."
    )
    total_bytes: int | None
    network: bool = Field(description="True for a drive that lives on another machine.")
    source: str | None = Field(
        description="Where a network drive really lives, e.g. nas:/export."
    )


class DirectoryListingResponse(BaseModel):
    path: str = Field(description="The folder that was listed, as an absolute path.")
    parent: str | None = Field(description="Its parent folder; null at the top.")
    entries: list[DirectoryEntryResponse] = Field(
        description="The folders directly inside it (never files)."
    )
    truncated: bool = Field(
        description="True if there were more folders than are shown."
    )
    locations: list[StorageLocationResponse] = Field(
        description="Places to start browsing from: the project, home and mounted drives."
    )
    hint: str | None = Field(
        default=None,
        description=(
            "Why a drive might be missing from `locations`, where the platform has a "
            "known reason (for example a Windows drive not yet mounted under WSL)."
        ),
    )


class PathInspectionResponse(BaseModel):
    path: str
    exists: bool
    is_dir: bool
    writable: bool
    will_create: bool = Field(
        description="The folder doesn't exist and would be created."
    )
    inside_project: bool
    same_disk_as_project: bool | None
    free_bytes: int | None
    total_bytes: int | None
    existing_volume: str | None = Field(
        description="The configured volume already at this path, if any."
    )
    marker_volume: str | None = Field(
        description="The configured volume whose drive this is, if any."
    )
    has_civex_data: bool
    is_network: bool = Field(description="The folder is on a network filesystem.")
    problems: list[str] = Field(description="Reasons it can't be added as a volume.")
    warnings: list[str] = Field(
        description="Things to know; they don't block adding it."
    )


class CreateFolderRequest(BaseModel):
    parent: str = Field(description="Absolute path of the folder to create it in.")
    name: str = Field(description="Name of the new folder (no slashes).")


class CreateFolderResponse(BaseModel):
    path: str


class CollectionVolumeShareResponse(BaseModel):
    volume: str
    files: int = Field(description="Files of the collection on this volume.")
    bytes: int
    shared_files: int = Field(
        description="Of those, files another collection uses too (moving one affects both)."
    )
    state: str = Field(
        description="The volume's state now: online, offline, wrong_drive, readonly or retired."
    )
    available: bool = Field(description="Whether the volume can be read right now.")


class CollectionStorageResponse(BaseModel):
    collection_id: str
    files: int = Field(description="Distinct files the collection's records use.")
    bytes: int = Field(description="Total size of the files the catalog knows.")
    volumes: list[CollectionVolumeShareResponse] = Field(
        description="Each volume that holds some of them, largest first."
    )
    unlocated_files: int = Field(
        description="Files records use that the catalog doesn't place on any volume."
    )


class TransferRequest(BaseModel):
    kind: str = Field(
        description="drain: move everything off the `sources` volumes. consolidate: move the files of the `collection_ids` collections."
    )
    targets: list[str] = Field(
        description="Volumes to put the files on, in order of preference: a file goes to the first that is usable and has room."
    )
    sources: list[str] = Field(
        default_factory=list, description="drain: the volumes to empty."
    )
    collection_ids: list[str] = Field(
        default_factory=list, description="consolidate: ids of the collections to move."
    )
    include_shared: bool = Field(
        default=False,
        description=(
            "consolidate: also move files that collections kept on a different "
            "volume use as well. They stay where they are by default, since moving "
            "one would only split those collections instead."
        ),
    )
    verify: str = Field(
        default="copy",
        description=(
            "copy: each file is hashed as it is copied and must match its recorded "
            "hash. full: the copy is also read back and hashed (about twice the reading)."
        ),
    )
    freeze_sources: bool = Field(
        default=True,
        description=(
            "drain: make the sources read-only while it runs, so new uploads don't "
            "keep landing on them, and put them back afterwards."
        ),
    )


class TargetShareResponse(BaseModel):
    volume: str
    files: int = Field(description="About how many files would go to this target.")
    bytes: int
    free_bytes: int | None = Field(
        description="Room the target has; null if it can't be read now."
    )


class TransferPlanResponse(BaseModel):
    files: int = Field(
        description="Files that would be moved (from the catalog, so close, not exact)."
    )
    bytes: int
    already_there: int = Field(description="Files already on a target, left alone.")
    shared_left: int = Field(
        description="consolidate: files left because collections kept elsewhere use them too."
    )
    shared_left_bytes: int
    targets: list[TargetShareResponse]
    problems: list[str] = Field(description="Reasons the transfer can't start.")
    warnings: list[str] = Field(description="Things worth knowing; they don't stop it.")
    can_proceed: bool


class TransferProgressResponse(BaseModel):
    files_total: int
    files_done: int
    files_skipped: int = Field(description="Already on a target.")
    files_failed: int
    bytes_total: int
    bytes_done: int
    current: str | None = Field(
        description="The file being copied (a hash prefix), if any."
    )
    current_bytes: int = Field(
        description="Bytes of the current file copied so far; add to bytes_done for a smooth bar."
    )
    current_total: int
    rate_bytes_per_second: float
    eta_seconds: float | None
    message: str


class TransferFailureResponse(BaseModel):
    sha256: str
    volume: str = Field(description="Where the file is (and stays).")
    reason: str


class TransferResponse(BaseModel):
    id: str
    kind: str
    status: str = Field(
        description="running, paused, completed, failed, cancelled or interrupted (the process died; resumable)."
    )
    spec: TransferRequest
    plan: TransferPlanResponse | None
    progress: TransferProgressResponse
    failures: list[TransferFailureResponse] = Field(
        description="Files that couldn't be moved (the first few hundred)."
    )
    failures_total: int
    pause_reason: str | None
    auto_resume: bool = Field(
        description="Paused only because a volume stopped answering, and will carry on by itself when it does."
    )
    error: str | None
    control: str | None = Field(
        description="A pause or cancel asked for and not yet acted on."
    )
    frozen: dict[str, str] = Field(
        description="Volumes made read-only for the duration, and what each was before."
    )
    live: bool = Field(description="Running on a thread of this server right now.")
    created_at: str | None
    started_at: str | None
    finished_at: str | None
    updated_at: str | None


class AddVolumeRequest(BaseModel):
    name: str
    path: str
    allocated_gb: float | None = None
    add_to_queue: bool = Field(
        default=False,
        description=(
            "Also put the volume in the general write queue. Leave false for a "
            "volume that only homes particular collections."
        ),
    )


class UpdateVolumeRequest(BaseModel):
    path: str | None = None
    allocated_gb: float | None = None
    clear_allocation: bool = False
    state: str | None = Field(
        default=None,
        description="active, readonly (readable, never written to) or retired.",
    )


class SetQueueRequest(BaseModel):
    queue: list[str]


class GCRequest(BaseModel):
    apply: bool = Field(
        default=False,
        description="Actually delete collectible objects. False (default) only reports what would be deleted.",
    )
    grace_days: int = Field(
        default=14,
        ge=0,
        description="Skip unreferenced objects written more recently than this many days.",
    )
    rebuild_refs: bool = Field(
        default=False,
        description="Recompute the file-reference table from every record and job before collecting. Normally unnecessary; use if the table may have drifted.",
    )


class StoredObjectResponse(BaseModel):
    sha256: str = Field(description="Content hash identifying the object.")
    volume: str = Field(description="Volume the object was found on.")
    size: int = Field(description="Object size in bytes.")
    mtime: float = Field(description="Unix timestamp the object was written.")


class GCReportResponse(BaseModel):
    dry_run: bool = Field(description="True if no objects were actually deleted.")
    grace_days: int
    scanned: int = Field(description="Total objects found in the store.")
    referenced: int = Field(
        description="Distinct content hashes reachable from a live record or workflow job."
    )
    protected_by_grace: int = Field(
        description="Unreferenced objects skipped for being younger than the grace period."
    )
    deleted_count: int = Field(
        description="Objects deleted (or, if dry_run, collectible)."
    )
    deleted_bytes: int
    deleted: list[StoredObjectResponse]
    stale_scratch_removed: int = Field(
        description="Abandoned upload scratch files (from an interrupted "
        "streamed upload) removed, or if dry_run, collectible."
    )


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


class MoveTargetRequest(BaseModel):
    kind: Literal["sqlite", "docker", "postgres"] = Field(
        description=(
            "Where to move to: 'sqlite' (a new file in the project), 'docker' "
            "(this project's Civex-managed PostgreSQL container) or 'postgres' "
            "(a PostgreSQL server you run)."
        )
    )
    url: str | None = Field(
        default=None,
        description="Full connection URL, for kind 'postgres' (instead of the fields below).",
    )
    path: str | None = Field(
        default=None,
        description="File to create, for kind 'sqlite'. Defaults to a new file in _civex/.",
    )
    host: str | None = Field(
        default=None, description="Server host, for kind 'postgres'."
    )
    port: int = Field(default=5432, description="Server port, for kind 'postgres'.")
    database: str | None = Field(
        default=None, description="Database name, for kind 'postgres'."
    )
    user: str | None = Field(
        default=None, description="User name, for kind 'postgres'."
    )
    password: str | None = Field(
        default=None, description="Password, for kind 'postgres'."
    )


class ConnectionCheckResponse(BaseModel):
    ok: bool = Field(description="Whether a connection was made.")
    error: str | None = Field(
        default=None, description="Why not, in plain words, when ok is false."
    )


class DatabaseSummaryResponse(BaseModel):
    label: str = Field(
        description="'SQLite file', 'Docker PostgreSQL' or 'PostgreSQL server'."
    )
    dialect: str = Field(description="'sqlite' or 'postgresql'.")
    location: str = Field(description="Where it is, with any password hidden.")
    reachable: bool = Field(description="Whether it could be read.")
    error: str | None = Field(default=None, description="Why not, when unreachable.")
    records: int = Field(description="Number of records.")
    rows: int = Field(description="Rows across every table.")
    size_bytes: int | None = Field(
        default=None, description="On-disk size, when known."
    )


class MovePreflightResponse(BaseModel):
    source: DatabaseSummaryResponse = Field(description="The database now in use.")
    target: DatabaseSummaryResponse = Field(description="The destination.")
    target_label: str = Field(description="Kind of destination, for display.")
    can_proceed: bool = Field(description="False when `problems` is not empty.")
    problems: list[str] = Field(description="Reasons the move can't go ahead.")
    warnings: list[str] = Field(description="Things worth knowing that don't block it.")
    estimate_seconds: int = Field(description="Rough time the copy will take.")


class MoveProgressResponse(BaseModel):
    phase: str = Field(description="'copy', 'verify' or 'finalize'.")
    table: str | None = Field(default=None, description="Table being copied.")
    rows_done: int = Field(description="Rows copied so far.")
    rows_total: int = Field(description="Rows to copy in all.")
    tables_done: int = Field(description="Tables finished.")
    tables_total: int = Field(description="Tables to copy.")
    message: str = Field(description="What it is doing, for display.")


class MoveRecordResponse(BaseModel):
    id: str = Field(description="Identifier of the move.")
    started_at: str = Field(description="When it started (ISO 8601).")
    finished_at: str | None = Field(default=None, description="When it ended.")
    status: Literal["running", "done", "failed", "cancelled"] = Field(
        description="Outcome. Only 'done' means the project now uses the new database."
    )
    source_label: str = Field(description="Kind of database moved from.")
    source_location: str = Field(description="Where it was, password hidden.")
    target_label: str = Field(description="Kind of database moved to.")
    target_location: str = Field(description="Where it is, password hidden.")
    seconds: float | None = Field(default=None, description="How long the copy took.")
    counts: dict[str, int] = Field(description="Rows copied per table.")
    error: str | None = Field(default=None, description="Why it didn't finish.")
    problems: list[str] = Field(
        description="What didn't match, if verification failed."
    )
    reverted_at: str | None = Field(
        default=None, description="When it was undone, if it was."
    )


class MoveJobResponse(BaseModel):
    id: str = Field(description="Job id to poll.")
    status: Literal["running", "done", "failed", "cancelled"] = Field(
        description="State of the move."
    )
    progress: MoveProgressResponse = Field(description="Latest progress.")
    error: str | None = Field(
        default=None, description="Why it failed or was cancelled."
    )
    record: MoveRecordResponse | None = Field(
        default=None, description="The history entry, once the move has ended."
    )


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


class MapSettingsResponse(BaseModel):
    tile_url: str | None = Field(
        description=(
            "XYZ tile URL for the location editor's street-level map, with "
            "{z}, {x} and {y} placeholders. Null means the editor uses only "
            "its bundled coastlines."
        )
    )
    attribution: str | None = Field(
        description="Credit shown on the map for the tile provider, as plain text."
    )


class UpdateMapSettingsRequest(BaseModel):
    tile_url: str | None = Field(
        description="XYZ tile URL (http or https, with {z}, {x}, {y}), or null to clear."
    )
    attribution: str | None = Field(
        default=None, description="Plain-text credit for the provider, or null."
    )


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


class RestrictionDescriptorResponse(BaseModel):
    key: str = Field(description="Key in a field's `restrictions` dict.")
    label: str = Field(description="Name shown beside the control.")
    control: str = Field(
        description=(
            "Which editor to show: number, integer, bytes, choices, accept, "
            "filename_template, schema, timezone, date_bound, datetime_bound, "
            "unit, precision, geometry_types or bbox."
        )
    )
    help: str = Field(description="One sentence of guidance; may be empty.")


class FieldTypeDescriptorResponse(BaseModel):
    type: str = Field(description="The field type name, as used in `type`.")
    label: str = Field(description="Plain-language name of the type.")
    description: str = Field(description="What the type is for.")
    stored_as: str = Field(description="How a value is held, in plain language.")
    entry_hint: str = Field(
        description="One line of guidance shown beside the input on the record page."
    )
    example: str = Field(description="An example value as a person would type it.")
    restrictions: list[RestrictionDescriptorResponse] = Field(
        description="The rules a field of this type can carry, in display order."
    )
    supports_default: bool = Field(
        description="Whether a default value can be set when creating the field."
    )


class FieldKindResponse(BaseModel):
    key: str = Field(description="Stable identifier of the kind.")
    label: str = Field(description="Name shown in the field-kind picker.")
    type: str = Field(description="The field type a field of this kind is created as.")
    description: str = Field(description="What the kind is for.")
    focus: str | None = Field(
        description="Restriction key the editor should lead with, if any."
    )


class FieldTypesResponse(BaseModel):
    types: list[FieldTypeDescriptorResponse] = Field(
        description="Every field type, with the rules each can carry."
    )
    kinds: list[FieldKindResponse] = Field(
        description="The 'what kind of data is this?' picker, in display order."
    )

    @classmethod
    def build(cls) -> FieldTypesResponse:
        from dataclasses import asdict

        from civex.domain.field_descriptors import FIELD_KINDS, FIELD_TYPES

        return cls(
            types=[
                FieldTypeDescriptorResponse.model_validate(asdict(d))
                for d in FIELD_TYPES.values()
            ],
            kinds=[FieldKindResponse.model_validate(asdict(k)) for k in FIELD_KINDS],
        )
