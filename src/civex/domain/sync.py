"""What sync sends: the wire types shared by the authority, the client and the
transport. Plain dataclasses; the HTTP layer validates them with its own models.

One authority holds a project's truth and numbers every change it accepts
(`hub_seq`). A device sends the changes it made (`SyncEntry`, an audit entry)
and reads everyone's back in that order. A change is identified by its audit
entry's id, which is what makes sending it twice harmless.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any, Protocol

from civex.domain import features
from civex.domain.field_descriptors import FIELD_TYPES
from civex.domain import hlc

# The wire formats this civex speaks. MAX goes up when what travels changes in a
# way an older peer can't read (a new kind, a new field in `WIRE_FIELDS`, a
# changed meaning); MIN goes up when an older one is no longer served. An
# authority is upgraded first and answers a device on any version both speak.
PROTOCOL_MIN = 3
PROTOCOL_MAX = 6
# The first version whose feed tells a device how far the authority looked
# (`FeedPage.through`) and whose hello lists the collections it may read: what a
# device whose person may not read the whole project needs to sync it.
SCOPED_PROTOCOL = 5
# The oldest version this civex still serves but its next release will not, so
# devices still on it are told to update before they are cut off (`Hello.
# protocol_retiring`). None while nothing is being retired. Raise
# `PROTOCOL_MIN` only in the release after one that set this.
PROTOCOL_RETIRING: int | None = None
# Optional features, by name, that a peer can look for in `Hello`. Adding one is
# not a protocol change; an older peer just doesn't have it.
CAPABILITIES: tuple[str, ...] = (
    "library",
    "device_login",
    "file_packs",
    "gzip_requests",
)
# JSON request bodies (a push) may be sent `Content-Encoding: gzip`; the
# authority decompresses them up to a cap (`server.sync_policy`).
GZIP_REQUESTS = "gzip_requests"
# Many small files in one request (`POST /files/pack`): each is checked and
# stored, and the answer says which went in. Offered by every authority that
# serves; one without it is sent the files one request each.
FILE_PACKS = "file_packs"
# A big file in numbered parts, several at a time, resumable: `POST
# /files/{sha}/parts` (answers which parts are held), `PUT /files/{sha}/parts/{n}`
# and `POST /files/{sha}/parts/complete`. Offered when the authority's files are
# on drives (a bucket takes parts straight, `direct_files`).
FILE_PARTS = "file_parts"
# The limits a pack and a part keep to, on both sides: a file in a pack is
# smaller than PACK_FILE_MAX, a pack holds at most PACK_MAX_FILES files and
# PACK_MAX_BYTES bytes; a part is FILE_PART_BYTES unless the file is so big that
# MAX_FILE_PARTS parts would not cover it.
PACK_FILE_MAX = 64 * 1024 * 1024
PACK_MAX_FILES = 1000
PACK_MAX_BYTES = 256 * 1024 * 1024
FILE_PART_BYTES = 16 * 1024 * 1024
FILE_PART_MIN = 1024 * 1024
FILE_PART_MAX = 64 * 1024 * 1024
MAX_FILE_PARTS = 10_000
# A device may ask to join without an invite: it shows a short code, a person
# approves it on the authority (`POST /device-login`, polled at
# `GET /device-login/{device_code}`).
DEVICE_LOGIN = "device_login"
# Files go straight between a device and the authority's storage (a bucket) by
# presigned URL: `POST /files/{sha}/upload` answers where, `POST
# /files/{sha}/complete` records it, and `GET /files/{sha}` answers 307. An
# authority offers it when its host has the feature of the same name.
DIRECT_FILES = features.DIRECT_FILES

# The order a project's things must exist in: each refers to the ones before it.
ENTITY_ORDER = (
    "schema",
    "field",
    "dataset",
    "view",
    "dashboard",
    "record",
    "note",
)

# A kind that is no longer synced (protocol 6): releases are published on a
# host and never travel, so a device never sends one, the authority never feeds
# or snapshots one and refuses one it is sent (`REFUSAL_NOT_SYNCED`). Kept out
# of `ENTITY_ORDER`, so nothing seeds, joins or counts them.
NOT_SYNCED_KINDS = frozenset({"release"})
# Releases were part of protocols 4 and 5, so a device on either may still ask
# for their snapshot: it is answered with an empty page, never an error.
NOT_SYNCED_AFTER = 5

# What of each kind travels, and nothing else: a column added for this machine
# alone (a cache, a search index) stays off the wire, and adding one here is a
# protocol change (`tests/sync/test_wire_shapes.py` holds the two together).
# `dataset` also carries its schema list, by id and, for history, by name.
WIRE_FIELDS: dict[str, frozenset[str]] = {
    "schema": frozenset(
        {
            "id",
            "name",
            "label",
            "description",
            "parent_id",
            "display_template",
            "unique_keys",
            "charts",
            "created_at",
            "deleted_at",
        }
    ),
    "field": frozenset(
        {
            "id",
            "schema_id",
            "name",
            "label",
            "dtype",
            "required",
            "default_value",
            "restrictions",
            "position",
            "created_at",
            "deleted_at",
        }
    ),
    "dataset": frozenset(
        {
            "id",
            "name",
            "description",
            "scope",
            "timezone",
            "created_at",
            "deleted_at",
        }
    ),
    "view": frozenset(
        {
            "id",
            "schema_id",
            "name",
            "filter_tree",
            "columns",
            "sort",
            "files_layout",
            "created_at",
        }
    ),
    "dashboard": frozenset({"id", "cards", "created_at"}),
    "record": frozenset(
        {
            "id",
            "schema_id",
            "dataset_id",
            "parent_record_id",
            "data",
            "created_at",
            "updated_at",
            "deleted_at",
        }
    ),
    "note": frozenset(
        {
            "id",
            "record_id",
            "thread_id",
            "body",
            "author",
            "created_at",
            "edited_at",
            "resolved_at",
            "resolved_by",
            "deleted_at",
        }
    ),
}

# What each protocol version added, so a server still answers a device on an
# older one with only what it can read (`kinds_for`, `entry_for`,
# `snapshot_for`; applied in the peer router, never in the core): a kind, or a
# kind's field, and the version it travels from.
KINDS_SINCE: dict[str, int] = {"dashboard": 4, "note": 4}
FIELDS_SINCE: dict[str, dict[str, int]] = {"schema": {"charts": 4}}


def kinds_for(protocol: int) -> tuple[str, ...]:
    """The kinds a peer on `protocol` knows, in `ENTITY_ORDER`."""
    return tuple(k for k in ENTITY_ORDER if KINDS_SINCE.get(k, 0) <= protocol)


def snapshot_for(
    protocol: int, kind: str, snapshot: dict[str, Any] | None
) -> dict[str, Any] | None:
    """A snapshot without the fields a peer on `protocol` can't read."""
    newer = {f for f, v in FIELDS_SINCE.get(kind, {}).items() if v > protocol}
    if snapshot is None or not newer:
        return snapshot
    return {k: v for k, v in snapshot.items() if k not in newer}


