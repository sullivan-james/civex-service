"""
Plain Python dataclasses that travel between every layer: CLI, services, repos, server.
No SQLAlchemy, no Pydantic — just data.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from civex.domain.naming import display_label
from civex.domain.templating import from_field_list


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    return dt


@dataclass
class FieldDTO:
    id: uuid.UUID
    schema_id: uuid.UUID
    name: str
    dtype: str  # "integer" | "float" | "string" | "boolean" | "file" | "reference" | "enum" | "url" | "reference_list" | "tags" | "longtext"
    required: bool
    restrictions: dict[str, Any]
    created_at: datetime
    default_value: Any | None = None
    position: int | None = None
    # Free-text display name; None means "derive one from name".
    # See civex.domain.naming for the name/label split.
    label: str | None = None
    # Soft-delete marker; None means live. See SchemaRepository.delete_field.
    deleted_at: datetime | None = None

    @property
    def display_name(self) -> str:
        return display_label(self.name, self.label)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "schema_id": str(self.schema_id),
            "name": self.name,
            "label": self.label,
            "dtype": self.dtype,
            "required": self.required,
            "restrictions": self.restrictions,
            "default_value": self.default_value,
            "position": self.position,
            "created_at": self.created_at.isoformat(),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FieldDTO:
        return cls(
            id=uuid.UUID(d["id"]),
            schema_id=uuid.UUID(d["schema_id"]),
            name=d["name"],
            label=d.get("label"),
            dtype=d["dtype"],
            required=d["required"],
            restrictions=d.get("restrictions") or {},
            default_value=d.get("default_value"),
            position=d.get("position"),
            created_at=datetime.fromisoformat(d["created_at"]),
            deleted_at=_parse_dt(d.get("deleted_at")),
        )


@dataclass
class SchemaDTO:
    id: uuid.UUID
    name: str
    description: str | None
    parent_id: uuid.UUID | None
    created_at: datetime
    fields: list[FieldDTO] = field(default_factory=list)
    # Template (domain/templating.py) that builds a record's natural name from
    # its field values; None means "use the first plain value".
    display_template: str | None = None
    # Free-text display name; None means "derive one from name".
    label: str | None = None
    # Soft-delete marker; None means live. See SchemaRepository.delete/restore.
    deleted_at: datetime | None = None
    # Fields deleted from this schema and still restorable. `fields` holds only
    # the live ones, so nothing that reads a schema sees a deleted field.
    deleted_fields: list[FieldDTO] = field(default_factory=list)
    # Uniqueness policies: each a list of this schema's own field ids. See
    # domain/uniqueness.py.
    unique_keys: list[list[str]] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return display_label(self.name, self.label)

    @property
    def unique_key_names(self) -> list[list[str]]:
        """`unique_keys` by field name; a key naming a field that's gone is dropped."""
        by_id = {str(f.id): f.name for f in self.fields}
        return [
            [by_id[i] for i in key]
            for key in self.unique_keys
            if all(i in by_id for i in key)
        ]

    def to_dict(self) -> dict[str, Any]:
        # fields excluded — it's a loaded relationship, not a scalar property
        return {
            "id": str(self.id),
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "display_template": self.display_template,
            "unique_keys": self.unique_keys,
            "created_at": self.created_at.isoformat(),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SchemaDTO:
        return cls(
            id=uuid.UUID(d["id"]),
            name=d["name"],
            label=d.get("label"),
            description=d.get("description"),
            parent_id=uuid.UUID(d["parent_id"]) if d.get("parent_id") else None,
            # Dumps and audit rows older than templates carry a field list.
            display_template=d.get("display_template")
            or (
                from_field_list(d["display_fields"])
                if d.get("display_fields")
                else None
            ),
            unique_keys=d.get("unique_keys") or [],
            created_at=datetime.fromisoformat(d["created_at"]),
            deleted_at=_parse_dt(d.get("deleted_at")),
        )


@dataclass
class SchemaDeleteImpactDTO:
    """What deleting a schema would take with it, computed up front so the
    caller can warn before the delete happens rather than after it fails."""

    child_schema_count: int
    record_count: int


@dataclass
class ResolvedField:
    """
    A field together with the name of the schema it was defined on.
    Used by SchemaService.collect_fields() to show field inheritance.
    """

    field: FieldDTO
    source_schema_name: str


@dataclass(frozen=True)
class DeletedField:
    """A deleted field and the schema it was defined on (which may be an
    ancestor of the schema a record is typed by), so it can be restored."""

    field: FieldDTO
    schema_name: str


@dataclass(frozen=True)
class ResolvedSchema:
    """A schema with its inherited fields flattened and indexed. Resolving a
    schema walks its parent chain, so a caller does it once per operation and
    hands this down rather than each helper re-resolving from a schema id."""

    schema: SchemaDTO
    fields: list[ResolvedField]  # own fields first, then inherited
    by_name: dict[str, FieldDTO]
    name_to_id: dict[str, str]  # field name -> str(field.id)
    id_to_name: dict[str, str]  # str(field.id) -> field name
    # Fields deleted from this schema or one it inherits from, by str(field.id):
    # what a record's leftover values belong to, and what can be restored.
    deleted_by_id: dict[str, DeletedField] = field(default_factory=dict)


@dataclass
class FieldValueDTO:
    """One value of one record, described for a person: the record's name, where
    it lives, the field's label and type, and the value as it is now. What a
    list of changes needs to say "depth on Encounter 12" instead of two ids.
    Response-only: worked out when read, never stored, so a rename shows."""

    record_id: str
    record_name: str | None
    dataset_name: str | None
    schema_name: str | None
    field_name: str | None  # what a write names; None when the field is gone
    field_label: str | None  # None when the field no longer exists
    dtype: str | None
    value: Any = None
    record_deleted: bool = False
    field_deleted: bool = False


@dataclass
class NameIssue:
    """A schema or field whose `name` predates slug validation.

    Reported by `SchemaService.lint_names()` / `civex schema lint`. Nothing is
    broken — these names still resolve — but they read badly in workflow YAML
    and CSV headers, so they're worth renaming (with a label taking over the
    human-facing text).
    """

    kind: str  # "schema" | "field"
    schema_name: str
    name: str
    suggestion: str | None  # slugified alternative, None if undecidable


@dataclass
class DatasetDTO:
    id: uuid.UUID
    name: str
    description: str | None
    record_count: int
    created_at: datetime
    # Soft-delete marker; None means live. See DatasetRepository.delete/restore.
    deleted_at: datetime | None = None
    # IANA zone datetime values are read and shown in; None = unset.
    timezone: str | None = None
    # "local" | "global" -- see civex.domain.scopes.
    scope: str = "local"
    # Names of the schemas this collection is for; records here can only be
    # of these. Sorted by name.
    schemas: list[str] = field(default_factory=list)
    # The same schemas by id, in the same order. History stores these too: a
    # schema's name can change, its id can't, so an entry still says which
    # schemas the collection was for after a rename.
    schema_ids: list[uuid.UUID] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        # record_count excluded — it's a computed value, not stored on the entity
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "timezone": self.timezone,
            "scope": self.scope,
            "schemas": list(self.schemas),
            "schema_ids": [str(i) for i in self.schema_ids],
            "created_at": self.created_at.isoformat(),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DatasetDTO:
        return cls(
            id=uuid.UUID(d["id"]),
            name=d["name"],
            description=d.get("description"),
            record_count=0,
            created_at=datetime.fromisoformat(d["created_at"]),
            deleted_at=_parse_dt(d.get("deleted_at")),
            # Absent in bundles/audit rows written before timezones existed.
            timezone=d.get("timezone"),
            # Likewise absent before collection scopes existed.
            scope=d.get("scope") or "local",
            schemas=list(d.get("schemas") or []),
            schema_ids=[uuid.UUID(i) for i in d.get("schema_ids") or []],
        )


@dataclass
class ViewDTO:
    """A saved column/filter/sort definition against a base schema -- a named
    civex.domain.query.RecordQuery plus columns. filter_tree is the filter
    tree shape of civex.domain.filters, unchanged: its conditions may test the
    base schema's own fields, an ancestor's or a descendant's. columns may
    additionally contain single-hop reference-field joins (see ViewService)."""

    id: uuid.UUID
    schema_id: uuid.UUID
    schema_name: str  # denormalised for display, resolved by the repo
    name: str
    columns: list[str]  # base schema field names, or "ref_field.target_field" joins
    filter_tree: dict[str, Any] | None  # civex.domain.filters wire shape
    sort: list[dict[str, Any]]  # [{"field": <name>, "direction": "asc"|"desc"}, ...]
    created_at: datetime
    # How the view's files are arranged when exported: "tree" or "flat"
    # (civex.domain.file_access.LAYOUTS).
    files_layout: str = "tree"

    def to_dict(self) -> dict[str, Any]:
        # schema_name excluded -- denormalized display field, not stored on the entity
        return {
            "id": str(self.id),
            "schema_id": str(self.schema_id),
            "name": self.name,
            "columns": self.columns,
            "filter_tree": self.filter_tree,
            "sort": self.sort,
            "files_layout": self.files_layout,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ViewDTO:
        return cls(
            id=uuid.UUID(d["id"]),
            schema_id=uuid.UUID(d["schema_id"]),
            schema_name="",
            name=d["name"],
            columns=d.get("columns") or [],
            filter_tree=d.get("filter_tree"),
            sort=d.get("sort") or [],
            created_at=datetime.fromisoformat(d["created_at"]),
            files_layout=d.get("files_layout") or "tree",
        )


@dataclass
class ExportDefinitionDTO:
    """An export saved with a schema (`schema_name`): which kind of record holds
    the files (`holder`, None = any kind beneath), which file fields (empty =
    every one), a filter on those records, and a layout
    (civex.domain.file_access.LAYOUTS). Which collection or record it runs on is
    not part of it."""

    id: uuid.UUID
    schema_id: uuid.UUID
    schema_name: str  # denormalised for display, resolved by the repo
    name: str
    holder_id: uuid.UUID | None
    holder: str | None  # the holder's schema name, resolved by the repo
    fields: list[str]
    filter_tree: dict[str, Any] | None
    files_layout: str
    created_at: datetime
    # Whether the files are exported (False: tables alone), and the tables to
    # make beside them (`civex.domain.tables.TableSpec`s as dicts).
    include_files: bool = True
    tables: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "schema_id": str(self.schema_id),
            "name": self.name,
            "holder_id": str(self.holder_id) if self.holder_id else None,
            "fields": self.fields,
            "filter_tree": self.filter_tree,
            "files_layout": self.files_layout,
            "include_files": self.include_files,
            "tables": self.tables,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class FileRef:
    """
    Stored as a dict in record.data for 'file' dtype fields.
    The actual bytes live in <volume_path>/<sha256[:2]>/<sha256[2:]>.
    """

    sha256: str
    filename: str  # original user-facing filename
    size: int  # bytes
    volume: str = "default"  # which named volume holds this object

    def to_dict(self) -> dict[str, Any]:
        return {
            "sha256": self.sha256,
            "filename": self.filename,
            "size": self.size,
            "volume": self.volume,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FileRef:
        return cls(
            sha256=d["sha256"],
            filename=d["filename"],
            size=d["size"],
            volume=d.get("volume", "default"),
        )


# Keys the server adds to a file value in responses. They describe the moment
# of the read, so a client that echoes them back must not get them stored, and
# a history diff must not count them as an edit.
DERIVED_FILE_KEYS = ("resolved_filename", "location")

# Volume states. "online" is the only one that accepts writes.
VOLUME_ONLINE = "online"
VOLUME_OFFLINE = "offline"  # the path isn't there (drive not plugged in)
VOLUME_WRONG_DRIVE = "wrong_drive"  # something is there, but it isn't this volume
VOLUME_READONLY = "readonly"  # reachable; marked read-only
VOLUME_RETIRED = "retired"  # reachable; no longer written to

# What a volume's configured `state` may be (the others above are worked out).
VOLUME_CONFIG_STATES = ("active", "readonly", "retired")


@dataclass(frozen=True)
class VolumeStatus:
    """Whether a volume can be used right now, and if not, why and what to do
    about it. Produced only by `VolumeAwareFileObjectStore.volume_status()`."""

    state: str  # one of the VOLUME_* constants
    reason: str = ""  # what civex expected vs found; empty when online
    fix: str = ""  # plain-language next step; empty when online
    volume_id: str | None = None  # the verified identity, once the volume has one

    @property
    def reachable(self) -> bool:
        """Its objects can be read and listed."""
        return self.state in (VOLUME_ONLINE, VOLUME_READONLY, VOLUME_RETIRED)

    @property
    def writable(self) -> bool:
        return self.state == VOLUME_ONLINE


@dataclass
class DirectoryEntry:
    name: str
    path: str


@dataclass
class StorageLocation:
    """A place to start browsing from: the project, home, or a mounted drive."""

    label: str
    path: str
    kind: str  # "project" | "home" | "drive"
    free_bytes: int | None = None
    total_bytes: int | None = None
    network: bool = False
    source: str | None = None  # where a network drive really lives (host:/share)


@dataclass
class DirectoryListing:
    path: str
    parent: str | None  # None at the top of the filesystem
    entries: list[DirectoryEntry]  # folders only
    truncated: bool
    locations: list[StorageLocation]
    hint: str | None = None  # why a drive might be missing, where it's known


@dataclass
class PathInspection:
    """What adding a folder as a volume would involve, decided in one place
    (`StoreService.inspect_path`) so the preview in the UI and the real
    `add_volume` can't disagree. `problems` block the add; `warnings` don't."""

    path: str
    exists: bool
    is_dir: bool
    writable: bool
    will_create: bool
    inside_project: bool
    same_disk_as_project: bool | None
    free_bytes: int | None
    total_bytes: int | None
    existing_volume: str | None  # a configured volume already at this path
    marker_volume: str | None  # configured volume whose drive this is
    has_civex_data: bool
    problems: list[str]
    warnings: list[str]
    is_network: bool = False


@dataclass
class FileCopy:
    """One place a file's content is (or is recorded to be)."""

    volume: str
    path: str  # where the object is, or would be, on that volume
    present: bool | None  # None: recorded there, but the volume can't be checked now
    state: str  # the volume's state (VOLUME_*)
    network: bool = False


@dataclass
class CollectionUse:
    id: str
    name: str | None  # None if the collection no longer exists
    records: int


@dataclass
class FileInfo:
    """Where a file's content is stored and what uses it."""

    sha256: str
    size: int | None
    copies: list[FileCopy]
    records: int  # records that reference it
    jobs: int  # workflow runs that took it as an input
    collections: list[CollectionUse]


@dataclass
class CollectionVolumeShare:
    """How much of a collection's data one volume holds."""

    volume: str
    files: int
    bytes: int
    shared_files: int  # of those, files another collection uses too
    state: str = "online"  # the volume's state now (see VolumeStatus)
    available: bool = True


@dataclass
class CollectionStorage:
    """Where a collection's files are: one share per volume that holds any."""

    collection_id: str
    files: int  # distinct files the collection's records use
    bytes: int  # of those the catalog has a size for
    volumes: list[CollectionVolumeShare]
    unlocated_files: int  # used by records but not in the catalog on any volume
    # Where those are: "server" (the project follows one: only there) or
    # "missing" (nowhere this project can get them from).
    unlocated_place: str = "missing"


@dataclass
class VolumeSurplus:
    """Files on a volume that no collection uses."""

    unused_files: int = 0  # nothing at all uses them (garbage collection can reclaim)
    unused_bytes: int = 0
    history_files: int = 0  # only workflow run history uses them
    history_bytes: int = 0


@dataclass
class StoredObjectInfo:
    """One object on disk in the content-addressed store, as seen by GC --
    not what a FileRef claims to point at, but what's actually there."""

    sha256: str
    volume: str
    size: int
    mtime: float  # unix timestamp; objects are write-once, so this is effectively creation time

    def to_dict(self) -> dict[str, Any]:
        return {
            "sha256": self.sha256,
            "volume": self.volume,
            "size": self.size,
            "mtime": self.mtime,
        }


@dataclass
class GCReport:
    """Result of a GCService.run() pass over the object store."""

    dry_run: bool
    grace_days: int
    scanned: int  # total objects found in the store
    referenced: int  # distinct sha256 reachable from a live root
    protected_by_grace: int  # unreferenced but younger than the grace period
    deleted: list[StoredObjectInfo]  # collected (or, if dry_run, collectible)
    stale_scratch_removed: int = 0  # abandoned put_stream() .part files reclaimed
    # Sources that failed to read while collecting references (e.g. a
    # corrupt JSON row). Non-empty means the reference set may be
    # incomplete, so run() refuses to delete anything this pass regardless
    # of the dry_run flag it was called with -- see GCService.run().
    errors: list[str] = field(default_factory=list)
    # The one volume this pass was limited to, or None for the whole store.
    volume: str | None = None

    @property
    def deleted_count(self) -> int:
        return len(self.deleted)

    @property
    def deleted_bytes(self) -> int:
        return sum(o.size for o in self.deleted)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "grace_days": self.grace_days,
            "scanned": self.scanned,
            "referenced": self.referenced,
            "protected_by_grace": self.protected_by_grace,
            "deleted_count": self.deleted_count,
            "deleted_bytes": self.deleted_bytes,
            "deleted": [o.to_dict() for o in self.deleted],
            "stale_scratch_removed": self.stale_scratch_removed,
            "errors": self.errors,
            "volume": self.volume,
        }


@dataclass
class RecordDTO:
    id: uuid.UUID
    dataset_id: uuid.UUID
    schema_id: uuid.UUID
    schema_name: str  # denormalised for display
    parent_record_id: uuid.UUID | None  # set for child-schema records
    data: dict[str, Any]  # field_name → coerced value or FileRef.to_dict()
    created_at: datetime
    updated_at: datetime
    natural_name: str | None = (
        None  # first meaningful field value; computed by RecordService
    )
    # Soft-delete marker; None means live. See RecordRepository.delete/restore.
    deleted_at: datetime | None = None
    # id -> that target's natural_name, for every reference/reference_list
    # value on this record. Response-only, like schema_name -- computed by
    # RecordService._attach_reference_labels, never stored or round-tripped.
    reference_labels: dict[str, str | None] | None = None
    # Response-only, like reference_labels: the name of the collection this
    # record lives in, and -- only for reference targets living in a
    # *different* collection (a global one) -- target id -> that collection's
    # name, so a client can mark where a reference comes from.
    dataset_name: str | None = None
    reference_collections: dict[str, str] | None = None
    # Response-only, like reference_labels: live child counts per child schema
    # name, and the requested columns the record's own data can't answer
    # (inherited fields, `ref.field` joins). See RecordService.query_records.
    child_counts: dict[str, int] | None = None
    derived: dict[str, Any] | None = None
    # Response-only: values this record still holds for fields that have been
    # deleted from its schema, each with when it was deleted and the schema to
    # restore it on. Nothing in `data` is lost; a restore brings them back.
    deleted_fields: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        # schema_name excluded — denormalized display field, not stored on the entity
        return {
            "id": str(self.id),
            "dataset_id": str(self.dataset_id),
            "schema_id": str(self.schema_id),
            "parent_record_id": str(self.parent_record_id)
            if self.parent_record_id
            else None,
            "data": self.data,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RecordDTO:
        return cls(
            id=uuid.UUID(d["id"]),
            dataset_id=uuid.UUID(d["dataset_id"]),
            schema_id=uuid.UUID(d["schema_id"]),
            schema_name="",
            parent_record_id=uuid.UUID(d["parent_record_id"])
            if d.get("parent_record_id")
            else None,
            data=d.get("data") or {},
            created_at=datetime.fromisoformat(d["created_at"]),
            updated_at=datetime.fromisoformat(d["updated_at"]),
            deleted_at=_parse_dt(d.get("deleted_at")),
        )


@dataclass
class ReferrerGroupDTO:
    """How many live records of one schema, in one collection, reference a
    record through one field -- one row of a record's "Referenced by"."""

    dataset_id: uuid.UUID
    dataset_name: str
    schema_name: str  # the referrers' schema, which owns the field
    field_name: str
    dtype: str  # "reference" | "reference_list"
    count: int


@dataclass
class AuditLogDTO:
    id: uuid.UUID
    action: str  # "create" | "update" | "delete" | "restore" | "purge"
    entity_type: str  # "record" | "schema" | "field" | "dataset" | "view"
    entity_id: uuid.UUID
    old_data: dict[str, Any] | None
    new_data: dict[str, Any] | None
    timestamp: datetime
    # Response-only, like RecordDTO.reference_labels: what the entry changed, as
    # `audit_diff.Change.to_dict()` rows, worked out by AuditService on a read.
    # Never stored.
    changes: list[dict[str, Any]] = field(default_factory=list)
    # Response-only, like `changes`: where the thing this entry is about is now
    # -- {kind, status: live|deleted|gone, name, collection, deleted_at} -- so a
    # lost record can be told from one that was edited, deleted or purged.
    now: dict[str, Any] | None = None
    # Who made the change, as the machine that made it reported it (the name
    # chosen in the project, else the OS user). None for entries from before
    # this was recorded.
    actor: str | None = None
    # The device a synced change came through, as the authority stamped it
    # from the device's token (None: made on the authority, not synced yet, or
    # synced before this was kept).
    device: str | None = None
    # How the change is stored (`AuditLog.format`): 1 = whole `old_data` and
    # `new_data`; 2 = `delta` (only what changed) with `new_data` the thing's
    # identity. Read the two sides with `audit_diff.entry_snapshots`.
    delta: dict[str, Any] | None = None
    format: int = 1
    # Response-only, like `changes`: what became of this change when it was sent
    # to the authority, if it did not go in as made -- `SyncConflictDTO.to_dict()`
    # rows (clashes, a refusal, an edit against a delete), open or settled. Never
    # stored, and never in a sync bundle.
    sync: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": str(self.entity_id),
            "old_data": self.old_data,
            "new_data": self.new_data,
            "timestamp": self.timestamp.isoformat(),
            **({"delta": self.delta, "format": self.format} if self.delta else {}),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AuditLogDTO:
        return cls(
            id=uuid.UUID(d["id"]),
            action=d["action"],
            entity_type=d["entity_type"],
            entity_id=uuid.UUID(d["entity_id"]),
            old_data=d.get("old_data"),
            new_data=d.get("new_data"),
            timestamp=datetime.fromisoformat(d["timestamp"]),
            delta=d.get("delta"),
            format=int(d.get("format") or 1),
        )


@dataclass
class BlockerDTO:
    """The deleted thing standing between a record and being restored: its
    collection, its schema, or the nearest-to-the-top deleted record above it.
    Restoring this one first is what unblocks the other."""

    kind: str  # "collection" | "schema" | "record"
    id: uuid.UUID
    name: str

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "id": str(self.id), "name": self.name}


@dataclass
class RestoreConflictDTO:
    """Why a deleted record can't come back although nothing above it is
    deleted: while it was gone, another record took the values of a uniqueness
    key (`fields`). Resolving it means changing or deleting `existing_id`, or
    leaving this one deleted."""

    record_id: (
        uuid.UUID
    )  # the record that can't come back (may be below the one asked for)
    record_name: str
    existing_id: str
    existing_name: str
    fields: list[str]

    @property
    def message(self) -> str:
        names = (
            self.fields[0]
            if len(self.fields) == 1
            else ", ".join(self.fields[:-1]) + " and " + self.fields[-1]
        )
        return (
            f"'{self.record_name}' can't come back: '{self.existing_name}' now has "
            f"the same {names}, and these must be unique. Change or delete "
            f"'{self.existing_name}' first, or leave this one deleted."
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": str(self.record_id),
            "record_name": self.record_name,
            "existing_id": self.existing_id,
            "existing_name": self.existing_name,
            "fields": self.fields,
            "message": self.message,
        }


@dataclass
class RestorePlanDTO:
    """What restoring something from Recently Deleted would do, worked out
    without doing it: whether it can be done, what is in the way, and what
    comes back. `records` counts the records restored, the record itself
    included when it is one; only what was deleted *with* it comes back, never
    something deleted on its own earlier."""

    kind: str  # "record" | "collection" | "schema" | "field"
    id: uuid.UUID
    name: str
    records: int
    blocked_by: BlockerDTO | None = None
    # Where a restored record will be (its collection), for saying so.
    collection: str | None = None
    collection_id: uuid.UUID | None = None
    # For a field: the schema it belongs to.
    schema_name: str | None = None
    # When it was deleted, for saying so.
    deleted_at: datetime | None = None
    # Why it can't come back when no deleted thing above it is the cause (a
    # field whose name has since been taken). Restoring something else won't
    # help, so there is no `blocked_by`.
    reason: str | None = None
    # For a record held back only by deleted records above it: how many of them
    # (each would come back by itself, not with what was deleted alongside it).
    # Restoring just this record then brings back `parents_needed + 1`.
    parents_needed: int | None = None
    # A live record has taken the unique values of one that would come back.
    conflict: RestoreConflictDTO | None = None

    @property
    def can_restore(self) -> bool:
        return self.blocked_by is None and self.reason is None and self.conflict is None

    @property
    def blocked_message(self) -> str | None:
        """Why it can't be restored, in plain words; None when it can."""
        return self.held_back_message or (
            self.conflict.message if self.conflict else None
        )

    @property
    def held_back_message(self) -> str | None:
        """Why it is held back by something deleted (or a taken field name),
        as opposed to a clash of unique values (`conflict`), which restoring
        less (`only_this`) can sidestep."""
        if self.reason:
            return self.reason
        b = self.blocked_by
        if b is None:
            return None
        where = {
            "collection": "is in the collection",
            "schema": "is a field of the schema"
            if self.kind == "field"
            else "is typed by the schema",
            "record": "is under the record",
        }[b.kind]
        return (
            f"'{self.name}' {where} '{b.name}', which is deleted. Restore that first."
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": str(self.id),
            "name": self.name,
            "records": self.records,
            "blocked_by": self.blocked_by.to_dict() if self.blocked_by else None,
            "collection": self.collection,
            "collection_id": str(self.collection_id) if self.collection_id else None,
            "schema_name": self.schema_name,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "parents_needed": self.parents_needed,
            "blocked": self.blocked_message,
            "conflict": self.conflict.to_dict() if self.conflict else None,
            "can_restore": self.can_restore,
        }


@dataclass
class RetentionCutoffs:
    """Delete what is older than these instants; None leaves that kind alone."""

    deleted_before: datetime | None = None  # things deleted before this, for good
    audit_before: datetime | None = None  # change history before this
    runs_before: datetime | None = None  # finished workflow runs before this


@dataclass
class RetentionReportDTO:
    """What a retention clean-up removed, or with `dry_run` would remove."""

    dry_run: bool
    deleted_records: int = 0
    deleted_collections: int = 0
    deleted_schemas: int = 0
    # Things that could not be deleted for good, with why.
    skipped: list[str] = field(default_factory=list)
    audit_entries: int = 0
    audit_batches: int = 0
    # Older history kept anyway: about something that can still be restored, or
    # not yet pushed to the remote.
    audit_kept_restorable: int = 0
    audit_kept_unsynced: int = 0
    # Kept however old: each thing's creation and latest entry.
    audit_kept_first_and_last: int = 0
    runs: int = 0
    run_steps: int = 0

    @property
    def anything(self) -> bool:
        return bool(
            self.deleted_records
            or self.deleted_collections
            or self.deleted_schemas
            or self.audit_entries
            or self.runs
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "deleted_records": self.deleted_records,
            "deleted_collections": self.deleted_collections,
            "deleted_schemas": self.deleted_schemas,
            "skipped": self.skipped,
            "audit_entries": self.audit_entries,
            "audit_batches": self.audit_batches,
            "audit_kept_restorable": self.audit_kept_restorable,
            "audit_kept_unsynced": self.audit_kept_unsynced,
            "audit_kept_first_and_last": self.audit_kept_first_and_last,
            "runs": self.runs,
            "run_steps": self.run_steps,
            "anything": self.anything,
        }


@dataclass
class RestoreSetDTO:
    """Which of a set of deleted records can come back, worked out for the whole
    set at once (a bulk delete can be thousands, so nothing here is a query per
    record)."""

    # Chosen records with nothing deleted above them: restorable right now.
    ready: list[uuid.UUID] = field(default_factory=list)
    # Chosen records held back by something deleted that is not covered.
    blocked: list[uuid.UUID] = field(default_factory=list)
    # Chosen records under another chosen one: they come back with it only if
    # they were deleted with it. Otherwise they wait for it, and go next round.
    waiting: list[uuid.UUID] = field(default_factory=list)
    # Every chosen record -> the records that come back with it (itself and what
    # was deleted with it).
    groups: dict[uuid.UUID, list[uuid.UUID]] = field(default_factory=dict)
    # Everything that would be live afterwards, counting each record once.
    coming: set[uuid.UUID] = field(default_factory=set)


@dataclass
class RestoreSetResultDTO:
    restored: int  # records restored in their own right
    came_back: int  # records live again in all, with what went with them
    left: list[str]  # chosen records still held back, as ids


@dataclass
class RestoreAllPlanDTO:
    """What restoring every deleted thing a history filter matches would do,
    worked out without doing it."""

    collections: int  # deleted collections matched
    schemas: int  # deleted schemas matched
    records: int  # deleted records matched, each deleted in its own right
    restores: int  # records that would come back in all, with what went with them
    blocked: int  # matched, but something above is deleted and not in the set
    truncated: bool = False  # more matched than were looked at
    fields: int = 0  # deleted fields matched

    @property
    def things(self) -> int:
        return self.collections + self.schemas + self.fields + self.records

    def to_dict(self) -> dict[str, Any]:
        return {
            "collections": self.collections,
            "schemas": self.schemas,
            "fields": self.fields,
            "records": self.records,
            "restores": self.restores,
            "blocked": self.blocked,
            "truncated": self.truncated,
            "things": self.things,
        }


@dataclass
class RestoreAllResultDTO:
    restored: int  # things brought back
    records: int  # records that came back in all
    blocked: int  # left deleted: something above them is deleted and not in the set

    def to_dict(self) -> dict[str, Any]:
        return {
            "restored": self.restored,
            "records": self.records,
            "blocked": self.blocked,
        }


# What reverting one field of an entry would do. See AuditService.plan_revert.
REVERT_APPLY = "apply"  # the field still holds what the entry left; safe to put back
REVERT_CONFLICT = "conflict"  # edited since the entry; put back only when forced
REVERT_SAME = "same"  # already holds the older value; nothing to do
REVERT_SKIPPED = "skipped"  # can't be put back (`reason` says why)


@dataclass
class RevertFieldDTO:
    field: str
    label: str | None
    dtype: str | None
    current: Any  # what the record holds now
    target: Any  # what reverting would put back
    status: str  # REVERT_*
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "label": self.label,
            "dtype": self.dtype,
            "current": self.current,
            "target": self.target,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass
class RevertPlanDTO:
    """What undoing an audit entry would do, worked out without doing it.

    `kind`: "update" puts fields back, "restore" brings a deleted record back
    (undoing a delete), "delete" removes a record (undoing a create).
    `blocked` is why nothing can be undone at all, else None."""

    audit_id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    kind: str | None
    fields: list[RevertFieldDTO] = field(default_factory=list)
    blocked: str | None = None
    # What to restore first, when that is why `blocked` is set.
    blocker: BlockerDTO | None = None

    @property
    def can_apply(self) -> bool:
        if self.blocked:
            return False
        if self.kind != "update":
            return True
        return any(f.status in (REVERT_APPLY, REVERT_CONFLICT) for f in self.fields)

    @property
    def has_conflicts(self) -> bool:
        return any(f.status == REVERT_CONFLICT for f in self.fields)

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit_id": str(self.audit_id),
            "entity_type": self.entity_type,
            "entity_id": str(self.entity_id),
            "kind": self.kind,
            "fields": [f.to_dict() for f in self.fields],
            "blocked": self.blocked,
            "blocker": self.blocker.to_dict() if self.blocker else None,
            "can_apply": self.can_apply,
            "has_conflicts": self.has_conflicts,
        }


@dataclass
class RevertResultDTO:
    audit_id: uuid.UUID
    entity_id: uuid.UUID
    kind: str
    applied: list[str] = field(default_factory=list)  # field names put back

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit_id": str(self.audit_id),
            "entity_id": str(self.entity_id),
            "kind": self.kind,
            "applied": self.applied,
        }


