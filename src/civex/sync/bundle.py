"""
SyncBundle — the data transfer format for push/pull/clone.

All UUIDs are stored as strings; all datetimes as ISO 8601 strings.
Objects (binary blobs) are never included — only their sha256 hashes
are listed in object_refs so the receiver knows what exists remotely.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SyncBundle:
    version: int
    exported_at: str                  # ISO 8601
    schemas: list[dict[str, Any]]     # full Schema rows
    fields: list[dict[str, Any]]      # full Field rows
    datasets: list[dict[str, Any]]    # full Dataset rows
    records: list[dict[str, Any]]     # incremental Record rows (updated_at >= since)
    object_refs: list[str] = field(default_factory=list)  # sha256s that exist on source

    def to_json(self) -> str:
        return json.dumps({
            "version": self.version,
            "exported_at": self.exported_at,
            "schemas": self.schemas,
            "fields": self.fields,
            "datasets": self.datasets,
            "records": self.records,
            "object_refs": self.object_refs,
        })

    @classmethod
    def from_json(cls, text: str) -> SyncBundle:
        d = json.loads(text)
        return cls(
            version=d["version"],
            exported_at=d["exported_at"],
            schemas=d["schemas"],
            fields=d["fields"],
            datasets=d["datasets"],
            records=d["records"],
            object_refs=d.get("object_refs", []),
        )
