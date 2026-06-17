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

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, TypeDecorator, UniqueConstraint
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

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
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
    description: Mapped[str | None] = mapped_column(String(1000))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("schemas.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(_UTCDateTime(), default=_now)

    fields: Mapped[list[Field]] = relationship(
        "Field", back_populates="schema", cascade="all, delete-orphan", order_by="Field.created_at"
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
    schema_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schemas.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    dtype: Mapped[str] = mapped_column(String(50), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    restrictions: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(_UTCDateTime(), default=_now)

    schema: Mapped[Schema] = relationship("Schema", back_populates="fields")


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

    records: Mapped[list[Record]] = relationship(
        "Record", back_populates="dataset", cascade="all, delete-orphan"
    )


class Record(Base):
    """
    A single data entry in a dataset, typed by its schema.
    data is a JSON dict — keys are field names, values are the typed field values.
    Validation against the schema's fields happens at write time in application code.

    parent_record_id links child-schema records to the parent record they extend
    (e.g. a Recording record referencing its Encounter record within the same dataset).
    """
    __tablename__ = "records"
    __table_args__ = (
        Index("ix_records_dataset_schema", "dataset_id", "schema_id"),
        Index("ix_records_dataset_created", "dataset_id", "created_at"),
        Index("ix_records_dataset_parent", "dataset_id", "parent_record_id"),
        # GIN index enables containment (@>) queries on JSONB data fields.
        # On SQLite this degrades to a plain B-tree on the JSON text column (harmless).
        Index("ix_records_data_gin", "data", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id"), nullable=False)
    schema_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schemas.id"), nullable=False)
    parent_record_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("records.id"), nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(_UTCDateTime(), default=_now)
    updated_at: Mapped[datetime] = mapped_column(_UTCDateTime(), default=_now, onupdate=_now)
    search_vector: Mapped[str | None] = mapped_column(_TSVECTOR, nullable=True, default=None)

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
    commit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("commits.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)   # create | update | delete
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)  # record | schema | field | dataset
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
    record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("records.id"), nullable=False)
    schema_name: Mapped[str] = mapped_column(String(255), nullable=False)
    trigger: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    log: Mapped[str | None] = mapped_column(String, nullable=True)
    input_data: Mapped[dict[str, Any] | None] = mapped_column(_JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(_UTCDateTime(), default=_now)
    started_at: Mapped[datetime | None] = mapped_column(_UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(_UTCDateTime(), nullable=True)

    record: Mapped[Record] = relationship("Record")