@dataclass
class AuditBatchDTO:
    """What a bulk operation was, for the one event it shows as in history."""

    id: uuid.UUID
    kind: str  # "import" | "delete" | "restore" | "purge" | "workflow"
    label: str | None  # a workflow's name, an import's file; else None
    ref: str | None  # what started it, to link to (a workflow run's id)
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "kind": self.kind,
            "label": self.label,
            "ref": self.ref,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class AuditEventDTO:
    """One line of history: a single change, or a whole batch of them. A batch
    reports how many matching changes it holds and of what (`parts`), not the
    changes themselves; those are paged separately."""

    id: uuid.UUID  # the entry's id, or the batch's
    timestamp: datetime  # the latest change in it
    count: int  # changes in it that match the filters
    entry: AuditLogDTO | None = None
    batch: AuditBatchDTO | None = None
    parts: list[dict[str, Any]] = field(
        default_factory=list
    )  # {entity_type, action, count}
    # Who made it: the entry's actor, or for a batch the one its changes were
    # made by. None when it was not recorded.
    actor: str | None = None
    # The device it came through, when synced (see AuditLogDTO.device).
    device: str | None = None


@dataclass
class ErrorEnvelope:
    """How a failed workflow step is recorded, identically for every tier.

    `kind`/`message`/`retryable` are the wire protocol's envelope
    (civex_plugin_sdk.errors) -- a built-in raising in-process, a subprocess
    plugin sending an error frame, and a container exiting non-zero all
    arrive here in the same shape.

    `step` is added host-side and is deliberately not part of the wire
    envelope: a plugin has no idea which step id it was invoked as, and
    shouldn't. The executor knows, and a job error that doesn't say which
    step failed is close to useless in a multi-step workflow.
    """

    kind: str
    message: str
    retryable: bool = False
    step: str | None = None

    @classmethod
    def from_exception(
        cls, exc: BaseException, step: str | None = None
    ) -> "ErrorEnvelope":
        """Classify any exception. Anything that doesn't declare a `kind`
        (a bare ValueError from a built-in, say) is an unclassified crash:
        reported as such, and never as retryable, because there's no basis
        to guess and guessing wrong re-runs a permanently broken step."""
        return cls(
            kind=getattr(exc, "kind", None) or "plugin_error",
            message=str(exc) or exc.__class__.__name__,
            retryable=bool(getattr(exc, "retryable", False)),
            step=step,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "message": self.message,
            "retryable": self.retryable,
            "step": self.step,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ErrorEnvelope":
        return cls(
            kind=raw.get("kind", "plugin_error"),
            message=raw.get("message", ""),
            retryable=bool(raw.get("retryable", False)),
            step=raw.get("step"),
        )


@dataclass
class StepExecution:
    """One step's resolved inputs/outputs/timing/outcome from a single
    `executor.run()` pass (CIVEX-117). Persisted as a list of these (via
    `to_dict()`) on the `step_executions` table, one row per step
    (CIVEX-170) -- `WorkflowJobDTO.step_executions` reassembles that back
    into this same list-of-dicts shape.

    `outputs` is None for a step that raised (there's nothing to report) or
    was skipped by a falsy `if:` (its plugin never ran). `error` is the same
    human-readable message form `ErrorEnvelope.message` uses, not the full
    envelope -- the failing step already names itself via `step_id`.

    `depends_on` is the same dependency edges `executor.topological_sort()`
    derived to order this run (CIVEX-132) -- the step ids (not virtual ones
    like `__input__`) this step's `inputs`/`if` reference. It reflects the
    dependencies actually used by this run rather than requiring a separate
    fetch/parse of the workflow's YAML to draw a DAG of it.
    """

    step_id: str
    plugin: str
    status: str  # success | failed | skipped
    inputs: dict[str, Any]
    outputs: dict[str, Any] | None
    duration_seconds: float
    error: str | None = None
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "plugin": self.plugin,
            "status": self.status,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
            "depends_on": self.depends_on,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StepExecution":
        return cls(
            step_id=raw["step_id"],
            plugin=raw["plugin"],
            status=raw["status"],
            inputs=raw.get("inputs") or {},
            outputs=raw.get("outputs"),
            duration_seconds=raw.get("duration_seconds", 0.0),
            error=raw.get("error"),
            depends_on=raw.get("depends_on") or [],
        )


@dataclass
class WorkflowJobDTO:
    id: uuid.UUID
    workflow_name: str
    record_id: uuid.UUID
    schema_name: str  # resolved via record_id -> schemas.name, not stored (CIVEX-171)
    trigger: str  # record_created | record_updated | manual
    status: str  # pending | running | completed | failed
    error: str | None  # human-readable message; == error_details["message"] when set
    error_details: dict[str, Any] | None  # ErrorEnvelope.to_dict(), when known
    log: str | None  # captured stdout/stderr from execution
    input_data: (
        dict[str, Any] | None
    )  # pre-seeded __input__ step outputs for manual+batch runs
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    depth: int = 0  # trigger chain depth; jobs enqueued at MAX_JOB_DEPTH are refused
    # Per-step execution records (CIVEX-117), backed by the `step_executions`
    # table (CIVEX-170): list of StepExecution.to_dict(), in execution order.
    # None for jobs still pending/running, or that have no steps recorded.
    step_executions: list[dict[str, Any]] | None = None
    # Records this run created or updated: [{record_id, schema_name,
    # natural_name, action}, ...] in touch order. None for jobs still
    # pending/running, or that predate this field.
    affected_records: list[dict[str, Any]] | None = None
    # What caused the run: {"changes": [{field, before, after, watched}],
    # "caused_by": {job_id, workflow} | None}. None for a run started by hand,
    # or one that predates this field.
    trigger_detail: dict[str, Any] | None = None


@dataclass
class AiUsageEventDTO:
    id: uuid.UUID
    provider: str  # "anthropic" | "openai-compat"
    model: str
    input_tokens: int
    output_tokens: int
    created_at: datetime


@dataclass
class AnalyticsFilters:
    """The one query-param contract shared by every `/analytics` endpoint
    (server/routers/analytics.py). Each endpoint documents which of these it
    actually applies -- unused fields are simply ignored rather than
    rejected, so the frontend filter bar can send the same params to every
    widget without per-widget special cases.

    `dataset`/`schema` are names (not ids), matching how every other
    endpoint in this API addresses them. `workflow_id`/`plugin_id` are the
    string identifiers used elsewhere too (WorkflowDef.name and the plugin
    registry key, e.g. "civex.load_file") -- neither resource has a separate
    numeric/uuid id.
    """

    start: datetime | None = None
    end: datetime | None = None
    bucket: str = "day"  # day | week | month
    dataset: str | None = None
    schema: str | None = None
    workflow_id: str | None = None
    plugin_id: str | None = None
    status: str | None = None
    trigger: str | None = None
    entity_type: str | None = None
    action: str | None = None


@dataclass
class OrphanDTO:
    """A live record that sits under a deleted one, and what it sits under
    (the deleted records directly above it, topmost first)."""

    record: RecordDTO
    above: list[RecordDTO]
