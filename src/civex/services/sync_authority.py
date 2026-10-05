"""The authority: the one copy of a project that settles what is true.

Devices send the changes they made; the authority checks each against what it
holds, merges it (see `domain/merge`), numbers what it accepts and serves
everyone's changes back in that order. Nothing a device says about *when* or
*who* is trusted: the order is the authority's, and the author of an accepted
change is the device whose token sent it.

Sending a change twice is harmless: each is recorded by its id, and a repeat is
answered with the first answer. A change that cannot be taken yet (a file has
not arrived) is neither recorded nor refused, and is sent again later.
"""

from __future__ import annotations

import logging

import hashlib
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from civex.domain import hlc
from civex.domain.exceptions import ValidationError
from civex.domain.merge import LIFECYCLE_KEYS, DERIVED_KEYS, merge
from civex.domain.sync import (
    APPLIED,
    CONFLICT,
    DEFERRED,
    ENTITY_ORDER,
    MERGED,
    PROTOCOL_VERSION,
    REJECTED,
    FeedPage,
    Hello,
    OpResult,
    PushResult,
    SnapshotPage,
    SyncDeviceDTO,
    SyncEntry,
    SyncError,
)
from civex.repositories.protocols import FileObjectStore, SyncRepository
from civex.services.sync_applier import SyncApplier, stamp_of

FEED_MAX = 500
SNAPSHOT_MAX = 500
PUSH_MAX = 500


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


log = logging.getLogger(__name__)