def entry_for(protocol: int, entry: SyncEntry) -> SyncEntry | None:
    """An entry as a peer on `protocol` can read it: None for a kind it
    doesn't know, else without the fields it doesn't (an edit of only those
    leaves an edit of nothing, which applies as no change)."""
    if entry.entity_type in NOT_SYNCED_KINDS or entry.entity_type not in kinds_for(
        protocol
    ):
        return None
    kind = entry.entity_type
    newer = {f for f, v in FIELDS_SINCE.get(kind, {}).items() if v > protocol}
    if not newer:
        return entry
    return dataclasses.replace(
        entry,
        old_data=snapshot_for(protocol, kind, entry.old_data),
        new_data=snapshot_for(protocol, kind, entry.new_data),
        delta=(
            None
            if entry.delta is None
            else {
                p: c for p, c in entry.delta.items() if p.split(".", 1)[0] not in newer
            }
        ),
    )


# Actions whose snapshots are the thing itself (a purge carries a tombstone).
_STATE_ACTIONS = frozenset({"create", "update", "delete", "restore"})


def wire_state(kind: str, snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    """A snapshot as it travels: only its kind's `WIRE_FIELDS`."""
    if snapshot is None or kind not in WIRE_FIELDS:
        return snapshot
    allowed = WIRE_FIELDS[kind]
    return {k: v for k, v in snapshot.items() if k in allowed}


def _wire_delta(kind: str, delta: dict[str, Any] | None) -> dict[str, Any] | None:
    if delta is None or kind not in WIRE_FIELDS:
        return delta
    allowed = WIRE_FIELDS[kind]
    return {p: c for p, c in delta.items() if p.split(".", 1)[0] in allowed}


def protocol_range(header: str | None) -> tuple[int, int] | None:
    """(min, max) from `X-Civex-Protocol` ("2" or "2-3"); None if unreadable."""
    lo, _, hi = (header or "").strip().partition("-")
    try:
        low, high = int(lo), int(hi or lo)
    except ValueError:
        return None
    return (low, high) if 0 < low <= high else None


def protocol_header() -> str:
    """What this civex sends as `X-Civex-Protocol`."""
    if PROTOCOL_MIN == PROTOCOL_MAX:
        return str(PROTOCOL_MAX)
    return f"{PROTOCOL_MIN}-{PROTOCOL_MAX}"


def agree(theirs: tuple[int, int]) -> int | None:
    """The newest version both sides speak, or None."""
    version = min(theirs[1], PROTOCOL_MAX)
    return version if version >= max(theirs[0], PROTOCOL_MIN) else None


def protocol_mismatch(
    theirs: tuple[int, int] | None,
    there: str,
    here: str,
    their_version: str | None = None,
) -> str:
    """Why two peers can't sync, saying which one to update. `there` and `here`
    name the two sides ("the server", "this computer"); `their_version` is the
    civex the other side runs, when it said."""
    runs = f" ({there} runs civex {their_version})" if their_version else ""
    if theirs is None or theirs[1] < PROTOCOL_MIN:
        spoken = f"sync protocol {theirs[1]}" if theirs else "an older sync protocol"
        return (
            f"Update civex on {there}{runs}: it speaks {spoken}, and {here} "
            f"needs {PROTOCOL_MIN} or later."
        )
    return (
        f"Update civex on {here}{runs}: {there} needs sync protocol {theirs[0]} "
        f"or later, and {here} speaks up to {PROTOCOL_MAX}."
    )


def retiring_notice(retiring: int | None, agreed: int | None) -> str | None:
    """What to tell a person when the server will stop accepting the protocol
    this device speaks with it at its next update (None: nothing to say)."""
    if retiring is None or agreed is None or agreed > retiring:
        return None
    return (
        "The server will stop accepting this version of civex after its next "
        "update. Update civex on this computer to keep syncing."
    )


def unreadable_field_type(kind: str, snapshot: Any, delta: Any = None) -> str | None:
    """A field type this civex doesn't know, in a field's state or change from
    another civex (None when there is none): such a field can't be applied
    here, and the records using it couldn't be read."""
    if kind != "field":
        return None
    seen = [snapshot.get("dtype") if isinstance(snapshot, dict) else None]
    change = delta.get("dtype") if isinstance(delta, dict) else None
    if isinstance(change, dict):
        seen.append(change.get("after"))
    return next((t for t in seen if t is not None and t not in FIELD_TYPES), None)


def newer_field_type(dtype: str) -> SyncError:
    return SyncError(
        f"The server holds a field of a type this civex doesn't know ('{dtype}'). "
        "Update civex on this computer to keep syncing.",
        retryable=False,
    )


# How the authority settled a change that a device sent.
APPLIED = "applied"  # taken as sent
MERGED = "merged"  # taken, with edits to other fields folded in
CONFLICT = "conflict"  # a field both changed: the authority's value stayed
DUPLICATE = "duplicate"  # seen before; nothing done
REJECTED = "rejected"  # can never be accepted (it breaks a rule); say why
DEFERRED = "deferred"  # not yet (a file hasn't arrived); send it again later

# How sync itself settles a conflict (the column holds at most 10 chars): what
# was waiting for review when the project moves to another server (that
# server's answers were about it, not the new one); and a refusal of a thing's
# create, still unsettled, once a fill of the authority takes the thing after all.
FOLLOWED = "followed"
TAKEN = "taken"

RETRY_STATUSES = frozenset({DEFERRED})

# Why a refusal (`REJECTED`) was made, in the `code` of its `conflicts` item
# (absent from an older authority). A permission refusal can go through once the
# device may do it, so a device sends it again later; any other would only fail
# again.
REFUSAL_PERMISSION = "permission"
REFUSAL_INVALID = "invalid"
# The change is about a kind that is not synced (a release: those are published
# on a host). Never sent again; the device keeps what it made.
REFUSAL_NOT_SYNCED = "not_synced"
NOT_SYNCED_MESSAGE = (
    "Releases are published on a civex hub and are not synced: make this one there."
)

# A change that went in (a record) although its values break a data rule of the
# project (a required field left empty, a value outside its field's
# restrictions): the answer's `conflicts` item has kind `UNFIT` and this code. The
# record is kept and shown by everyone as it is; the flag is a fact about the
# data, worked out again from it, and the pusher's item is only the nudge.
UNFIT = "unfit"
UNFIT_DATA = "data"

# What a device keeps when the authority's rules refuse it, marked (`rejected`),
# to send again or let go: never put back where the authority has it. Until it
# is settled the thing counts as changed here, so the authority's later changes
# to it wait (and do not quietly overwrite it).
KEPT_STRUCTURE = frozenset({"schema", "field"})

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
    # The device whose token sent it: stamped by the authority, never taken
    # from what a device sends.
    device: str | None = None
    device_id: str | None = None
    hlc: str | None = None
    batch: SyncBatchInfo | None = None
    # Only on what the authority serves:
    hub_seq: int | None = None
    # The authority did not take `new_data` as sent (it merged or kept its own
    # value); a later entry carries the state it settled on, so a device skips
    # applying this one.
    superseded: bool = False
    # An edit or a restore travels as what changed (`audit_diff.make_delta`),
    # with `new_data` the thing's identity and no `old_data`; a create carries
    # the thing as made and a delete the thing as it was (`stored_form`).
    delta: dict[str, Any] | None = None
    # The action it is part of (`audit_log.op_id`): an authority takes the
    # entries sharing it together or not at all. None for one on its own.
    op: str | None = None

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
            "device": self.device,
            "device_id": self.device_id,
            "hlc": self.hlc,
            "batch": self.batch.to_dict() if self.batch else None,
            "hub_seq": self.hub_seq,
            "superseded": self.superseded,
            "delta": self.delta,
            "op": self.op,
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
            device=d.get("device"),
            device_id=d.get("device_id"),
            hlc=d.get("hlc"),
            batch=SyncBatchInfo.from_dict(d["batch"]) if d.get("batch") else None,
            hub_seq=d.get("hub_seq"),
            superseded=bool(d.get("superseded", False)),
            delta=d.get("delta"),
            op=str(d["op"]) if d.get("op") else None,
        )

    def on_the_wire(self) -> SyncEntry:
        """This entry as it travels: snapshots and delta cut to `WIRE_FIELDS`
        (a purge's tombstone travels as it is: nothing applies it as state)."""
        if self.action not in _STATE_ACTIONS:
            return self
        kind = self.entity_type
        return dataclasses.replace(
            self,
            old_data=wire_state(kind, self.old_data),
            new_data=wire_state(kind, self.new_data),
            delta=_wire_delta(kind, self.delta),
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
    for name in ("old_data", "new_data", "delta"):
        value = getattr(entry, name)
        if value is not None and not isinstance(value, dict):
            return f"{name} is not an object"
    for path, change in (entry.delta or {}).items():
        if not isinstance(change, dict) or not set(change) <= {"before", "after"}:
            return f"The change to {path} is not a before and after"
    if entry.delta is not None and entry.action not in ("update", "restore"):
        return f"A '{entry.action}' carries the thing itself, not what changed"
    if entry.action in ("create", "update", "restore") and (
        not entry.new_data or str(entry.new_data.get("id")) != str(entry.entity_id)
    ):
        return "The change does not say what the thing became"
    if entry.action in _STATE_ACTIONS:
        keys = (
            set(entry.old_data or {})
            | set(entry.new_data or {})
            | {path.split(".", 1)[0] for path in entry.delta or {}}
        )
        if unknown := sorted(keys - WIRE_FIELDS[entry.entity_type]):
            return f"The change carries what this server doesn't keep: {', '.join(unknown)}"
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
    # A delete of a record that was already deleted here, by another change:
    # taken and written down (so undo knows of it) but it changed nothing, so
    # the device shows it as done by whoever got there first, not as its own.
    already_done: bool = False
    # Set on an answer given again to a change sent before (never on the wire):
    # nothing was done this time, so it is not news to a host.
    replayed: bool = field(default=False, compare=False, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "op_id": str(self.op_id),
            "status": self.status,
            "message": self.message,
            "conflicts": self.conflicts,
            "hub_seq": self.hub_seq,
            **({"already_done": True} if self.already_done else {}),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OpResult:
        return cls(
            op_id=uuid.UUID(d["op_id"]),
            status=d["status"],
            message=d.get("message"),
            conflicts=list(d.get("conflicts") or []),
            hub_seq=d.get("hub_seq"),
            already_done=bool(d.get("already_done", False)),
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


@dataclass(frozen=True)
class PushAccepted:
    """What a host is told after a device's push has been committed
    (`Project.push_accepted`): who sent it and what the authority took, so a
    host can attribute and count pushes without reading its responses. `taken`
    are the ids of the changes taken into the project (`APPLIED` or `MERGED`),
    and `counts` how many changes ended in each status, refused ones included.
    There is no commit as such: a change is numbered (`first_seq`..`last_seq`,
    the positions in the feed)."""

    device_id: str | None
    device: str
    actor: str | None
    taken: tuple[uuid.UUID, ...]
    counts: Mapping[str, int]
    changed: Mapping[str, int]  # taken changes by kind of thing (record, note, ...)
    first_seq: int | None
    last_seq: int | None
    head_seq: int

    @classmethod
    def of(
        cls,
        who: Principal,
        actor: str | None,
        entries: Sequence[SyncEntry],
        result: PushResult,
    ) -> PushAccepted | None:
        """The report of a push, or None when it took nothing (all refused,
        repeated or held back): nothing happened that a host would count."""
        kinds = {e.id: e.entity_type for e in entries}
        # A change sent again is answered as before and done no more than once.
        fresh = [r for r in result.results if not r.replayed]
        taken = [r for r in fresh if r.status in (APPLIED, MERGED)]
        if not taken:
            return None
        counts: dict[str, int] = {}
        for r in fresh:
            counts[r.status] = counts.get(r.status, 0) + 1
        changed: dict[str, int] = {}
        for r in taken:
            kind = kinds.get(r.op_id, "unknown")
            changed[kind] = changed.get(kind, 0) + 1
        seqs = [r.hub_seq for r in taken if r.hub_seq is not None]
        return cls(
            device_id=who.device_id,
            device=who.name,
            actor=actor,
            taken=tuple(r.op_id for r in taken),
            counts=counts,
            changed=changed,
            first_seq=min(seqs) if seqs else None,
            last_seq=max(seqs) if seqs else None,
            head_seq=result.head_seq,
        )


@dataclass
class FeedPage:
    entries: list[SyncEntry]
    head_seq: int  # the authority's latest number
    more: bool  # there are entries past this page
    # Protocol 5: the last number the authority looked at to make this page. A
    # caller who may not see some changes is given only the others, so the last
    # entry sent is not where reading got to: a device moves its cursor to this,
    # or it would read the same unseen run again at every sync.
    through: int | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "entries": [e.to_dict() for e in self.entries],
            "head_seq": self.head_seq,
            "more": self.more,
        }
        if self.through is not None:
            out["through"] = self.through
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FeedPage:
        entries = [SyncEntry.from_dict(e) for e in d["entries"]]
        for entry in entries:
            if entry.entity_type not in ENTITY_ORDER or entry.action not in ACTIONS:
                # Read before anything is applied, so the cursor stays put and
                # nothing is half taken: a newer server must not send this to a
                # device on an older version, so this is a bug there or here.
                raise SyncError(
                    f"The server sent a change this civex can't read "
                    f"({entry.action} {entry.entity_type}). Update civex here.",
                    retryable=False,
                )
            # A field of a type added in a newer civex: stopped the same way.
            dtype = unreadable_field_type(
                entry.entity_type, entry.new_data, entry.delta
            )
            if dtype is not None:
                raise newer_field_type(dtype)
        through = d.get("through")
        return cls(
            entries,
            int(d["head_seq"]),
            bool(d["more"]),
            int(through) if through is not None else None,
        )


@dataclass
class Hello:
    """What an authority says about itself to a device that connects."""

    protocol_version: int  # the version this device and the server agreed on
    project_id: uuid.UUID
    head_seq: int
    empty: bool  # holds none of the project's things yet
    seeded_by: str | None  # the device that put the first data in, if any
    device_name: str  # what the token the caller used is called
    # How many of each kind it holds (deleted ones too), so a device copying
    # it can say how far along it is.
    counts: dict[str, int] = field(default_factory=dict)
    # The highest number its feed no longer holds (pruned): a device that has
    # not read past it can't catch up from the feed, and copies again.
    feed_floor: int = 0
    # Every version the server speaks, the civex it runs, and its optional
    # features (`CAPABILITIES`).
    protocol_min: int = 0
    protocol_max: int = 0
    server_version: str | None = None
    capabilities: list[str] = field(default_factory=list)
    # The oldest version it still speaks but will stop accepting at its next
    # update (`PROTOCOL_RETIRING`), so a device still on it can say so.
    protocol_retiring: int | None = None
    # Protocol 5: the collections this caller may read, each `{"id", "seq"}`
    # (`seq`: the number its creation was given in the feed, 0 when it has none),
    # so a device can tell when it has been given one it does not hold and ask
    # for it (`snapshot` with `dataset`): one made after the device's cursor
    # comes in the feed, one made before it has to be asked for. None: not said
    # (an older authority or protocol), so the device assumes nothing changed.
    readable: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "protocol_version": self.protocol_version,
            "project_id": str(self.project_id),
            "head_seq": self.head_seq,
            "empty": self.empty,
            "seeded_by": self.seeded_by,
            "device_name": self.device_name,
            "counts": self.counts,
            "feed_floor": self.feed_floor,
            "protocol_min": self.protocol_min,
            "protocol_max": self.protocol_max,
            "server_version": self.server_version,
            "capabilities": self.capabilities,
            "protocol_retiring": self.protocol_retiring,
        }
        if self.readable is not None:
            out["readable"] = self.readable
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Hello:
        version = int(d["protocol_version"])
        return cls(
            protocol_version=version,
            project_id=uuid.UUID(d["project_id"]),
            head_seq=int(d["head_seq"]),
            empty=bool(d["empty"]),
            seeded_by=d.get("seeded_by"),
            device_name=d.get("device_name", ""),
            counts={k: int(v) for k, v in (d.get("counts") or {}).items()},
            feed_floor=int(d.get("feed_floor") or 0),
            # A server from before the range spoke exactly one version.
            protocol_min=int(d.get("protocol_min") or version),
            protocol_max=int(d.get("protocol_max") or version),
            server_version=d.get("server_version"),
            capabilities=[str(c) for c in d.get("capabilities") or []],
            protocol_retiring=(
                int(d["protocol_retiring"])
                if d.get("protocol_retiring") is not None
                else None
            ),
            readable=(
                [
                    {"id": str(c["id"]), "seq": int(c.get("seq") or 0)}
                    for c in d["readable"]
                ]
                if d.get("readable") is not None
                else None
            ),
        )


# What copying a project is doing, for whoever shows how far along it is.
COPYING = "copying"  # a device joining: reading the authority's things
FILLING = "filling"  # a device filling an empty authority with its own
HISTORY = "history"  # a joined device fetching the history from before it joined
FILES = "files"  # a device downloading the files its records cite
SENDING = "sending"  # a device uploading files the authority lacks


@dataclass
class SyncProgress:
    """How far a long sync step has got: `done` of `total` (None when unknown),
    and the kind of thing it is on."""

    phase: str
    done: int
    total: int | None
    kind: str | None = None
    # For moving files: bytes so far, how many in all (None when unknown),
    # how fast (`domain/rates`).
    bytes_done: int = 0
    rate: float = 0.0
    bytes_total: int | None = None
    # Sending files: how many couldn't be read here (a drive not plugged in).
    # Not counted in `done`, nor their bytes in `bytes_done`.
    owed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "done": self.done,
            "total": self.total,
            "kind": self.kind,
            "bytes_done": self.bytes_done,
            "bytes_total": self.bytes_total,
            "rate": self.rate,
            "owed": self.owed,
        }


