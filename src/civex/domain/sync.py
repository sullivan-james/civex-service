"""What sync sends: the wire types shared by the authority, the client and the
transport. Plain dataclasses; the HTTP layer validates them with its own models.

One authority holds a project's truth and numbers every change it accepts
(`hub_seq`). A device sends the changes it made (`SyncEntry`, an audit entry)
and reads everyone's back in that order. A change is identified by its audit
entry's id, which is what makes sending it twice harmless.
"""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from civex.domain import hlc

# Bumped when the wire format changes in a way an older peer can't read.
PROTOCOL_VERSION = 1

# The order a project's things must exist in: each refers to the ones before it.
ENTITY_ORDER = ("schema", "field", "dataset", "view", "record")

# How the authority settled a change that a device sent.
APPLIED = "applied"  # taken as sent
MERGED = "merged"  # taken, with edits to other fields folded in
CONFLICT = "conflict"  # a field both changed: the authority's value stayed
DUPLICATE = "duplicate"  # seen before; nothing done
REJECTED = "rejected"  # can never be accepted (it breaks a rule); say why
DEFERRED = "deferred"  # not yet (a file hasn't arrived); send it again later

RETRY_STATUSES = frozenset({DEFERRED})

ACTIONS = frozenset({"create", "update", "delete", "restore", "purge"})
# A delete's time becomes the `deleted_at` of what it deletes, so a device whose
# clock is further ahead than this is refused rather than stamping the future.
MAX_DELETE_AHEAD = timedelta(milliseconds=hlc.MAX_DRIFT_MS)


@dataclass
class SyncBatchInfo:
    """The bulk operation a change belonged to, so it is one event on every
    device and a delete's records share one deleted-at."""

    id: uuid.UUID
    kind: str
    label: str | None
    ref: str | None
    created_at: str  # ISO 8601

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "kind": self.kind,
            "label": self.label,
            "ref": self.ref,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SyncBatchInfo:
        return cls(
            id=uuid.UUID(d["id"]),
            kind=d["kind"],
            label=d.get("label"),
            ref=d.get("ref"),
            created_at=d["created_at"],
        )


@dataclass
class SyncEntry:
    """One change as it travels: an audit entry, with its snapshots."""

    id: uuid.UUID
    action: str  # create | update | delete | restore | purge
    entity_type: str
    entity_id: uuid.UUID
    old_data: dict[str, Any] | None
    new_data: dict[str, Any] | None
    timestamp: str  # ISO 8601, when it was made
    actor: str | None = None
    device_id: str | None = None
    hlc: str | None = None
    batch: SyncBatchInfo | None = None
    # Only on what the authority serves:
    hub_seq: int | None = None
    # The authority did not take `new_data` as sent (it merged or kept its own
    # value); a later entry carries the state it settled on, so a device skips
    # applying this one.
    superseded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": str(self.entity_id),
            "old_data": self.old_data,
            "new_data": self.new_data,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "device_id": self.device_id,
            "hlc": self.hlc,
            "batch": self.batch.to_dict() if self.batch else None,
            "hub_seq": self.hub_seq,
            "superseded": self.superseded,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SyncEntry:
        return cls(
            id=uuid.UUID(d["id"]),
            action=d["action"],
            entity_type=d["entity_type"],
            entity_id=uuid.UUID(d["entity_id"]),
            old_data=d.get("old_data"),
            new_data=d.get("new_data"),
            timestamp=d["timestamp"],
            actor=d.get("actor"),
            device_id=d.get("device_id"),
            hlc=d.get("hlc"),
            batch=SyncBatchInfo.from_dict(d["batch"]) if d.get("batch") else None,
            hub_seq=d.get("hub_seq"),
            superseded=bool(d.get("superseded", False)),
        )


