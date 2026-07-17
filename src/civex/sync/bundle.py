"""
SyncBundle — the data transfer format for push/pull/clone.

All UUIDs are stored as strings; all datetimes as ISO 8601 strings.
Objects (binary blobs) are never included — only their sha256 hashes
are listed in object_refs so the receiver knows what exists remotely.

from_seq / to_seq are monotonic commit sequence numbers (integers).
The receiver stores to_seq as its new watermark after a successful sync.
deleted_record_ids carries IDs of records deleted in the transferred commits
so the receiver can remove them locally.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SyncBundle:
    version: int
    exported_at: str  # ISO 8601
    from_seq: int  # watermark lower bound (exclusive)
    to_seq: int  # watermark upper bound (inclusive); store this after sync
    schemas: list[dict[str, Any]]  # full Schema rows
    fields: list[dict[str, Any]]  # full Field rows
    datasets: list[dict[str, Any]]  # full Dataset rows
    records: list[dict[str, Any]]  # records touched in commits (from_seq, to_seq]
    deleted_record_ids: list[str] = field(
        default_factory=list
    )  # IDs deleted in those commits
    object_refs: list[str] = field(default_factory=list)  # sha256s that exist on source
    commits: list[dict[str, Any]] = field(default_factory=list)
    audit_log: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
                "version": self.version,
                "exported_at": self.exported_at,
                "from_seq": self.from_seq,
                "to_seq": self.to_seq,
                "schemas": self.schemas,
                "fields": self.fields,
                "datasets": self.datasets,
                "records": self.records,
                "deleted_record_ids": self.deleted_record_ids,
                "object_refs": self.object_refs,
                "commits": self.commits,
                "audit_log": self.audit_log,
            }
        )

    @classmethod
    def from_json(cls, text: str) -> SyncBundle:
        d = json.loads(text)
        return cls(
            version=d["version"],
            exported_at=d["exported_at"],
            from_seq=d.get("from_seq", 0),
            to_seq=d.get("to_seq", 0),
            schemas=d["schemas"],
            fields=d["fields"],
            datasets=d["datasets"],
            records=d["records"],
            deleted_record_ids=d.get("deleted_record_ids", []),
            object_refs=d.get("object_refs", []),
            commits=d.get("commits", []),
            audit_log=d.get("audit_log", []),
        )