@dataclass
class SnapshotPage:
    """A page of one kind of thing as it is now, for a device joining the
    project. Read with the authority's `head_seq` taken *first*, so anything
    that changes while a device reads is picked up from the feed afterwards.

    `next` is where the following page starts (`snapshot_cursor` of the last
    item): pages follow on from a thing, not from a count, so something removed
    meanwhile can't shift a page past something that never changed."""

    kind: str
    items: list[dict[str, Any]]
    more: bool
    head_seq: int
    next: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "items": self.items,
            "more": self.more,
            "head_seq": self.head_seq,
            "next": self.next,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SnapshotPage:
        # A field of a type this civex doesn't know stops a copy before
        # anything of the page is written, as it stops the feed.
        for item in d["items"]:
            dtype = unreadable_field_type(d["kind"], item)
            if dtype is not None:
                raise newer_field_type(dtype)
        return cls(
            d["kind"],
            list(d["items"]),
            bool(d["more"]),
            int(d["head_seq"]),
            d.get("next"),
        )


def snapshot_cursor(snapshot: dict[str, Any]) -> str:
    """Where a page that ends on `snapshot` continues: things are read in order
    of when they were made, then id, so this names a place in that order."""
    return f"{snapshot['created_at']}|{snapshot['id']}"


def parse_snapshot_cursor(cursor: str) -> tuple[str, str]:
    """(created_at, id) from a `snapshot_cursor`, or ValueError."""
    created_at, sep, id_ = cursor.rpartition("|")
    if not sep or not created_at or not id_:
        raise ValueError(f"Not a page cursor: {cursor!r}")
    return created_at, id_


