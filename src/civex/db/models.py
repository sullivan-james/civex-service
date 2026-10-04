"""
SQLAlchemy 2.0 ORM models.

Key design choice: record data is stored as JSON/JSONB.
This replaces the EAV multi-table pattern — validation and type coercion happen in
application code against the schema's field definitions, not at the DB layer.

On PostgreSQL the JSON columns become JSONB (via with_variant), giving GIN index
support for field-level queries. On SQLite they are stored as text.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, cast

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    Table,
    Text,
    TypeDecorator,
    UniqueConstraint,
    delete,
    event,
    inspect,
    insert,
    nulls_last,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Transparently uses JSONB on PostgreSQL, JSON text on SQLite.
_JSON = JSON().with_variant(JSONB(), "postgresql")
# Transparently uses TSVECTOR on PostgreSQL, plain text (unused) on SQLite.
_TSVECTOR = Text().with_variant(TSVECTOR(), "postgresql")


class _UTCDateTime(TypeDecorator):
    """DateTime(timezone=True) that guarantees a UTC-aware value on read.

    SQLite has no timestamp-with-timezone storage — it keeps the wall-clock
    value and drops the offset, handing back a naive datetime on SELECT even
    though every value written here (see _now()) is UTC. Reattach the tzinfo
    SQLite dropped so callers never see a naive-but-actually-UTC datetime.
    PostgreSQL's TIMESTAMPTZ already round-trips tzinfo, so this is a no-op there.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(
        self, value: datetime | None, dialect: Any
    ) -> datetime | None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


class Schema(Base):
    """
    A schema is a named, versioned definition of a data structure.
    A schema can inherit fields from a parent schema.
    Multiple datasets can share a schema.
    """

    __tablename__ = "schemas"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # Human-facing display name. name stays a slug because workflows, CSV
    # headers and display_template reference it as text; label absorbs the
    # cosmetic churn so renames stay rare. Null → derived from name.
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(String(1000))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("schemas.id"), nullable=True
    )
    # Template naming this schema's records (domain/templating.py); null means
    # "use the first plain value on the record".
    display_template: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(_UTCDateTime(), default=_now)
    # Soft-delete marker. NULL = live. Set instead of a hard DELETE so a
    # schema (and, via SchemaRepository's cascade, the records typed by it)
    # can be restored within the retention window (see RetentionConfig).
    deleted_at: Mapped[datetime | None] = mapped_column(
        _UTCDateTime(), nullable=True, default=None
    )

    fields: Mapped[list[Field]] = relationship(
        "Field",
        back_populates="schema",
        cascade="all, delete-orphan",
        order_by=lambda: [nulls_last(Field.position), Field.created_at],
    )
    parent: Mapped[Schema | None] = relationship(
        "Schema", remote_side="Schema.id", back_populates="children"
    )
    children: Mapped[list[Schema]] = relationship("Schema", back_populates="parent")


