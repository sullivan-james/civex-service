"""
Plain Python dataclasses that travel between every layer: CLI, services, repos, server.
No SQLAlchemy, no Pydantic — just data.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


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
    dtype: str  # "integer" | "float" | "string" | "boolean" | "file" | "reference" | "enum" | "url" | "reference_list" | "tags"
    required: bool
    restrictions: dict[str, Any]
    created_at: datetime
    default_value: Any | None = None
    position: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "schema_id": str(self.schema_id),
            "name": self.name,
            "dtype": self.dtype,
            "required": self.required,
            "restrictions": self.restrictions,
            "default_value": self.default_value,
            "position": self.position,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FieldDTO:
        return cls(
            id=uuid.UUID(d["id"]),
            schema_id=uuid.UUID(d["schema_id"]),
            name=d["name"],
            dtype=d["dtype"],
            required=d["required"],
            restrictions=d.get("restrictions") or {},
            default_value=d.get("default_value"),
            position=d.get("position"),
            created_at=datetime.fromisoformat(d["created_at"]),
        )


@dataclass
class SchemaDTO:
    id: uuid.UUID
    name: str
    description: str | None
    parent_id: uuid.UUID | None
    created_at: datetime
    fields: list[FieldDTO] = field(default_factory=list)
    display_field: str | None = None  # field name to use as the record's natural name

    def to_dict(self) -> dict[str, Any]:
        # fields excluded — it's a loaded relationship, not a scalar property
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "display_field": self.display_field,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SchemaDTO:
        return cls(
            id=uuid.UUID(d["id"]),
            name=d["name"],
            description=d.get("description"),
            parent_id=uuid.UUID(d["parent_id"]) if d.get("parent_id") else None,
            display_field=d.get("display_field"),
            created_at=datetime.fromisoformat(d["created_at"]),
        )


@dataclass
class ResolvedField:
    """
    A field together with the name of the schema it was defined on.
    Used by SchemaService.collect_fields() to show field inheritance.
    """

    field: FieldDTO
    source_schema_name: str


@dataclass
class DatasetDTO:
    id: uuid.UUID
    name: str
    description: str | None
    record_count: int
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        # record_count excluded — it's a computed value, not stored on the entity
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DatasetDTO:
        return cls(
            id=uuid.UUID(d["id"]),
            name=d["name"],
            description=d.get("description"),
            record_count=0,
            created_at=datetime.fromisoformat(d["created_at"]),
        )


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
        )


@dataclass
class CommitDTO:
    id: uuid.UUID
    seq: int | None
    message: str | None
    created_at: datetime
    record_count: int
    schema_count: int
    dataset_count: int
    pushed_at: datetime | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "seq": self.seq,
            "message": self.message,
            "created_at": self.created_at.isoformat(),
            "record_count": self.record_count,
            "schema_count": self.schema_count,
            "dataset_count": self.dataset_count,
            "pushed_at": self.pushed_at.isoformat() if self.pushed_at else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CommitDTO:
        return cls(
            id=uuid.UUID(d["id"]),
            seq=d.get("seq"),
            message=d.get("message"),
            created_at=datetime.fromisoformat(d["created_at"]),
            record_count=d.get("record_count", 0),
            schema_count=d.get("schema_count", 0),
            dataset_count=d.get("dataset_count", 0),
            pushed_at=datetime.fromisoformat(d["pushed_at"])
            if d.get("pushed_at")
            else None,
        )


@dataclass
class AuditLogDTO:
    id: uuid.UUID
    commit_id: uuid.UUID | None
    action: str  # "create" | "update" | "delete"
    entity_type: str  # "record" | "schema" | "field" | "dataset"
    entity_id: uuid.UUID
    old_data: dict[str, Any] | None
    new_data: dict[str, Any] | None
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "commit_id": str(self.commit_id) if self.commit_id else None,
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": str(self.entity_id),
            "old_data": self.old_data,
            "new_data": self.new_data,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AuditLogDTO:
        return cls(
            id=uuid.UUID(d["id"]),
            commit_id=uuid.UUID(d["commit_id"]) if d.get("commit_id") else None,
            action=d["action"],
            entity_type=d["entity_type"],
            entity_id=uuid.UUID(d["entity_id"]),
            old_data=d.get("old_data"),
            new_data=d.get("new_data"),
            timestamp=datetime.fromisoformat(d["timestamp"]),
        )


@dataclass
class WorkflowJobDTO:
    id: uuid.UUID
    workflow_name: str
    record_id: uuid.UUID
    schema_name: str
    trigger: str  # record_created | record_updated | manual
    status: str  # pending | running | completed | failed
    error: str | None
    log: str | None  # captured stdout/stderr from execution
    input_data: (
        dict[str, Any] | None
    )  # pre-seeded __input__ step outputs for manual+batch runs
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    depth: int = 0  # trigger chain depth; jobs enqueued at MAX_JOB_DEPTH are refused


@dataclass
class AiUsageEventDTO:
    id: uuid.UUID
    provider: str  # "anthropic" | "openai-compat"
    model: str
    input_tokens: int
    output_tokens: int
    created_at: datetime