def not_on_server_yet(added_by: str | None) -> tuple[str, str]:
    """(reason, fix) for a file this computer hasn't got and the server hasn't
    either: nothing here can send it. Says which computer added it when that is
    known (a fact; whether it still has the file is not known). The one wording,
    wherever it is said (opening it, downloading, an export, the files list)."""
    where = f" It was added on '{added_by}'." if added_by else ""
    return (
        f"It isn't on this computer, and the server hasn't got it.{where}",
        "The computer that has it sends it when it syncs; if none has, attach "
        "the file to the record again.",
    )


class SyncError(RuntimeError):
    """Sync could not finish. `retryable` is true for what trying again can fix
    (a network failure); a refused token or a protocol mismatch is not."""

    def __init__(
        self,
        message: str,
        retryable: bool = True,
        status: int = 400,
        detail: str = "",
        retry_after: float | None = None,
        code: str = "",
    ) -> None:
        super().__init__(message)
        # Why, for a program to act on (not_a_device, clock_skew, bad_signature,
        # too_large...), when the authority said; empty from an older server.
        self.code = code
        self.retryable = retryable
        # Seconds the server asked to wait before trying again (`Retry-After`),
        # when it said.
        self.retry_after = retry_after
        # How an authority reports it over HTTP: 401 no/invalid token, 403 a
        # token used from another device.
        self.status = status
        # The technical text behind the message (an exception's own words),
        # for whoever needs it; the message is what a person reads.
        self.detail = detail


