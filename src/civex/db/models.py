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
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    nulls_last,
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
    # headers and display_fields reference it as text; label absorbs the
    # cosmetic churn so renames stay rare. Null → derived from name.
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(String(1000))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("schemas.id"), nullable=True
    )
    display_fields: Mapped[list[str]] = mapped_column(
        _JSON, nullable=False, default=list, server_default="[]"
    )
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
    A saved column/filter/sort definition against a base schema's own
    fields -- the definition a table view in the UI reads back to
    reconstruct itself. filter_tree is the same AND/OR shape records
    queries use (civex.domain.filters); columns/sort reference field names
    the way Schema.display_fields does, not field ids, so renaming a field
    on the schema is not reflected here automatically.
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
    created_at: Mapped[datetime] = mapped_column(_UTCDateTime(), default=_now)
    # See Schema.deleted_at -- same soft-delete marker, same reason. Deleting
    # a dataset cascades to soft-delete its records (DatasetRepository).
    deleted_at: Mapped[datetime | None] = mapped_column(
        _UTCDateTime(), nullable=True, default=None
    )

    records: Mapped[list[Record]] = relationship(
        "Record", back_populates="dataset", cascade="all, delete-orphan"
    )


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
        # GIN index enables containment (@>) queries on JSONB data fields.
        # On SQLite this degrades to a plain B-tree on the JSON text column (harmless).
        Index("ix_records_data_gin", "data", postgresql_using="gin"),
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
    schema: Mapped[Schema] = relationship("Schema")


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
    status: pending → running → completed | failed
    trigger: record_created | record_updated | manual
    """

    __tablename__ = "workflow_jobs"

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
    __table_args__ = (UniqueConstraint("job_id", "position"),)

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