def problem_with(entry: SyncEntry, now: datetime | None = None) -> str | None:
    """Why a change can never be taken, or None. The one place a change's shape
    is checked, so nothing downstream has to cope with a value it can't read:
    a single odd entry must be refused by itself, not fail the whole push."""
    now = now or datetime.now(timezone.utc)
    if entry.entity_type not in ENTITY_ORDER:
        return f"Unknown kind '{entry.entity_type}'"
    if entry.action not in ACTIONS:
        return f"Unknown action '{entry.action}'"
    for name in ("old_data", "new_data"):
        value = getattr(entry, name)
        if value is not None and not isinstance(value, dict):
            return f"{name} is not an object"
    if entry.action in ("create", "update", "restore") and (
        not entry.new_data or str(entry.new_data.get("id")) != str(entry.entity_id)
    ):
        return "The change does not say what the thing became"
    try:
        made = datetime.fromisoformat(entry.timestamp)
    except (TypeError, ValueError):
        return "The change has no readable time"
    if made.tzinfo is None:
        made = made.replace(tzinfo=timezone.utc)
    if entry.action == "delete" and made > now + MAX_DELETE_AHEAD:
        return "This device's clock is more than an hour ahead of the server's"
    if entry.hlc is not None and not hlc.is_valid(entry.hlc):
        return "The change's clock stamp is not valid"
    return None


@dataclass
class OpResult:
    """How the authority settled one change a device sent."""

    op_id: uuid.UUID
    status: str
    message: str | None = None
    # For `conflict`/`merged`: the values that did not go in.
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    hub_seq: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "op_id": str(self.op_id),
            "status": self.status,
            "message": self.message,
            "conflicts": self.conflicts,
            "hub_seq": self.hub_seq,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OpResult:
        return cls(
            op_id=uuid.UUID(d["op_id"]),
            status=d["status"],
            message=d.get("message"),
            conflicts=list(d.get("conflicts") or []),
            hub_seq=d.get("hub_seq"),
        )


@dataclass
class PushResult:
    results: list[OpResult]
    head_seq: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "results": [r.to_dict() for r in self.results],
            "head_seq": self.head_seq,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PushResult:
        return cls([OpResult.from_dict(r) for r in d["results"]], int(d["head_seq"]))


@dataclass
class FeedPage:
    entries: list[SyncEntry]
    head_seq: int  # the authority's latest number
    more: bool  # there are entries past this page

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "head_seq": self.head_seq,
            "more": self.more,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FeedPage:
        return cls(
            [SyncEntry.from_dict(e) for e in d["entries"]],
            int(d["head_seq"]),
            bool(d["more"]),
        )


@dataclass
class Hello:
    """What an authority says about itself to a device that connects."""

    protocol_version: int
    project_id: uuid.UUID
    head_seq: int
    empty: bool  # holds none of the project's things yet
    seeded_by: str | None  # the device that put the first data in, if any
    device_name: str  # what the token the caller used is called

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "project_id": str(self.project_id),
            "head_seq": self.head_seq,
            "empty": self.empty,
            "seeded_by": self.seeded_by,
            "device_name": self.device_name,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Hello:
        return cls(
            protocol_version=int(d["protocol_version"]),
            project_id=uuid.UUID(d["project_id"]),
            head_seq=int(d["head_seq"]),
            empty=bool(d["empty"]),
            seeded_by=d.get("seeded_by"),
            device_name=d.get("device_name", ""),
        )


@dataclass
class SnapshotPage:
    """A page of one kind of thing as it is now, for a device joining the
    project. Read with the authority's `head_seq` taken *first*, so anything
    that changes while a device reads is picked up from the feed afterwards."""

    kind: str
    items: list[dict[str, Any]]
    more: bool
    head_seq: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "items": self.items,
            "more": self.more,
            "head_seq": self.head_seq,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SnapshotPage:
        return cls(d["kind"], list(d["items"]), bool(d["more"]), int(d["head_seq"]))


