"""
Pydantic models for the HTTP boundary only.
DTOs (domain/dtos.py) stay as plain dataclasses throughout the service layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from civex.domain.dtos import (
    AuditBatchDTO,
    AuditEventDTO,
    AuditLogDTO,
    DatasetDTO,
    FieldDTO,
    NameIssue,
    RecordDTO,
    ReferrerGroupDTO,
    RestoreAllPlanDTO,
    RestoreAllResultDTO,
    RestorePlanDTO,
    RetentionReportDTO,
    RevertPlanDTO,
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
    display_template: str | None = Field(
        default=None,
        description=(
            "Template that names this schema's records; fields in braces, "
            "formats after a colon. Null means the first plain value is used."
        ),
    )
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
            display_template=dto.display_template,
            fields=[FieldResponse.from_dto(f) for f in dto.fields],
            deleted_at=dto.deleted_at,
        )


class PreviewNameRequest(BaseModel):
    template: str = Field(
        description="The template to try, e.g. '{site}-{taken_on:YYYY-MM}'."
    )
    values: dict[str, Any] = Field(
        default_factory=dict,
        description="Field values (keyed by field name) of the sample record to render against.",
    )
    kind: Literal["record", "file"] = Field(
        default="record",
        description=(
            "'record' renders a record's name; 'file' renders a download name, "
            "where `{ext}` is available and a blank value makes the result null."
        ),
    )


class PreviewNameResponse(BaseModel):
    name: str | None = Field(
        description="The rendered text, or null when the template renders to nothing."
    )
    error: str | None = Field(
        default=None, description="Why the template is not valid, if it is not."
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
    display_template: str | None = Field(
        default=None,
        description=(
            "Template that names the schema's records. Send an empty string "
            "to clear it; omit the key to leave it unchanged."
        ),
    )


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


class RestoreSelectedRequest(BaseModel):
    ids: list[str] = Field(
        max_length=5000, description="The deleted records to restore."
    )
    with_parents: bool = Field(
        default=True,
        description="Also restore the deleted records above a chosen one, each "
        "by itself. Without it, a record under a deleted record is left.",
    )


class RestoreSelectedResponse(BaseModel):
    restored: int = Field(description="Chosen records that came back.")
    came_back: int = Field(
        description="Records live again in all, counting the parents brought back."
    )
    left: int = Field(description="Chosen records still deleted, and why not.")


class RecordLabelsRequest(BaseModel):
    ids: list[str] = Field(
        max_length=200,
        description="Record ids to look up. Anything that isn't a record is skipped.",
    )


class RecordLabelResponse(BaseModel):
    id: str
    schema_name: str = Field(description="The record's schema.")
    natural_name: str | None = Field(
        description=(
            "The record's name as it is now: its schema's display template "
            "applied to its current values. Null when nothing in it can name it."
        )
    )
    deleted: bool = Field(
        description="True for a record in Recently Deleted (it can still be restored)."
    )
    deleted_at: datetime | None = Field(
        default=None, description="When it was deleted; null for a live record."
    )


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


class DeletedFieldValue(BaseModel):
    id: str = Field(description="The deleted field's id.")
    name: str
    label: str = Field(description="Its display name.")
    dtype: str
    schema_name: str = Field(
        description="The schema it was defined on, which is where to restore it."
    )
    deleted_at: datetime | None = Field(
        default=None, description="When the field was deleted."
    )
    value: Any = Field(
        description="What this record still holds for it; back in `data` once "
        "the field is restored."
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
    deleted_fields: list[DeletedFieldValue] | None = Field(
        default=None,
        description="Values this record still holds for fields that have been "
        "deleted from its schema. Nothing is lost: restoring the field "
        "(`POST /schemas/{schema_name}/fields/{id}/restore`) puts each back in "
        "`data`. Null when there are none.",
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
            deleted_fields=[DeletedFieldValue(**d) for d in dto.deleted_fields]
            if dto.deleted_fields
            else None,
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
    unused_files: int = Field(
        default=0,
        description="Files on the volume that nothing uses; garbage collection can reclaim them.",
    )
    unused_bytes: int = 0
    history_files: int = Field(
        default=0,
        description="Files kept only because a workflow run took them as an input.",
    )
    history_bytes: int = 0
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
    volume: str | None = Field(
        default=None,
        description="Only collect objects stored on this volume. Omit to clean up every volume.",
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
    volume: str | None = Field(
        default=None,
        description="The volume this pass was limited to, or null for every volume.",
    )
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
    depth: int = Field(
        default=0,
        description=(
            "How many workflow-triggered-by-workflow hops deep this run is: 0 for "
            "a run started by a person or an ordinary edit, 1 for a run started "
            "by another run's save, and so on."
        ),
    )
    trigger_detail: dict | None = Field(
        default=None,
        description=(
            "What caused the run. `changes` lists each field that changed, with a "
            "short `before` and `after` and whether the workflow was `watched` "
            "for it. `caused_by` is {job_id, workflow} when another run's own "
            "save started this one, else null. Null for a run started by hand."
        ),
    )

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
            depth=dto.depth,
            trigger_detail=dto.trigger_detail,
        )


class RerunJobsRequest(BaseModel):
    ids: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="Ids of the runs to repeat. Each is queued as a new run.",
    )
    filter: dict[str, Any] | None = Field(
        default=None,
        description="Instead of ids: repeat every run this filter matches (the "
        "same filter tree as GET /jobs, at most 1000 runs).",
    )


class SkippedJob(BaseModel):
    id: str
    reason: str = Field(description="Why this run could not be repeated.")


class RerunJobsResponse(BaseModel):
    started: list[WorkflowJobResponse] = Field(
        description="The new runs that were queued, in the order asked."
    )
    skipped: list[SkippedJob] = Field(
        description="Runs that could not be repeated, such as one whose record "
        "has since been deleted."
    )


class RunManyRequest(BaseModel):
    record_ids: list[str] = Field(
        min_length=1,
        max_length=500,
        description="Ids of the records to run the workflow on, one run each.",
    )


class RunManyResponse(BaseModel):
    started: list[WorkflowJobResponse] = Field(
        description="The runs that were queued, in the order asked."
    )
    skipped: list[SkippedJob] = Field(
        description="Records the workflow was not run on, each with why: not "
        "found, or not the schema the workflow is for."
    )


class BatchResponse(BaseModel):
    total: int = Field(
        description="Every run in the current stretch of work: those finished "
        "since the queue was last empty, plus those still waiting or running."
    )
    active: int = Field(description="Of those, waiting or running.")
    completed: int = Field(description="Of those, finished successfully.")
    failed: int = Field(description="Of those, failed.")
    cancelled: int = Field(description="Of those, cancelled.")
    started_at: datetime = Field(
        description="When the earliest run in this stretch was queued."
    )


class RunFieldResponse(BaseModel):
    name: str
    label: str
    type: str = Field(description="string, enum, integer or datetime.")
    description: str
    choices: list[str] | None = Field(
        default=None, description="Fixed choices, when there are any."
    )
    operators: list[str] = Field(description="Operators a condition on it accepts.")


class FailureGroupResponse(BaseModel):
    workflow: str
    kind: str | None = Field(description="The failure type, such as timeout.")
    step: str | None = Field(description="The step that failed.")
    message: str | None = Field(description="The failure's own message.")
    count: int = Field(description="How many runs failed this way.")
    last_at: datetime = Field(description="When one last did.")


class AutomationStatusResponse(BaseModel):
    paused: bool = Field(
        description=(
            "True while automation is paused: triggers start nothing, waiting "
            "runs are not picked up, and manual runs are refused."
        )
    )
    pending: int = Field(description="Runs waiting to start.")
    running: int = Field(description="Runs in progress.")
    cancelled: int = Field(
        default=0,
        description="How many runs the call just cancelled (stop only).",
    )
    batch: BatchResponse | None = Field(
        default=None,
        description="The current stretch of work with how many have succeeded and "
        "failed so far; null when nothing is waiting or running.",
    )


# --- Audit ---


class AuditChange(BaseModel):
    field: str = Field(
        description="The field (record entries) or attribute (everything else) "
        "that changed, by name."
    )
    label: str | None = Field(
        default=None,
        description="The field's display name now; null when it has since been "
        "renamed or deleted, or for a non-record entry.",
    )
    dtype: str | None = Field(
        default=None, description="The field's type, when it still exists."
    )
    before: Any = Field(default=None, description="The value before; null if unset.")
    after: Any = Field(default=None, description="The value after; null if unset.")
    deleted: dict[str, Any] | None = Field(
        default=None,
        description="Set when this field has since been deleted: status "
        "(deleted = can still be restored, gone = permanently deleted), its id "
        "and, for a deleted one, the schema to restore it on and when it was "
        "deleted.",
    )


class AuditNow(BaseModel):
    kind: str = Field(
        description="What the entry is about: record, collection, schema or field."
    )
    status: str = Field(
        description="live (it exists), deleted (in Recently Deleted, restorable) "
        "or gone (permanently deleted)."
    )
    ref: str | None = Field(
        default=None,
        description="What to restore or purge it by: a record's or field's id, "
        "else its name.",
    )
    name: str | None = Field(default=None, description="Its name now.")
    schema_name: str | None = Field(
        default=None,
        description="Its schema (for a field, the schema it belongs to); known "
        "even for a record that is gone for good.",
    )
    collection: str | None = Field(default=None, description="The collection it is in.")
    deleted_at: datetime | None = None


class AuditLogResponse(BaseModel):
    id: str
    action: str = Field(description="One of: create, update, delete, restore, purge.")
    actor: str | None = Field(
        default=None,
        description="Who made the change, as reported by the machine that made "
        "it (the operating-system user). Not verified. Null for entries from "
        "before this was recorded.",
    )
    entity_type: str = Field(
        description="One of: record, schema, field, dataset, view."
    )
    entity_id: str
    old_data: dict[str, Any] | None = Field(
        default=None,
        description="Full entity snapshot before the change, as stored. A record's "
        "values are keyed by field id, so an entry survives a rename; `changes` "
        "has them by current name. Null on create.",
    )
    new_data: dict[str, Any] | None = Field(
        default=None,
        description="Full entity snapshot after the change, as stored (see "
        "`old_data`). Null on delete.",
    )
    changes: list[AuditChange] = Field(
        default_factory=list,
        description="What the entry changed, field by field, in schema order. "
        "A delete or purge lists the values that were lost; a restore lists "
        "nothing.",
    )
    now: AuditNow | None = Field(
        default=None,
        description="Where the record this entry is about is now, so a lost one "
        "can be told from one that was edited, deleted or purged.",
    )
    timestamp: datetime

    @classmethod
    def from_dto(cls, dto: AuditLogDTO) -> AuditLogResponse:
        return cls(
            id=str(dto.id),
            action=dto.action,
            actor=dto.actor,
            entity_type=dto.entity_type,
            entity_id=str(dto.entity_id),
            old_data=dto.old_data,
            new_data=dto.new_data,
            changes=[AuditChange(**c) for c in dto.changes],
            now=AuditNow(**dto.now) if dto.now else None,
            timestamp=dto.timestamp,
        )


class AuditBatchResponse(BaseModel):
    id: str
    kind: str = Field(description="import, delete, restore, purge or workflow.")
    label: str | None = Field(
        default=None, description="A workflow's name or an import's file."
    )
    ref: str | None = Field(
        default=None, description="What started it, e.g. a workflow run's id."
    )
    created_at: datetime

    @classmethod
    def from_dto(cls, dto: AuditBatchDTO) -> AuditBatchResponse:
        return cls(**dto.to_dict())


class AuditPart(BaseModel):
    entity_type: str
    action: str
    count: int


class AuditEventResponse(BaseModel):
    id: str = Field(description="The entry's id, or the batch's.")
    kind: str = Field(description="entry (a single change) or batch.")
    timestamp: datetime = Field(description="The latest change in it.")
    count: int = Field(description="Changes in it that match the filters.")
    entry: AuditLogResponse | None = Field(
        default=None, description="The change itself, for kind=entry."
    )
    batch: AuditBatchResponse | None = Field(
        default=None, description="What the batch was, for kind=batch."
    )
    parts: list[AuditPart] = Field(
        default_factory=list,
        description="For a batch, what it holds by kind of thing and action. Its "
        "entries are listed at /audit/batches/{id}/entries.",
    )
    actor: str | None = Field(
        default=None,
        description="Who made it, as reported by the machine that made it (the "
        "operating-system user); for a batch, who made its changes. Null when "
        "it was not recorded.",
    )

    @classmethod
    def from_dto(cls, dto: AuditEventDTO) -> AuditEventResponse:
        return cls(
            id=str(dto.id),
            kind="batch" if dto.batch else "entry",
            timestamp=dto.timestamp,
            count=dto.count,
            entry=AuditLogResponse.from_dto(dto.entry) if dto.entry else None,
            batch=AuditBatchResponse.from_dto(dto.batch) if dto.batch else None,
            parts=[AuditPart(**p) for p in dto.parts],
            actor=dto.actor,
        )


class PaginatedAuditEventsResponse(BaseModel):
    items: list[AuditEventResponse]
    total: int
    offset: int
    limit: int


class OpenBatchRequest(BaseModel):
    kind: Literal["import"] = Field(
        default="import",
        description="What the batch is. Only an import is opened by a client; the "
        "server opens its own for deletes, restores and workflow runs.",
    )
    label: str | None = Field(default=None, description="E.g. the file imported.")


class RevertRequest(BaseModel):
    fields: list[str] | None = Field(
        default=None,
        description="Only put these fields back. Omit to revert everything the "
        "entry changed.",
    )
    force: bool = Field(
        default=False,
        description="Also overwrite fields that were edited since the entry.",
    )


class RevertFieldResponse(BaseModel):
    field: str
    label: str | None = None
    dtype: str | None = None
    current: Any = Field(default=None, description="What the record holds now.")
    target: Any = Field(default=None, description="What reverting would put back.")
    status: str = Field(
        description="apply (still as the entry left it), conflict (edited since; "
        "reverted only when forced), same (already the older value) or skipped "
        "(cannot be put back; see reason)."
    )
    reason: str | None = None


class RestoreAllRequest(BaseModel):
    filter: dict[str, Any] | None = Field(
        default=None,
        description="The history filter tree whose matches are restored (the one "
        "`GET /audit/events` takes), or null for everything deleted.",
    )
    q: str | None = Field(default=None, description="Text the changes must contain.")
    batch: str | None = Field(
        default=None,
        description="Only what this batch deleted: the id of a bulk delete (a "
        "record and everything beneath it) from `/audit/events`.",
    )


class RestoreAllPlanResponse(BaseModel):
    collections: int = Field(description="Deleted collections matched.")
    schemas: int = Field(description="Deleted schemas matched.")
    fields: int = Field(default=0, description="Deleted fields matched.")
    records: int = Field(description="Deleted records matched.")
    things: int = Field(description="All of the above.")
    restores: int = Field(
        description="Records that would be live afterwards, counting what came "
        "back with each, once."
    )
    blocked: int = Field(
        description="Matched, but under something deleted that is not in the set "
        "(for a field, also one whose name has since been taken)."
    )
    truncated: bool = Field(description="More matched than were looked at.")

    @classmethod
    def from_dto(cls, dto: RestoreAllPlanDTO) -> RestoreAllPlanResponse:
        return cls(**dto.to_dict())


class RestoreAllResultResponse(BaseModel):
    restored: int = Field(description="Things brought back.")
    records: int = Field(description="Records that came back in all.")
    blocked: int = Field(
        description="Left deleted: a parent is deleted and not in the set, or a "
        "field's name has been taken."
    )

    @classmethod
    def from_dto(cls, dto: RestoreAllResultDTO) -> RestoreAllResultResponse:
        return cls(**dto.to_dict())


class BlockerResponse(BaseModel):
    kind: str = Field(description="collection, schema or record.")
    id: str
    name: str = Field(description="What to call it: a name, or a record's name.")


class RestorePlanResponse(BaseModel):
    kind: str = Field(description="record, collection, schema or field.")
    id: str
    name: str
    schema_name: str | None = Field(
        default=None, description="For a field: the schema it belongs to."
    )
    records: int = Field(
        description="How many records come back: those deleted together with "
        "this, the record itself included when it is one. Never something "
        "deleted on its own earlier."
    )
    blocked_by: BlockerResponse | None = Field(
        default=None,
        description="The deleted collection, schema or record that must be "
        "restored first. Null when it can be restored now.",
    )
    collection: str | None = Field(
        default=None, description="For a record: the collection it will be in."
    )
    collection_id: str | None = None
    deleted_at: datetime | None = Field(
        default=None, description="When it was deleted."
    )
    parents_needed: int | None = Field(
        default=None,
        description="For a record held back only by deleted records above it: "
        "how many of them. `POST .../restore?with_parents=true` brings each "
        "back by itself (not what was deleted alongside it), so just this record "
        "(`&only_this=true`) comes back as `parents_needed + 1` records and "
        "its deleted siblings stay deleted. Null otherwise.",
    )
    blocked: str | None = Field(
        default=None,
        description="Why it can't be restored yet, in plain words. Null when it can.",
    )
    can_restore: bool

    @classmethod
    def from_dto(cls, dto: RestorePlanDTO) -> RestorePlanResponse:
        return cls(**dto.to_dict())


class RevertPlanResponse(BaseModel):
    audit_id: str
    entity_type: str
    entity_id: str
    kind: str | None = Field(
        default=None,
        description="update (put fields back), restore (undo a delete) or "
        "delete (undo a create). Null when nothing can be reverted.",
    )
    fields: list[RevertFieldResponse] = Field(
        default_factory=list, description="Per-field plan, for an update."
    )
    blocked: str | None = Field(
        default=None, description="Why the entry can't be reverted at all."
    )
    blocker: BlockerResponse | None = Field(
        default=None,
        description="When a deleted record can't come back yet, what to restore first.",
    )
    can_apply: bool
    has_conflicts: bool

    @classmethod
    def from_dto(cls, dto: RevertPlanDTO) -> RevertPlanResponse:
        return cls(**dto.to_dict())


class RevertResultResponse(BaseModel):
    audit_id: str
    entity_id: str
    kind: str
    applied: list[str] = Field(
        description="Names of the fields that were put back (an update only)."
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


class ShortcutResponse(BaseModel):
    exists: bool = Field(
        description="Whether the Desktop shortcut for this project is there."
    )
    path: str | None = Field(
        default=None, description="Where it is (or would be), when there is a Desktop."
    )


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
        description="Deleted items can be restored for this many days. A "
        "clean-up only deletes them permanently after that when "
        "`auto_purge_deleted` is on."
    )
    auto_purge_deleted: bool = Field(
        description="Whether a clean-up permanently deletes items deleted more "
        "than `purge_after_days` ago."
    )
    audit_days: int | None = Field(
        description="Change history older than this many days is removed by a "
        "clean-up. Null keeps it forever."
    )
    run_days: int | None = Field(
        description="Finished workflow runs, with their step logs, older than "
        "this many days are removed by a clean-up. Null keeps them forever."
    )


class UpdateRetentionSettingsRequest(BaseModel):
    """Only the fields sent are changed; send null for `audit_days` or
    `run_days` to keep that kind forever."""

    purge_after_days: int | None = Field(default=None, ge=1)
    auto_purge_deleted: bool | None = None
    audit_days: int | None = Field(default=None, ge=1)
    run_days: int | None = Field(default=None, ge=1)


class RetentionRunRequest(BaseModel):
    dry_run: bool = Field(default=True, description="Only count what would be removed.")
    from_settings: bool = Field(
        default=False,
        description="Apply the retention settings (each kind left at keep-forever "
        "is left alone).",
    )
    deleted_before: datetime | None = Field(
        default=None,
        description="Permanently delete everything deleted before this.",
    )
    audit_before: datetime | None = Field(
        default=None,
        description="Remove change history before this (not about anything that "
        "can still be restored, and with a remote, not yet pushed).",
    )
    runs_before: datetime | None = Field(
        default=None,
        description="Remove finished workflow runs, with their step logs, before this.",
    )


class ForgetPurgedRequest(BaseModel):
    dry_run: bool = Field(
        default=True, description="Only count the entries that would be deleted."
    )


class ForgetPurgedResponse(BaseModel):
    dry_run: bool
    entries: int = Field(
        description="History entries about records that no longer exist."
    )


class RetentionReportResponse(BaseModel):
    dry_run: bool
    deleted_records: int
    deleted_collections: int
    deleted_schemas: int
    skipped: list[str] = Field(
        description="Deleted things that could not be removed, with why."
    )
    audit_entries: int
    audit_batches: int
    audit_kept_restorable: int = Field(
        description="Older history kept because it is about something that can "
        "still be restored."
    )
    audit_kept_unsynced: int = Field(
        description="Older history kept because it has not been synced yet."
    )
    runs: int
    run_steps: int
    anything: bool

    @classmethod
    def from_dto(cls, dto: RetentionReportDTO) -> RetentionReportResponse:
        return cls(**dto.to_dict())


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