def is_lock_contention(error: BaseException) -> bool:
    """Whether a database error only says another process is using the database
    right now (SQLite's "database is locked"/"busy", PostgreSQL's lock and
    deadlock failures): trying again soon is the fix, nothing is wrong with the
    database. Looks through the `__cause__` chain."""
    seen = 0
    while error is not None and seen < 8:
        text = str(getattr(error, "orig", None) or error).lower()
        if type(error).__module__.split(".")[0] in ("sqlalchemy", "sqlite3", "psycopg"):
            if (
                "database is locked" in text
                or "database table is locked" in text
                or "database is busy" in text
                or "could not obtain lock" in text
                or "deadlock detected" in text
                or "lock timeout" in text
            ):
                return True
        error = error.__cause__  # type: ignore[assignment]
        seen += 1
    return False


LOCK_CONTENTION_MESSAGE = (
    "Another civex process is using this project right now, so syncing waited. "
    "It will try again shortly."
)


def plain_failure(error: Exception) -> SyncError:
    """Any failure while syncing or connecting as a `SyncError` a person can
    read: one sentence saying what to do, with the technical text kept as its
    `detail`. A `SyncError` is already that. The one place a raw error (a
    database's SQL, a traceback's last line) becomes words."""
    if isinstance(error, SyncError):
        return error
    technical = f"{type(error).__name__}: {error}"
    if is_lock_contention(error):
        return SyncError(LOCK_CONTENTION_MESSAGE, retryable=True, detail=technical)
    if type(error).__module__.split(".")[0] == "sqlalchemy":
        return SyncError(
            "This computer's database isn't in the shape this civex expects, so "
            "syncing stopped. Run `civex doctor` to check it.",
            retryable=False,
            detail=technical,
        )
    return SyncError(
        "Syncing stopped because of an unexpected problem on this computer. "
        "It is in the log; trying again may help.",
        detail=technical,
    )