class SyncAuthorityService:
    def __init__(
        self,
        repo: SyncRepository,
        applier: SyncApplier,
        files: FileObjectStore,
    ) -> None:
        self._repo = repo
        self._applier = applier
        self._files = files

    # ------------------------------------------------------------------
    # Who may sync
    # ------------------------------------------------------------------

    def add_device(self, name: str) -> tuple[SyncDeviceDTO, str]:
        """Allow a device, returning the token it must present. The token is
        shown once: only its hash is kept."""
        name = name.strip()
        if not name:
            raise ValidationError("A device needs a name")
        if self._repo.device_named(name) is not None:
            raise ValidationError(f"A device called '{name}' already exists")
        token = secrets.token_urlsafe(32)
        return self._repo.add_device(name, hash_token(token)), token

    def list_devices(self) -> list[SyncDeviceDTO]:
        return self._repo.list_devices()

    def revoke_device(self, name: str) -> bool:
        return self._repo.revoke_device(name)

    def authenticate(self, token: str, device_id: str | None) -> SyncDeviceDTO:
        """The device a token belongs to. It is bound to the first device id it
        is used with, and refused from any other afterwards."""
        device = self._repo.device_by_token_hash(hash_token(token))
        if device is None:
            raise SyncError(
                "That token is not valid, or has been revoked",
                retryable=False,
                status=401,
            )
        if device_id:
            try:
                uuid.UUID(device_id)
            except ValueError:
                raise SyncError("The device id is not valid", retryable=False)
            if device.device_id and device.device_id != device_id:
                raise SyncError(
                    "That token belongs to another device",
                    retryable=False,
                    status=403,
                )
            if not device.device_id:
                self._repo.bind_device(device.id, device_id)
        self._repo.touch_device(device.id)
        return device

    # ------------------------------------------------------------------
    # Joining
    # ------------------------------------------------------------------

    def hello(self, device: SyncDeviceDTO) -> Hello:
        meta = self._repo.meta()
        return Hello(
            protocol_version=PROTOCOL_VERSION,
            project_id=meta.project_id,
            head_seq=self._head(),
            empty=self._repo.entity_count() == 0,
            seeded_by=meta.seeded_by,
            device_name=device.name,
        )

    def snapshot(self, kind: str, offset: int, limit: int) -> SnapshotPage:
        """A page of one kind as it is now, for a device joining. `head_seq` is
        read first: what changes while the device reads is in the feed past it."""
        if kind not in ENTITY_ORDER:
            raise ValidationError(f"Unknown kind '{kind}'")
        head = self._head()
        limit = max(1, min(limit, SNAPSHOT_MAX))
        items = self._repo.snapshots_page(kind, offset, limit + 1)
        return SnapshotPage(kind, items[:limit], len(items) > limit, head)

    def _head(self) -> int:
        """The latest number, after numbering anything changed on this instance
        itself (its own edits join the feed in the order they were made)."""
        self._repo.sequence_local_entries()
        return self._repo.head_seq()

    # ------------------------------------------------------------------
    # The feed
    # ------------------------------------------------------------------

    def feed(self, after: int, limit: int = 200) -> FeedPage:
        head = self._head()
        entries, more = self._repo.entries_after(after, max(1, min(limit, FEED_MAX)))
        return FeedPage(entries, head, more)

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    def missing_files(self, shas: list[str]) -> list[str]:
        return [s for s in dict.fromkeys(shas) if not self._files.exists(s)]

    # ------------------------------------------------------------------
    # Accepting changes
    # ------------------------------------------------------------------

    def push(
        self, device: SyncDeviceDTO, device_id: str | None, entries: list[SyncEntry]
    ) -> PushResult:
        """Settle each change, in the order sent. Stops at the first that has
        to wait (later ones may depend on it); those are simply not answered."""
        self._head()  # number this instance's own changes first
        results: list[OpResult] = []
        for entry in entries[:PUSH_MAX]:
            result = self._settle(device, device_id, entry)
            results.append(result)
            if result.status == DEFERRED:
                break
        self._log_push(device, entries, results)
        return PushResult(results, self._repo.head_seq())

    @staticmethod
    def _log_push(
        device: SyncDeviceDTO, entries: list[SyncEntry], results: list[OpResult]
    ) -> None:
        """One line per push saying what became of the changes, and one per
        change that was not simply taken, naming the thing."""
        counts: dict[str, int] = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
        summary = ", ".join(f"{n} {s}" for s, n in sorted(counts.items())) or "nothing"
        log.info("sync push from %s: %d sent, %s", device.name, len(entries), summary)
        by_id = {e.id: e for e in entries}
        for r in results:
            if r.status in ("conflict", "rejected", "deferred", "merged"):
                e = by_id.get(r.op_id)
                what = f"{e.entity_type} {e.entity_id}" if e else str(r.op_id)
                log.warning(
                    "sync push from %s: %s %s%s",
                    device.name,
                    what,
                    r.status,
                    f" ({r.message})" if r.message else "",
                )

    def _settle(
        self, device: SyncDeviceDTO, device_id: str | None, entry: SyncEntry
    ) -> OpResult:
        prior = self._repo.get_op(entry.id)
        if prior is not None:
            return prior  # sent before: the same answer, nothing done again
        problem = _unacceptable(entry)
        if problem:
            return self._refuse(device, device_id, entry, problem)
        try:
            with self._repo.savepoint():
                result = self._take(device, device_id, entry)
        except ValidationError as e:
            return self._refuse(device, device_id, entry, str(e))
        self._repo.save_op(entry, result, device_id, device.name)
        for conflict in result.conflicts:
            self._repo.add_conflict(
                kind=conflict.get("kind", "conflict"),
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
                field=conflict.get("field"),
                yours=conflict.get("yours"),
                theirs=conflict.get("theirs"),
                op_id=entry.id,
                device_name=device.name,
                message=conflict.get("message"),
            )
        return result

    def _refuse(
        self, device: SyncDeviceDTO, device_id: str | None, entry: SyncEntry, why: str
    ) -> OpResult:
        result = OpResult(entry.id, REJECTED, why)
        self._repo.save_op(entry, result, device_id, device.name)
        self._repo.add_conflict(
            kind="rejected",
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            field=None,
            yours=entry.new_data,
            theirs=None,
            op_id=entry.id,
            device_name=device.name,
            message=why,
        )
        return result

    def _take(
        self, device: SyncDeviceDTO, device_id: str | None, entry: SyncEntry
    ) -> OpResult:
        """Merge the change into what is held, write it, and record it."""
        kind, eid = entry.entity_type, entry.entity_id
        head = self._applier.head(kind, eid)
        conflicts: list[dict[str, Any]] = []
        final: dict[str, Any] | None = None  # the state the thing ends in, if it exists
        message: str | None = None

        if entry.action in ("create", "update", "restore"):
            incoming = entry.new_data or {}
            if head is None:
                if entry.action == "update":
                    raise ValidationError("It no longer exists on the server")
                final = dict(incoming)
            else:
                merged = merge(
                    entry.old_data if entry.action != "create" else None, head, incoming
                )
                final = merged.state
                final["deleted_at"] = (
                    None
                    if incoming.get("deleted_at") is None
                    else head.get("deleted_at")
                )
                if merged.changed and incoming.get("updated_at"):
                    # Something of the edit went in, so the thing was updated
                    # when the edit was made. An edit that all clashed changes
                    # nothing, and the thing keeps its own date.
                    final["updated_at"] = incoming["updated_at"]
                conflicts = [
                    {
                        "kind": "conflict",
                        "field": c.field,
                        "yours": c.incoming,
                        "theirs": c.head,
                    }
                    for c in merged.conflicts
                ]
                if head.get("deleted_at") and entry.action != "restore":
                    conflicts.append(
                        {
                            "kind": "edit_vs_delete",
                            "field": None,
                            "yours": None,
                            "theirs": None,
                            "message": "It was deleted on the server, and edited here: it has been kept",
                        }
                    )
            self._applier.apply_state(kind, eid, final)
        elif entry.action == "delete":
            if head is not None and head.get("deleted_at"):
                # Already deleted (another device got there first). Both are
                # deleted, but with their own stamps: settle on the authority's.
                if head["deleted_at"] != stamp_of(entry).isoformat():
                    final = head
            elif head is not None:
                if _edited_since(entry.old_data, head):
                    conflicts.append(
                        {
                            "kind": "edit_vs_delete",
                            "field": None,
                            "yours": None,
                            "theirs": None,
                            "message": "It was edited on the server after you last saw it, so it was not deleted",
                        }
                    )
                    final = head
                else:
                    self._applier.apply_delete(kind, eid, stamp_of(entry))
        elif entry.action == "purge":
            if head is not None:
                self._applier.apply_purge(kind, eid)
        else:
            raise ValidationError(f"Unknown action '{entry.action}'")

        self._seed(device_id)
        seq = self._write_entries(device, device_id, entry, head, final, conflicts)
        status = self._status(entry, final, conflicts)
        if conflicts and any(c["kind"] == "edit_vs_delete" for c in conflicts):
            message = next(
                c.get("message") for c in conflicts if c["kind"] == "edit_vs_delete"
            )
        return OpResult(entry.id, status, message, conflicts, seq)

    def _seed(self, device_id: str | None) -> None:
        """The first data an empty authority takes marks who put it there: the
        same device may resume an interrupted first push, no other may join."""
        meta = self._repo.meta()
        if device_id and meta.seeded_by is None:
            self._repo.set_seeded_by(device_id)

    def _status(
        self,
        entry: SyncEntry,
        final: dict[str, Any] | None,
        conflicts: list[dict[str, Any]],
    ) -> str:
        if conflicts:
            return CONFLICT
        if final is not None and entry.action in ("create", "update", "restore"):
            if _comparable(final) != _comparable(entry.new_data or {}):
                return MERGED
        return APPLIED

    def _write_entries(
        self,
        device: SyncDeviceDTO,
        device_id: str | None,
        entry: SyncEntry,
        head: dict[str, Any] | None,
        final: dict[str, Any] | None,
        conflicts: list[dict[str, Any]],
    ) -> int:
        """Record the change as it was made (numbered), and, when what the
        authority settled on is not what was sent, a second entry carrying the
        settled state, so every device ends where the authority did."""
        seq = self._repo.next_hub_seq()
        sent = SyncEntry(
            id=entry.id,
            action=entry.action,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            old_data=entry.old_data,
            new_data=entry.new_data,
            timestamp=entry.timestamp,
            actor=device.name,  # who sent it is who the token says, not what was claimed
            device_id=device_id,
            hlc=entry.hlc,
            batch=entry.batch,
        )
        self._repo.insert_entry(sent, hub_seq=seq)
        if entry.action in ("create", "update", "restore", "delete") and (
            conflicts or _differs(entry, final)
        ):
            settled = self._applier.head(entry.entity_type, entry.entity_id)
            if settled is not None:
                self._repo.insert_entry(
                    SyncEntry(
                        id=uuid.uuid4(),
                        action="update",
                        entity_type=entry.entity_type,
                        entity_id=entry.entity_id,
                        old_data=head,
                        new_data=settled,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        actor="sync",
                        hlc=hlc.tick(self._repo.latest_hlc(), _now_ms()),
                    ),
                    hub_seq=self._repo.next_hub_seq(),
                )
        return seq


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _comparable(state: dict[str, Any]) -> dict[str, Any]:
    skip = LIFECYCLE_KEYS | DERIVED_KEYS
    return {k: v for k, v in state.items() if k not in skip}


def _edited_since(base: dict[str, Any] | None, head: dict[str, Any]) -> bool:
    """Whether head differs from what an edit started from."""
    return _comparable(base or {}) != _comparable(head)


def _differs(entry: SyncEntry, final: dict[str, Any] | None) -> bool:
    if entry.action == "delete":
        return final is not None  # the delete was not applied
    if final is None:
        return False
    return _comparable(final) != _comparable(entry.new_data or {})


_KNOWN = ENTITY_ORDER


def _unacceptable(entry: SyncEntry) -> str | None:
    if entry.entity_type not in _KNOWN:
        return f"Unknown kind '{entry.entity_type}'"
    if entry.action in ("create", "update", "restore"):
        if not entry.new_data or str(entry.new_data.get("id")) != str(entry.entity_id):
            return "The change does not say what the thing became"
    return None