class Field(Base):
    """
    A single field definition within a schema.
    dtype is one of: integer, float, string, boolean, file, reference.
    restrictions is a freeform JSON dict (e.g. min/max for numbers, regex for strings).
    """

    __tablename__ = "fields"
    __table_args__ = (UniqueConstraint("schema_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    schema_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schemas.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # See Schema.label -- same split, same reason. Null → derived from name.
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dtype: Mapped[str] = mapped_column(String(50), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    restrictions: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict)
    default_value: Mapped[Any | None] = mapped_column(_JSON, nullable=True)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(_UTCDateTime(), default=_now)

    schema: Mapped[Schema] = relationship("Schema", back_populates="fields")


class View(Base):
    """
    A saved column/filter/sort definition against a base schema -- the
    definition a table view in the UI reads back to reconstruct itself, and
    what a schema's "saved filters" are. filter_tree is the same AND/OR shape
    records queries use (civex.domain.filters), whose conditions may test the
    base schema's own fields, an ancestor's or a descendant's; columns/sort
    reference field names the way Schema.display_fields does, not field ids,
    so renaming a field on the schema is not reflected here automatically.
    columns may also contain single-hop reference joins ("customer.email") --
    see RecordService.validate_columns / _attach_derived.
    """

    __tablename__ = "views"
    __table_args__ = (UniqueConstraint("schema_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    schema_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schemas.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    columns: Mapped[list[str]] = mapped_column(_JSON, nullable=False, default=list)
    filter_tree: Mapped[dict[str, Any] | None] = mapped_column(_JSON, nullable=True)
    sort: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON, nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(_UTCDateTime(), default=_now)

    schema: Mapped[Schema] = relationship("Schema")


class Dataset(Base):
    """
    A named container for a study or investigation.
    Records within a dataset may use any schema; the schema hierarchy
    and parent_record_id links express the structure.
    """

    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))
    # IANA zone (e.g. "America/Chicago") that datetime values in this dataset
    # are read and shown in. NULL means unset: naive input is read as UTC and
    # the UI falls back to the viewer's own zone. A datetime field's own
    # `timezone` restriction overrides it. See domain/timezones.py.
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(_UTCDateTime(), default=_now)
    # See Schema.deleted_at -- same soft-delete marker, same reason. Deleting
    # a dataset cascades to soft-delete its records (DatasetRepository).
    deleted_at: Mapped[datetime | None] = mapped_column(
        _UTCDateTime(), nullable=True, default=None
    )

    # "local": records here can only be referenced from within this collection.
    # "global": records here can be referenced from every collection. See
    # civex.domain.scopes.
    scope: Mapped[str] = mapped_column(
        String(10), nullable=False, default="local", server_default="local"
    )

    records: Mapped[list[Record]] = relationship(
        "Record", back_populates="dataset", cascade="all, delete-orphan"
    )
    schema_links: Mapped[list[DatasetSchema]] = relationship(
        "DatasetSchema", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("scope IN ('local', 'global')", name="ck_datasets_scope"),
    )


class DatasetSchema(Base):
    """A schema a collection is for: records in the collection can only be of
    these schemas. Schemas are global, so this is many-to-many. A child
    schema's parent must be listed too (its parent record lives in the same
    collection) -- enforced by DatasetService."""

    __tablename__ = "dataset_schemas"

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True
    )
    schema_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schemas.id"), primary_key=True
    )

    __table_args__ = (Index("ix_dataset_schemas_schema", "schema_id"),)


class Record(Base):
    """
    A single data entry in a dataset, typed by its schema.
    data is a JSON dict keyed by *field UUID* (RecordService translates to and
    from field names at its boundary, see _names_to_ids/_ids_to_names), values
    are the typed field values. Storing UUIDs means renaming a field costs
    nothing here.
    Validation against the schema's fields happens at write time in application code.

    parent_record_id links child-schema records to the parent record they extend
    (e.g. a Recording record referencing its Encounter record within the same dataset).
    """

    __tablename__ = "records"
    __table_args__ = (
        # A child's dataset_id must match its parent's (parent_record_id ->
        # dataset_id is a functional dependency; enforcing it as a plain FK
        # on id alone would be a 3NF violation). The unique constraint below
        # lets (id, dataset_id) be the target of the composite FK that ties
        # parent_record_id to the parent's dataset_id.
        UniqueConstraint("id", "dataset_id", name="uq_records_id_dataset"),
        ForeignKeyConstraint(
            ["parent_record_id", "dataset_id"],
            ["records.id", "records.dataset_id"],
            name="fk_records_parent_same_dataset",
        ),
        Index("ix_records_dataset_schema", "dataset_id", "schema_id"),
        Index("ix_records_dataset_created", "dataset_id", "created_at"),
        Index("ix_records_dataset_parent", "dataset_id", "parent_record_id"),
        Index("ix_records_deleted_at", "deleted_at"),
        # list_children / recursive delete-restore-purge look children up by
        # parent alone (no dataset_id), which the composite index above can't
        # serve because it leads with dataset_id.
        Index("ix_records_parent", "parent_record_id"),
        # Nearly every read filters deleted_at IS NULL, so the live-row
        # listing index is partial: it excludes trash and stays small.
        Index(
            "ix_records_live_dataset_created",
            "dataset_id",
            "created_at",
            "id",
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_records_live_schema_created",
            "schema_id",
            "created_at",
            "id",
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        # GIN index enables containment (@>) queries on JSONB data fields.
        # On SQLite this degrades to a plain B-tree on the JSON text column (harmless).
        Index("ix_records_data_gin", "data", postgresql_using="gin"),
        # Full-text search (`search_vector @@ plainto_tsquery`) is a scan of
        # every record without this. SQLite never populates the column, so
        # there the (partial) index stays empty.
        Index(
            "ix_records_search_vector",
            "search_vector",
            postgresql_using="gin",
            sqlite_where=text("search_vector IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id"), nullable=False
    )
    schema_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schemas.id"), nullable=False
    )
    parent_record_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(_UTCDateTime(), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        _UTCDateTime(), default=_now, onupdate=_now
    )
    search_vector: Mapped[str | None] = mapped_column(
        _TSVECTOR, nullable=True, default=None
    )
    # See Schema.deleted_at -- same soft-delete marker. Also set by cascade
    # when the owning dataset or schema is deleted (see DatasetRepository /
    # SchemaRepository), and recursively when an ancestor record is deleted
    # (RecordService._delete_recursive).
    deleted_at: Mapped[datetime | None] = mapped_column(
        _UTCDateTime(), nullable=True, default=None
    )

    dataset: Mapped[Dataset] = relationship("Dataset", back_populates="records")
    # Every record read names its schema (RecordDTO.schema_name); joined, that
    # arrives with the record's own row instead of a lazy load per record.
    schema: Mapped[Schema] = relationship("Schema", lazy="joined")


class Commit(Base):
    """A named snapshot grouping a set of audit log entries (uncommitted changes)."""

    __tablename__ = "commits"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    seq: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True)
    message: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(_UTCDateTime(), default=_now)
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    schema_count: Mapped[int] = mapped_column(Integer, default=0)
    dataset_count: Mapped[int] = mapped_column(Integer, default=0)
    pushed_at: Mapped[datetime | None] = mapped_column(_UTCDateTime(), nullable=True)

    entries: Mapped[list[AuditLog]] = relationship("AuditLog", back_populates="commit")