@dataclass
class SyncMetaDTO:
    project_id: uuid.UUID
    head_seq: int  # authority: the last number handed out
    cursor: int  # device: the last of the authority's numbers applied here
    seeded_by: str | None
    last_synced_at: str | None
    last_error: str | None
    last_error_at: str | None
    # Authority: the highest number its feed no longer holds (pruned).
    feed_floor: int = 0
    # Device: history up to this number (where it joined) is still to be
    # fetched from the authority; None when it holds all of it.
    history_from: int | None = None


# -- Who a device is ---------------------------------------------------------
#
# An admin invites a device by name; the invite works once and expires. The
# device makes a key pair, keeps the private half, and joins with the invite and
# its public key (`Joined`: the authority's key, which the device keeps). From
# then on it signs in by signing `session_request` (no shared secret ever
# travels again) and gets a token for `SESSION_SECONDS`; the authority signs
# `session_answer`, so a device knows it is still talking to the server it
# joined.

# What every invite starts with, so a scanner (gitleaks, GitHub's secret
# scanning) recognises one pasted where it shouldn't be.
INVITE_PREFIX = "civex_inv_"
INVITE_HOURS = 24
# A request to join by approval lasts this long, and the device asks every
# `LOGIN_POLL_SECONDS` whether it was approved.
LOGIN_MINUTES = 15
LOGIN_POLL_SECONDS = 3
SESSION_SECONDS = 15 * 60
# How far a device's clock may be from the authority's when signing in.
CLOCK_SKEW_SECONDS = 5 * 60