class SyncError(RuntimeError):
    """Sync could not finish. `retryable` is true for what trying again can fix
    (a network failure); a refused token or a protocol mismatch is not."""

    def __init__(self, message: str, retryable: bool = True, status: int = 400) -> None:
        super().__init__(message)
        self.retryable = retryable
        # How an authority reports it over HTTP: 401 no/invalid token, 403 a
        # token used from another device, 426 a protocol this server can't speak.
        self.status = status


@dataclass
class SyncMetaDTO:
    project_id: uuid.UUID
    head_seq: int  # authority: the last number handed out
    cursor: int  # device: the last of the authority's numbers applied here
    seeded_by: str | None
    last_synced_at: str | None
    last_error: str | None
    last_error_at: str | None


@dataclass
class SyncDeviceDTO:
    id: uuid.UUID
    name: str
    device_id: str | None
    created_at: str
    last_seen_at: str | None
    revoked_at: str | None


@dataclass
class SyncConflictDTO:
    id: uuid.UUID
    kind: str  # conflict | rejected | edit_vs_delete
    entity_type: str
    entity_id: uuid.UUID
    field: str | None
    yours: Any
    theirs: Any
    op_id: uuid.UUID | None
    device_name: str | None
    message: str | None
    status: str  # open | resolved
    created_at: str
    resolved_at: str | None
    resolution: str | None  # mine | theirs | value | edited | delete | retry
    # What the value was before either side changed it, and who wrote the one that
    # stayed, and when.
    base: Any = None
    theirs_actor: str | None = None
    theirs_at: str | None = None
    # Response-only, worked out when read (see `FieldValueDTO`): what a person
    # needs to recognise the record and the field, and whether the value they are
    # being asked about is still the one on the record.
    record_name: str | None = None
    dataset_name: str | None = None
    schema_name: str | None = None
    field_label: str | None = None
    dtype: str | None = None
    current: Any = None
    stale: bool = False
    record_deleted: bool = False
    # What can be done about it (see `SyncService.resolve_conflict`), so no screen
    # keeps its own copy of the rule.
    takes: list[str] = dataclasses.field(default_factory=list)
    # The other values the same edit set that did go in: what a person checking a
    # clash wants to see is that nothing else of theirs was lost.
    also_saved: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    # For a refused change or an edit/delete that met its opposite: what was
    # attempted (create | update | delete) and the fields it set, each with the
    # value before, the value it set and the value on the record now, so the
    # record page can show the change in place of describing it.
    attempted: str | None = None
    changes: list[dict[str, Any]] = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "kind": self.kind,
            "entity_type": self.entity_type,
            "entity_id": str(self.entity_id),
            "field": self.field,
            "yours": self.yours,
            "theirs": self.theirs,
            "op_id": str(self.op_id) if self.op_id else None,
            "device_name": self.device_name,
            "message": self.message,
            "status": self.status,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "resolution": self.resolution,
            "base": self.base,
            "theirs_actor": self.theirs_actor,
            "theirs_at": self.theirs_at,
            "record_name": self.record_name,
            "dataset_name": self.dataset_name,
            "schema_name": self.schema_name,
            "field_label": self.field_label,
            "dtype": self.dtype,
            "current": self.current,
            "stale": self.stale,
            "record_deleted": self.record_deleted,
            "takes": self.takes,
            "also_saved": self.also_saved,
            "attempted": self.attempted,
            "changes": self.changes,
        }


class SyncTransport(Protocol):
    """How a device talks to an authority. HTTP in use; tests supply one that
    calls an authority in the same process (and ones that fail on purpose)."""

    def hello(self) -> Hello: ...
    def push(self, entries: list[SyncEntry]) -> PushResult: ...
    def feed(self, after: int, limit: int) -> FeedPage: ...
    def snapshot(self, kind: str, offset: int, limit: int) -> SnapshotPage: ...
    def missing_files(self, shas: list[str]) -> list[str]: ...
    def upload_file(self, sha256: str, path: Path) -> None: ...
    def download_file(self, sha256: str, dest: Path) -> None: ...