class AuditLog(Base):
    """One row per entity write — create, update, or delete — from any source."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_entity", "entity_id", "timestamp"),
        Index("ix_audit_log_commit", "commit_id"),
        Index("ix_audit_log_timestamp", "timestamp"),
        # Staged (uncommitted) entries: a tiny, hot subset of a table that
        # otherwise grows forever.
        Index(
            "ix_audit_log_staged",
            "timestamp",
            postgresql_where=text("commit_id IS NULL"),
            sqlite_where=text("commit_id IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    commit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("commits.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # create | update | delete
    entity_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # record | schema | field | dataset
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    old_data: Mapped[dict[str, Any] | None] = mapped_column(_JSON, nullable=True)
    new_data: Mapped[dict[str, Any] | None] = mapped_column(_JSON, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(_UTCDateTime(), default=_now)

    commit: Mapped[Commit | None] = relationship("Commit", back_populates="entries")


class WorkflowJob(Base):
    """
    A queued or completed workflow execution.
    Jobs are enqueued automatically when a record event matches a workflow trigger,
    or manually via `civex worker enqueue`. The worker drains pending jobs in order.
    status: pending → running → completed | failed | cancelled
    trigger: record_created | record_updated | manual
    """

    __tablename__ = "workflow_jobs"
    __table_args__ = (
        # claim_pending(): oldest job in a given status.
        Index("ix_workflow_jobs_status_created", "status", "created_at"),
        Index("ix_workflow_jobs_record_created", "record_id", "created_at"),
        Index("ix_workflow_jobs_created", "created_at"),
        Index("ix_workflow_jobs_workflow_status", "workflow_name", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    workflow_name: Mapped[str] = mapped_column(String(255), nullable=False)
    record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("records.id"), nullable=False
    )
    # No schema_name column here (CIVEX-171): it was a copy of
    # records.schema_id -> schemas.name that went stale on rename. record_id
    # is a hard FK with no cascade, so a job's record can never disappear out
    # from under it -- the join is always available, so there's nothing to
    # snapshot. See job_repo._to_dto for where it's resolved on read.
    trigger: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # Structured form of `error` (CIVEX-143): {kind, message, retryable,
    # step}, identical whether the step failed in-process, in a subprocess,
    # or (later) in a container. `error` stays as the human-readable message
    # so existing readers keep working; this is what anything wanting to
    # *branch* on a failure reads. Both are written from `error_details` in
    # one place (WorkflowJobRepository.mark_failed, CIVEX-171) so they can't
    # disagree.
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    error_details: Mapped[dict[str, Any] | None] = mapped_column(_JSON, nullable=True)
    log: Mapped[str | None] = mapped_column(String, nullable=True)
    input_data: Mapped[dict[str, Any] | None] = mapped_column(_JSON, nullable=True)
    # Records this run created or updated: [{record_id, schema_name,
    # natural_name, action}, ...] in touch order -- WorkflowContext builds
    # this list live (see plugins.base.WorkflowContext._note_affected) and
    # the run persists whatever it collected before completing or failing,
    # same partial-progress contract as step_executions. None for jobs that
    # predate this field or never got far enough to touch a record.
    affected_records: Mapped[list[dict[str, Any]] | None] = mapped_column(
        _JSON, nullable=True
    )
    depth: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # What caused this run, beyond the event name: {"changes": [{field, before,
    # after, watched}], "caused_by": {job_id, workflow} | null}. Null for a run
    # started by hand, or that predates this field.
    trigger_detail: Mapped[dict[str, Any] | None] = mapped_column(_JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(_UTCDateTime(), default=_now)
    started_at: Mapped[datetime | None] = mapped_column(_UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(_UTCDateTime(), nullable=True)

    record: Mapped[Record] = relationship("Record")
    steps: Mapped[list["StepExecution"]] = relationship(
        "StepExecution",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="StepExecution.position",
    )


class StepExecution(Base):
    """One step's resolved inputs/outputs/timing/outcome from a single
    `executor.run()` pass -- see civex.domain.dtos.StepExecution, which is
    what `executor.run()` builds these rows from.

    Normalized out of the old `workflow_jobs.step_executions` JSON blob
    (CIVEX-117 -> CIVEX-170) so the envelope columns that analytics actually
    query (plugin, status, duration) don't require a JSON scan. `inputs` /
    `outputs` / `error_details` stay JSON -- they're arbitrary plugin
    payloads / envelopes with no fixed shape, and normalizing those out
    would just be trading one JSON blob for another.
    """

    __tablename__ = "step_executions"
    __table_args__ = (
        UniqueConstraint("job_id", "position"),
        Index("ix_step_executions_plugin_status", "plugin", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_jobs.id"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    step_id: Mapped[str] = mapped_column(String(255), nullable=False)
    plugin: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_details: Mapped[dict[str, Any] | None] = mapped_column(_JSON, nullable=True)
    inputs: Mapped[dict[str, Any] | None] = mapped_column(_JSON, nullable=True)
    outputs: Mapped[dict[str, Any] | None] = mapped_column(_JSON, nullable=True)
    # Not part of CIVEX-170's proposed schema, but dropping it would break
    # JobStepsDiagram's DAG view (CIVEX-132) -- kept as opaque JSON like
    # inputs/outputs since it's a list of step ids, not something queried on.
    depends_on: Mapped[list[str] | None] = mapped_column(_JSON, nullable=True)

    job: Mapped[WorkflowJob] = relationship("WorkflowJob", back_populates="steps")


class AiUsageEvent(Base):
    """One AI provider API call's token usage, recorded regardless of which
    provider/model was used -- powers `civex ai usage` and the AI panel's
    usage counter. Not tied to a record/session; a flat append-only log.
    """

    __tablename__ = "ai_usage_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_UTCDateTime(), default=_now)


class JobAffectedSchema(Base):
    """Which schemas a workflow run wrote to. Real foreign keys on both
    sides (unlike the `affected_records` JSON on WorkflowJob), so "jobs that
    touched schema X" is an indexed join rather than a JSON scan, and a
    purged job or schema takes its link rows with it."""

    __tablename__ = "job_affected_schemas"
    __table_args__ = (Index("ix_job_affected_schemas_schema", "schema_id"),)

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    schema_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schemas.id", ondelete="CASCADE"), primary_key=True
    )


class JobAffectedRecord(Base):
    """Which records a workflow run created or changed -- the indexed form of
    the `affected_records` JSON on WorkflowJob, so "runs that touched record
    X" (shown on every record's page) is a lookup rather than a scan of every
    job. `record_id` is not a FK: it mirrors what the run reported, and a
    record may since have been purged."""

    __tablename__ = "job_affected_records"
    __table_args__ = (Index("ix_job_affected_records_record", "record_id"),)

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    record_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)


class StorageTransfer(Base):
    """A move of stored files between volumes, as a durable account: what was
    asked for, how far it got, what couldn't be moved, and how it ended. The
    thread doing the work is momentary; this is what survives a restart, and
    what a progress bar reads."""

    __tablename__ = "storage_transfers"
    __table_args__ = (
        Index("ix_storage_transfers_created", "created_at"),
        Index("ix_storage_transfers_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # queued | running | paused | completed | failed | cancelled | interrupted
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    spec: Mapped[dict[str, Any]] = mapped_column(_JSON, nullable=False)
    plan: Mapped[dict[str, Any] | None] = mapped_column(_JSON, nullable=True)
    progress: Mapped[dict[str, Any]] = mapped_column(_JSON, nullable=False)
    failures: Mapped[list[Any]] = mapped_column(_JSON, nullable=False, default=list)
    failures_total: Mapped[int] = mapped_column(nullable=False, default=0)
    pause_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_resume: Mapped[bool] = mapped_column(nullable=False, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A pause or cancel someone has asked for. The process running the transfer
    # notices it as it saves progress, so it works from any other process.
    control: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Sources made read-only for the duration, and what each was before.
    frozen: Mapped[dict[str, Any]] = mapped_column(_JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(_UTCDateTime(), default=_now)
    started_at: Mapped[datetime | None] = mapped_column(_UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(_UTCDateTime(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(_UTCDateTime(), default=_now)


class StoredObject(Base):
    """Inventory of blobs in the object store: one row per sha256, written
    when the blob lands on disk and removed when it is deleted. Exists so
    per-volume usage is `SUM(size)` over an indexed column instead of a walk
    of the whole volume, and so GC never has to hold the store listing in
    memory. Disk is the source of truth -- GC reconciles this table against
    it, so drift (a rolled-back request, a crash) self-heals."""

    __tablename__ = "stored_objects"
    __table_args__ = (Index("ix_stored_objects_volume", "volume"),)

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    volume: Mapped[str] = mapped_column(String(255), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_UTCDateTime(), default=_now)


class RecordReference(Base):
    """A reference from one record's field to another record -- the reverse of
    what a `reference`/`reference_list` value says, so "what points at X" is an
    indexed lookup instead of a search of every record's JSON. Maintained by
    ORM events whenever a record's `data` is written (see below), and removed
    by ON DELETE CASCADE when the referrer is purged.

    `target_id` is deliberately not a FK: a reference may dangle (that is what
    `civex doctor` reports), and a target must stay purgeable. Rows come from
    any UUID-shaped value under a UUID key, so a text field holding a UUID adds
    one too; readers restrict `field_id` to real reference fields."""

    __tablename__ = "record_references"
    __table_args__ = (Index("ix_record_references_target", "target_id"),)

    record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("records.id", ondelete="CASCADE"), primary_key=True
    )
    field_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    target_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)


class FileReference(Base):
    """A live reference from a record (or a workflow job's input) to a blob.
    Maintained by ORM events in `civex.db.file_refs` whenever a record's
    `data` or a job's `input_data` is written, and removed by ON DELETE
    CASCADE when the owner is purged. GC collects blobs with no row here.
    `sha256` is deliberately not a FK to `stored_objects`: a record may
    reference a blob that hasn't been fetched from the remote yet."""

    __tablename__ = "file_references"
    __table_args__ = (
        CheckConstraint(
            "(record_id IS NOT NULL AND job_id IS NULL) "
            "OR (record_id IS NULL AND job_id IS NOT NULL)",
            name="ck_file_references_one_owner",
        ),
        UniqueConstraint("record_id", "sha256", name="uq_file_refs_record_sha"),
        UniqueConstraint("job_id", "sha256", name="uq_file_refs_job_sha"),
        Index("ix_file_references_sha256", "sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    record_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("records.id", ondelete="CASCADE"), nullable=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workflow_jobs.id", ondelete="CASCADE"), nullable=True
    )


# ---------------------------------------------------------------------------
# file_references maintenance
#
# Hooked on the ORM mapper rather than called from repositories so *every*
# writer is covered -- RecordRepository, the sync importer, restore paths --
# and none can forget. Uses the flush's own connection, so the reference rows
# commit or roll back atomically with the record/job write that caused them.
# ---------------------------------------------------------------------------


def _sync_file_refs(
    connection: Any,
    owner: str,
    owner_id: uuid.UUID,
    data: Any,
    *,
    is_new: bool = False,
) -> None:
    """Make the owner's file_references rows match the files its data cites.

    `is_new`: the owner was just inserted, so it has no rows yet -- nothing to
    read back, and (the common case) nothing to write when it cites no file."""
    from civex.domain.file_refs import collect_sha256_refs

    table = cast(Table, FileReference.__table__)
    owner_col = table.c[owner]
    wanted = collect_sha256_refs(data)
    if is_new and not wanted:
        return
    if not wanted:
        connection.execute(delete(table).where(owner_col == owner_id))
        return
    have = (
        set()
        if is_new
        else {
            row[0]
            for row in connection.execute(
                select(table.c.sha256).where(owner_col == owner_id)
            )
        }
    )
    stale = have - wanted
    if stale:
        connection.execute(
            delete(table).where(owner_col == owner_id, table.c.sha256.in_(stale))
        )
    fresh = wanted - have
    if fresh:
        other = "job_id" if owner == "record_id" else "record_id"
        connection.execute(
            insert(table),
            [
                {"id": _uuid(), "sha256": sha, owner: owner_id, other: None}
                for sha in sorted(fresh)
            ],
        )


def _sync_record_refs(
    connection: Any, record_id: uuid.UUID, data: Any, *, is_new: bool = False
) -> None:
    """Make the record's record_references rows match its data's references.
    `is_new`: just inserted, so there is nothing to read back or remove."""
    from civex.domain.references import collect_record_refs

    table = cast(Table, RecordReference.__table__)
    wanted = collect_record_refs(data)
    if is_new and not wanted:
        return
    if not wanted:
        connection.execute(delete(table).where(table.c.record_id == record_id))
        return
    have: set[tuple[uuid.UUID, uuid.UUID]] = (
        set()
        if is_new
        else {
            (row[0], row[1])
            for row in connection.execute(
                select(table.c.field_id, table.c.target_id).where(
                    table.c.record_id == record_id
                )
            )
        }
    )
    for field_id, target_id in have - wanted:
        connection.execute(
            delete(table).where(
                table.c.record_id == record_id,
                table.c.field_id == field_id,
                table.c.target_id == target_id,
            )
        )
    fresh = wanted - have
    if fresh:
        connection.execute(
            insert(table),
            [
                {"record_id": record_id, "field_id": f, "target_id": t}
                for f, t in sorted(fresh)
            ],
        )


def _data_changed(target: Any, attr: str) -> bool:
    return inspect(target).attrs[attr].history.has_changes()


@event.listens_for(Record, "after_insert")
def _record_inserted(mapper: Any, connection: Any, target: Record) -> None:
    _sync_file_refs(connection, "record_id", target.id, target.data, is_new=True)
    _sync_record_refs(connection, target.id, target.data, is_new=True)


@event.listens_for(Record, "after_update")
def _record_updated(mapper: Any, connection: Any, target: Record) -> None:
    if _data_changed(target, "data"):
        _sync_file_refs(connection, "record_id", target.id, target.data)
        _sync_record_refs(connection, target.id, target.data)


@event.listens_for(WorkflowJob, "after_insert")
def _job_inserted(mapper: Any, connection: Any, target: WorkflowJob) -> None:
    if target.input_data:
        _sync_file_refs(connection, "job_id", target.id, target.input_data, is_new=True)


@event.listens_for(WorkflowJob, "after_update")
def _job_updated(mapper: Any, connection: Any, target: WorkflowJob) -> None:
    if _data_changed(target, "input_data"):
        _sync_file_refs(connection, "job_id", target.id, target.input_data)