def session_request(authority_key: str, device_id: str, at: int) -> bytes:
    """What a device signs to sign in: to this authority, as this device, now."""
    return f"civex-session\n{authority_key}\n{device_id}\n{at}".encode()


def session_answer(device_signature: str) -> bytes:
    """What the authority signs back: its answer to that very request."""
    return f"civex-session-ok\n{device_signature}".encode()


@dataclass(frozen=True)
class DeviceCredentials:
    """What a device holds to reach an authority: its id, its private key, and
    the authority's public key once it has joined."""

    device_id: str
    private_key: str
    authority_key: str | None = None


@dataclass(frozen=True)
class LoginStarted:
    """The authority's answer to a device asking to join without an invite:
    the short `user_code` a person reads off the device and approves on the
    authority (or at `verify_url`, when the host has a page for it), and the
    secret `device_code` the device polls with until then."""

    user_code: str
    device_code: str
    expires_at: int  # unix seconds
    interval: int  # seconds between polls
    verify_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_code": self.user_code,
            "device_code": self.device_code,
            "expires_at": self.expires_at,
            "interval": self.interval,
            "verify_url": self.verify_url,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LoginStarted:
        return cls(
            user_code=str(d["user_code"]),
            device_code=str(d["device_code"]),
            expires_at=int(d["expires_at"]),
            interval=max(1, int(d.get("interval") or LOGIN_POLL_SECONDS)),
            verify_url=d.get("verify_url") or None,
        )


@dataclass
class LoginRequestDTO:
    """A device waiting to be let in (the authority's side of `LoginStarted`)."""

    id: uuid.UUID
    user_code: str
    device_id: str
    public_key: str
    created_at: str
    expires_at: str
    name: str | None  # given when approved
    approved_at: str | None
    denied_at: str | None


@dataclass(frozen=True)
class Joined:
    """The authority's answer to a device joining with an invite."""

    project_id: uuid.UUID
    authority_key: str
    device_name: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": str(self.project_id),
            "authority_key": self.authority_key,
            "device_name": self.device_name,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Joined:
        return cls(
            uuid.UUID(d["project_id"]), str(d["authority_key"]), str(d["device_name"])
        )


@dataclass(frozen=True)
class SessionGrant:
    """A signed-in device's token, until when (unix seconds), and the
    authority's signature over the request it answers."""

    token: str
    expires_at: int
    signature: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "expires_at": self.expires_at,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SessionGrant:
        return cls(str(d["token"]), int(d["expires_at"]), str(d["signature"]))


@dataclass
class SyncDeviceDTO:
    id: uuid.UUID
    name: str
    device_id: str
    public_key: str
    created_at: str
    last_seen_at: str | None
    revoked_at: str | None
    may_publish: bool = False  # to the library (`domain/library.py`)


@dataclass
class SyncInviteDTO:
    id: uuid.UUID
    name: str  # the device it is for
    created_at: str
    expires_at: str
    used_at: str | None
    revoked_at: str | None


@dataclass(frozen=True)
class Principal:
    """Who is calling an authority, as its `Authenticator` proved it. Here a
    device: `name` is what it was invited as (in the log, `hello` and each
    entry's `device`). An authenticator that proves a person sets `person`,
    which then wins over the author a device claims."""

    name: str
    token_id: uuid.UUID
    device_id: str
    person: str | None = None


class Authenticator(Protocol):
    """Turns the token a caller presents into a `Principal`, or raises
    `SyncError` (401: not valid, expired, or its device revoked)."""

    def authenticate(self, token: str) -> Principal: ...


