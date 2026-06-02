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

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Transparently uses JSONB on PostgreSQL, JSON text on SQLite.
_JSON = JSON().with_variant(JSONB(), "postgresql")


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    fields: Mapped[list[Field]] = relationship(
        "Field", back_populates="schema", cascade="all, delete-orphan", order_by="Field.created_at"
    )
    parent: Mapped[Schema | None] = relationship(
        "Schema", remote_side="Schema.id", back_populates="children"
    )
    children: Mapped[list[Schema]] = relationship("Schema", back_populates="parent")
    datasets: Mapped[list[Dataset]] = relationship("Dataset", back_populates="schema")


class Field(Base):
    """
    A single field definition within a schema.
    dtype is one of: integer, float, string, boolean, file.
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    schema: Mapped[Schema] = relationship("Schema", back_populates="fields")


class Dataset(Base):
    """
    A named collection of records, all conforming to the same schema.
    Think: a study, an experiment run, a measurement session.
    """
    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))
    schema_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schemas.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    schema: Mapped[Schema] = relationship("Schema", back_populates="datasets")
    records: Mapped[list[Record]] = relationship(
        "Record", back_populates="dataset", cascade="all, delete-orphan"
    )


class Record(Base):
    """
    A single data entry in a dataset.
    data is a JSON dict — keys are field names, values are the typed field values.
    Validation against the schema's fields happens at write time in application code.
    """
    __tablename__ = "records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id"), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    dataset: Mapped[Dataset] = relationship("Dataset", back_populates="records")
