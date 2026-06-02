"""
Plain Python dataclasses that travel between every layer: CLI, services, repos, server.
No SQLAlchemy, no Pydantic — just data.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class FieldDTO:
    id: uuid.UUID
    schema_id: uuid.UUID
    name: str
    dtype: str          # "integer" | "float" | "string" | "boolean" | "file"
    required: bool
    restrictions: dict[str, Any]
    created_at: datetime


@dataclass
class SchemaDTO:
    id: uuid.UUID
    name: str
    description: str | None
    parent_id: uuid.UUID | None
    created_at: datetime
    fields: list[FieldDTO] = field(default_factory=list)


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
    schema_id: uuid.UUID
    schema_name: str        # denormalised for display — resolved at read time
    record_count: int
    created_at: datetime


@dataclass
class FileRef:
    """
    Stored as a dict in record.data for 'file' dtype fields.
    The actual bytes live in .civex/objects/<sha256[:2]>/<sha256[2:]>.
    """
    sha256: str
    filename: str           # original user-facing filename
    size: int               # bytes

    def to_dict(self) -> dict[str, Any]:
        return {"sha256": self.sha256, "filename": self.filename, "size": self.size}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FileRef:
        return cls(sha256=d["sha256"], filename=d["filename"], size=d["size"])


@dataclass
class RecordDTO:
    id: uuid.UUID
    dataset_id: uuid.UUID
    data: dict[str, Any]    # field_name → coerced value or FileRef.to_dict()
    created_at: datetime
    updated_at: datetime