class SyncPolicy(Protocol):
    """What a principal may change. None lets the change through; a reason
    refuses it, as any change that breaks a rule is refused."""

    def refuses(self, who: Principal, entry: SyncEntry) -> str | None: ...


@dataclass
class SyncConflictDTO:
    id: uuid.UUID
    kind: str  # conflict | rejected | edit_vs_delete | unfit
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
    # For a refusal: why (`REFUSAL_PERMISSION`, ...) when the authority said, and
    # how often it has been sent again by itself since.
    code: str | None = None
    retries: int = 0
    retried_at: str | None = None
    # What the value was before either side changed it, and who wrote the one that
    # stayed, and when.
    base: Any = None
    theirs_actor: str | None = None
    theirs_device: str | None = None
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
    # For a refused record that sits under deleted records here: those records
    # ({id, schema_name, name}, topmost first), which `restore_above` brings
    # back before sending it again.
    sits_under: list[dict[str, Any]] = dataclasses.field(default_factory=list)

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
            "theirs_device": self.theirs_device,
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
            "sits_under": self.sits_under,
        }


class UploadSource(Protocol):
    """What a file to upload is read from: an open file, or one that counts
    the bytes read from it."""

    def read(self, size: int = -1, /) -> bytes: ...
    def seek(self, offset: int, whence: int = 0, /) -> int: ...
    def tell(self) -> int: ...


class SyncTransport(Protocol):
    """How a device talks to an authority. HTTP in use; tests supply one that
    calls an authority in the same process (and ones that fail on purpose).
    Signing in is the transport's own business: every call but `join` is made
    as the device its credentials name."""

    def join(self, invite: str) -> Joined: ...
    def request_login(self) -> LoginStarted:
        """Ask to join without an invite: a code for a person to approve."""
        ...

    def poll_login(self, device_code: str) -> Joined | None:
        """Whether the request was approved yet: `Joined` once it was, None
        while it waits; SyncError (410) once it was denied or expired."""
        ...

    def hello(self) -> Hello: ...
    def push(self, entries: list[SyncEntry]) -> PushResult: ...
    def feed(self, after: int, limit: int) -> FeedPage: ...
    def snapshot(
        self,
        kind: str,
        after: str | None,
        limit: int,
        dataset: str | None = None,
        left_after: int | None = None,
    ) -> SnapshotPage: ...
    def missing_files(self, shas: list[str]) -> list[str]: ...
    def upload_file(self, sha256: str, source: UploadSource, size: int) -> None:
        """Send `size` bytes read from `source` (from where it is now; read
        again from the start if the call has to be repeated)."""
        ...

    def file_chunks(self, sha256: str) -> Iterator[bytes]: ...
    # The library (`domain/library.py`): items as `LibraryItemDTO.to_dict`.
    def library(self) -> list[dict[str, Any]]: ...
    def library_item(
        self, kind: str, name: str, version: int | None = None
    ) -> dict[str, Any]: ...
    # The answer is `PublishResult.to_dict`: the versions stored, and warnings.
    def publish(self, items: list[dict[str, Any]]) -> dict[str, Any]: ...
    def unpublish(
        self, kind: str, name: str, version: int | None = None, force: bool = False
    ) -> None: ...


# A push carries at most this many serialized bytes (an action over it goes
# alone), so the size of a request doesn't depend on how wide the records are.
PUSH_BUDGET_BYTES = 2 * 1024 * 1024


def group_by_op(entries: list[SyncEntry]) -> list[SyncEntry]:
    """`entries` with each action's entries (sharing an `op`) together: actions
    in the order they first appear, entries in the order given. An entry with no
    `op` is an action of its own."""
    groups: dict[Any, list[SyncEntry]] = {}
    for at, entry in enumerate(entries):
        groups.setdefault(entry.op or at, []).append(entry)
    return [e for g in groups.values() for e in g]


def batch_by_budget(
    entries: list[SyncEntry],
    max_entries: int,
    max_bytes: int = PUSH_BUDGET_BYTES,
    size_of: Callable[[SyncEntry], int] | None = None,
) -> list[SyncEntry]:
    """The leading entries to send in one push: at most `max_entries` and about
    `max_bytes` serialized, but never part of an action (entries sharing an
    `op` are taken together or not at all; an action over the budget goes
    alone, and the first action is always taken). Entries with no `op` are each
    an action of their own."""
    size = size_of or (lambda e: len(json.dumps(e.to_dict())))
    entries = group_by_op(entries)  # an action's entries may have been apart
    taken: list[SyncEntry] = []
    used = 0
    i = 0
    while i < len(entries):
        j = i + 1
        if entries[i].op is not None:
            while j < len(entries) and entries[j].op == entries[i].op:
                j += 1
        action = entries[i:j]
        cost = sum(size(e) for e in action)
        if taken and (
            len(taken) + len(action) > max_entries or used + cost > max_bytes
        ):
            break
        taken += action
        used += cost
        i = j
    return taken
