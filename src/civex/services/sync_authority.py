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
from civex.domain.audit_diff import AFTER, BEFORE, apply_delta, identity
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
    problem_with,
    snapshot_cursor,
)
from civex.repositories.protocols import FileObjectStore, SyncRepository
from civex.services.cascades import States, changed_records, record_states
from civex.services.project_rules import ProjectRules
from civex.services.record_service import RecordService
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
        records: RecordService,
        rules: ProjectRules,
    ) -> None:
        self._repo = repo
        self._applier = applier
        self._files = files
        # What a project must still be after a change, asked of what it touched
        # (a change from elsewhere was checked against what that device held).
        self._rules = rules
        # The things the action being settled has entries for itself.
        self._covered: set[tuple[str, uuid.UUID]] = set()
        # The rules a record must satisfy are the record service's, not copied
        # here: a change from a device is held to what a person's edit is.
        self._records = records

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
        counts = self._repo.entity_counts()
        return Hello(
            protocol_version=PROTOCOL_VERSION,
            project_id=meta.project_id,
            head_seq=self._head(),
            empty=sum(counts.values()) == 0,
            seeded_by=meta.seeded_by,
            device_name=device.name,
            counts=counts,
            feed_floor=meta.feed_floor,
        )

    def snapshot(self, kind: str, after: str | None, limit: int) -> SnapshotPage:
        """A page of one kind as it is now, for a device joining, continuing
        after the cursor `after` (None: the first page). `head_seq` is read
        first: what changes while the device reads is in the feed past it."""
        if kind not in ENTITY_ORDER:
            raise ValidationError(f"Unknown kind '{kind}'")
        head = self._head()
        limit = max(1, min(limit, SNAPSHOT_MAX))
        try:
            items = self._repo.snapshots_page(kind, after, limit + 1)
        except ValueError as e:
            raise ValidationError(f"Not a page cursor: {after!r}") from e
        page = items[:limit]
        more = len(items) > limit
        return SnapshotPage(
            kind, page, more, head, snapshot_cursor(page[-1]) if more else None
        )

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
        to wait (later ones may depend on it); those are simply not answered.

        One push at a time: each change is merged with what is held and the
        whole thing written back, so two pushes reading the same thing at once
        would each overwrite the other. The feed's counter is taken first and
        held until the answer is saved, which makes every other push wait."""
        self._repo.lock_feed()
        self._head()  # number this instance's own changes first
        results: list[OpResult] = []
        for action in _actions(_at_most(entries, PUSH_MAX)):
            settled = (
                [self._settle(device, device_id, action[0])]
                if len(action) == 1
                else self._settle_action(device, device_id, action)
            )
            results += settled
            if any(r.status == DEFERRED for r in settled):
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
        self._covered = {(entry.entity_type, entry.entity_id)}
        problem = problem_with(entry)
        if problem:
            return self._refuse(device, device_id, entry, problem)
        try:
            with self._repo.savepoint():
                result = self._take(device, device_id, entry)
                self._rules.check(_changed([entry]))
        except ValidationError as e:
            if entry.entity_type != "record" and self._applier.head(
                entry.entity_type, entry.entity_id
            ):
                return self._put_back(device, device_id, entry, str(e))
            return self._refuse(
                device, device_id, entry, str(e), getattr(e, "path", None)
            )
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            # A value inside the snapshots that can't be read (an id or a date
            # that isn't one). Refused by itself, so it can't hold up the rest
            # of the push or be sent again for ever.
            return self._refuse(device, device_id, entry, f"A value is not valid: {e}")
        self._repo.save_op(entry, result, device_id, device.name)
        return result

    def _settle_action(
        self, device: SyncDeviceDTO, device_id: str | None, action: list[SyncEntry]
    ) -> list[OpResult]:
        """Settle the entries one action wrote (a field renamed with the
        templates it rewrote, a record deleted with everything beneath it) as
        one: all go in, or none does. Each is merged as it would be alone, then
        the rules are asked once about all it touched (in between, a template
        may briefly name the field's old name). An action that can't go in
        whole is answered as a whole:

        - a delete that met an edit made here keeps every thing it would have
          deleted, as a single record's delete does, and says so; the device is
          sent what is kept, so it ends where this copy is;
        - anything else is refused, every entry of it. What it would have
          changed that is here is sent back as it is here, so the device ends
          where this copy is rather than half way through the action; the
          person is told what did not go in and why, and does it again on what
          is there now. Only what isn't here at all (made by the action) stays
          on the device for review."""
        priors = [self._repo.get_op(e.id) for e in action]
        if all(p is not None for p in priors):
            return [p for p in priors if p is not None]  # sent before
        self._covered = {(e.entity_type, e.entity_id) for e in action}
        for entry in action:
            if problem := problem_with(entry):
                return self._refuse_action(device, device_id, action, problem)
        try:
            with self._repo.savepoint():
                results = [self._take(device, device_id, e) for e in action]
                failed = [r for r in results if r.status not in (APPLIED, MERGED)]
                if failed:
                    raise _NotWhole(results)
                self._rules.check(_changed(action))
        except _NotWhole as e:
            if all(_kept_from_delete(e.results, action)):
                return self._keep_instead_of_delete(
                    device, device_id, action, e.results
                )
            why = next((r.message for r in e.results if r.message), None)
            return self._refuse_action(
                device,
                device_id,
                action,
                why or "Something it changes was changed on the server meanwhile",
            )
        except ValidationError as e:
            return self._refuse_action(device, device_id, action, str(e))
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            return self._refuse_action(
                device, device_id, action, f"A value is not valid: {e}"
            )
        for entry, result in zip(action, results):
            self._repo.save_op(entry, result, device_id, device.name)
        return results

    def _refuse_action(
        self,
        device: SyncDeviceDTO,
        device_id: str | None,
        action: list[SyncEntry],
        why: str,
    ) -> list[OpResult]:
        message = f"Part of one change that could not go in whole: {why}"
        return [
            self._put_back(device, device_id, entry, message)
            if self._applier.head(entry.entity_type, entry.entity_id) is not None
            else self._refuse(device, device_id, entry, message)
            for entry in action
        ]

    def _put_back(
        self, device: SyncDeviceDTO, device_id: str | None, entry: SyncEntry, why: str
    ) -> OpResult:
        """Answer that a change was not taken, and send what is here instead,
        so the device that made it ends where this copy is. For the project's
        structure (and the parts of an action), where a change left in place on
        one device would sit under everything else that arrives there."""
        head = self._applier.head(entry.entity_type, entry.entity_id)
        conflicts = [
            self._clash(
                entry.entity_type,
                entry.entity_id,
                None,
                None,
                None,
                None,
                "not_taken",
                why,
            )
        ]
        seq = self._write_entries(device, device_id, entry, head, head, conflicts, None)
        result = OpResult(entry.id, CONFLICT, why, conflicts, seq)
        self._repo.save_op(entry, result, device_id, device.name)
        return result

    def _keep_instead_of_delete(
        self,
        device: SyncDeviceDTO,
        device_id: str | None,
        action: list[SyncEntry],
        tried: list[OpResult],
    ) -> list[OpResult]:
        """A delete of a record tree, part of which was edited (or added to)
        here since: the whole tree stays (half a tree would leave records under
        a deleted parent). Each entry is answered as an edit-vs-delete, with the
        state kept sent after it, as for a single record, saying why: its own
        reason, or the reason the rest of its tree was kept."""
        reasons = {
            r.op_id: c.get("message")
            for r in tried
            for c in r.conflicts
            if c.get("kind") == "edit_vs_delete" and c.get("message")
        }
        first: str = next(
            (m for m in reasons.values() if m), "It was edited on the server"
        )
        results: list[OpResult] = []
        for entry in action:
            message = reasons.get(entry.id) or (
                "It was to be deleted with the records above it, which were "
                f"kept: {first[0].lower()}{first[1:]}"
            )
            head = self._applier.head(entry.entity_type, entry.entity_id)
            conflicts = [
                self._clash(
                    entry.entity_type,
                    entry.entity_id,
                    None,
                    None,
                    None,
                    None,
                    "edit_vs_delete",
                    message,
                )
            ]
            seq = self._write_entries(
                device, device_id, entry, head, head, conflicts, None
            )
            result = OpResult(entry.id, CONFLICT, message, conflicts, seq)
            self._repo.save_op(entry, result, device_id, device.name)
            results.append(result)
        return results

    def _refuse(
        self,
        device: SyncDeviceDTO,
        device_id: str | None,
        entry: SyncEntry,
        why: str,
        field: str | None = None,
    ) -> OpResult:
        """Answer that a change can never be taken. The answer is remembered, so
        a repeat gets it again; the device that sent it keeps what it made and
        shows it for review (conflicts are held by the device whose change did
        not go in, not here). `field` is the value it was refused for, when it
        was one (`data.<field id>`), so the device can show that field to fix."""
        result = OpResult(
            entry.id,
            REJECTED,
            why,
            [{"kind": "rejected", "field": field}] if field else [],
        )
        self._repo.save_op(entry, result, device_id, device.name)
        return result

    def _take(
        self, device: SyncDeviceDTO, device_id: str | None, entry: SyncEntry
    ) -> OpResult:
        """Merge the change into what is held, write it, and record it."""
        kind, eid = entry.entity_type, entry.entity_id
        head = self._applier.head(kind, eid)
        cascade = self._cascade_before(entry, head)
        conflicts: list[dict[str, Any]] = []
        final: dict[str, Any] | None = None  # the state the thing ends in, if it exists
        incoming: dict[str, Any] | None = None  # what the change made, as a whole
        message: str | None = None

        if entry.action in ("create", "update", "restore"):
            if head is None:
                if entry.action == "update" or entry.delta is not None:
                    raise ValidationError(
                        "It is not on the server (deleted for good there, or "
                        "never taken)"
                    )
                incoming = entry.new_data or {}
                final = dict(incoming)
            else:
                base, incoming = _sides(entry, head)
                merged = merge(
                    base if entry.action != "create" else None, head, incoming
                )
                final = merged.state
                final["deleted_at"] = (
                    None
                    if incoming.get("deleted_at") is None
                    else head.get("deleted_at")
                )
                if (merged.changed or not merged.conflicts) and incoming.get(
                    "updated_at"
                ):
                    # The edit went in (even one whose values were all here
                    # already), so the thing was updated when the edit was
                    # made: every copy applies the edit's date with it, so this
                    # one must hold it too. An edit that all clashed changes
                    # nothing, keeps the thing's own date, and the state settled
                    # on after it puts every copy there.
                    final["updated_at"] = incoming["updated_at"]
                conflicts = [
                    self._clash(kind, eid, c.field, c.incoming, c.head, c.base)
                    for c in merged.conflicts
                ]
                if head.get("deleted_at") and entry.action != "restore":
                    conflicts.append(
                        self._clash(
                            kind,
                            eid,
                            None,
                            None,
                            None,
                            None,
                            "edit_vs_delete",
                            "It was deleted on the server, and edited here: it has been kept",
                        )
                    )
            if kind == "record":
                self._records.check_incoming(final, head)
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
                        self._clash(
                            kind,
                            eid,
                            None,
                            None,
                            None,
                            None,
                            "edit_vs_delete",
                            "It was edited on the server after you last saw it, so it was not deleted",
                        )
                    )
                    final = head
                elif kind == "record" and self._added_beneath(eid):
                    # Something was put under it here that the deleting device
                    # didn't know of: like an edit that meets a delete, it is
                    # kept, and so is the record (a child can't stay live
                    # under a deleted parent).
                    conflicts.append(
                        self._clash(
                            kind,
                            eid,
                            None,
                            None,
                            None,
                            None,
                            "edit_vs_delete",
                            "Something was added beneath it on the server after "
                            "you last saw it, so it was not deleted",
                        )
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
        seq = self._write_entries(
            device, device_id, entry, head, final, conflicts, incoming
        )
        if cascade is not None:
            self._write_cascade(entry, cascade)
        status = self._status(entry, final, conflicts, incoming)
        if conflicts and any(c["kind"] == "edit_vs_delete" for c in conflicts):
            message = next(
                c.get("message") for c in conflicts if c["kind"] == "edit_vs_delete"
            )
        return OpResult(entry.id, status, message, conflicts, seq)

    def _added_beneath(self, record_id: uuid.UUID) -> bool:
        """Whether a live record sits under this one that the action being
        settled doesn't delete too: one the deleting device never saw."""
        levels = self._records.records_repo.subtree_levels([record_id], deleted=False)
        beneath = {rid for level in levels[1:] for rid in level}
        return any(("record", rid) not in self._covered for rid in beneath)

    def _cascade_before(
        self, entry: SyncEntry, head: dict[str, Any] | None
    ) -> States | None:
        """Where a schema's or collection's records stand before a change that
        can delete or restore them (it, and so them, deleted or brought back),
        to say afterwards which it changed. None when it can't."""
        if entry.entity_type not in ("schema", "dataset") or head is None:
            return None
        if entry.action not in ("delete", "restore") and not head.get("deleted_at"):
            return None  # an edit to something live deletes nothing
        scope = _scope(entry)
        return record_states(self._records.records_repo, **scope)

    def _write_cascade(self, entry: SyncEntry, before: States) -> None:
        """An entry for each record the change deleted or brought back here,
        numbered after it: the records changed, so the feed says so, and every
        copy ends with them as they are here (not as its own cascade, from what
        it held, would have left them). Records the action itself already has
        an entry for (the device's own cascade, sent with it) are left to
        those."""
        covered = self._covered
        for rid, was, became in changed_records(
            self._records.records_repo, before, **_scope(entry)
        ):
            if ("record", rid) in covered:
                continue
            snap = self._applier.head("record", rid)
            if snap is None:
                continue
            if became is not None:
                step = SyncEntry(
                    id=uuid.uuid4(),
                    action="delete",
                    entity_type="record",
                    entity_id=rid,
                    old_data=identity({**snap, "deleted_at": None}),
                    new_data=None,
                    timestamp=became.isoformat(),
                    actor="sync",
                    hlc=hlc.tick(self._repo.latest_hlc(), _now_ms()),
                )
            else:
                step = SyncEntry(
                    id=uuid.uuid4(),
                    action="restore",
                    entity_type="record",
                    entity_id=rid,
                    old_data=None,
                    new_data=identity(snap),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    actor="sync",
                    hlc=hlc.tick(self._repo.latest_hlc(), _now_ms()),
                    delta={
                        "deleted_at": {
                            "before": was.isoformat() if was else None,
                            "after": None,
                        }
                    },
                )
            self._repo.insert_entry(step, hub_seq=self._repo.next_hub_seq())

    def _clash(
        self,
        kind: str,
        entity_id: uuid.UUID,
        path: str | None,
        yours: Any,
        theirs: Any,
        base: Any,
        what: str = "conflict",
        message: str | None = None,
    ) -> dict[str, Any]:
        """One thing that did not go in as made, as the answer carries it: both
        sides, what the value was, and who wrote the one that stayed and when.
        The device that sent the change keeps it for review (the authority keeps
        no list of its own)."""
        actor, via, at = self._repo.last_change(kind, entity_id, path)
        return {
            "kind": what,
            "field": path,
            "yours": yours,
            "theirs": theirs,
            "base": base,
            "theirs_actor": actor,
            "theirs_device": via,
            "theirs_at": at,
            "message": message,
        }

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
        incoming: dict[str, Any] | None,
    ) -> str:
        if conflicts:
            return CONFLICT
        if final is not None and entry.action in ("create", "update", "restore"):
            if _comparable(final) != _comparable(incoming or {}):
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
        incoming: dict[str, Any] | None,
    ) -> int:
        """Record the change as it was made (numbered), and, when what the
        authority settled on is not what was sent, a second entry carrying the
        settled state, so every device ends where the authority did."""
        # A change made on this instance itself that was saved while this push
        # was being merged is already in what was merged with, so it is
        # numbered first: numbered after, it would carry a state from before
        # this change and every device would apply it last.
        self._repo.sequence_local_entries()
        seq = self._repo.next_hub_seq()
        sent = SyncEntry(
            id=entry.id,
            action=entry.action,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            old_data=entry.old_data,
            new_data=entry.new_data,
            timestamp=entry.timestamp,
            # Who made it is what the device says, as given (the name a person
            # chose; a token proves a device, not a person). Which device sent
            # it is what the token says, never what was claimed.
            actor=_claimed_author(entry.actor) or device.name,
            device=device.name,
            device_id=device_id,
            hlc=self._believable(entry.hlc),
            batch=entry.batch,
            delta=entry.delta,
        )
        self._repo.insert_entry(sent, hub_seq=seq)
        if entry.action in ("create", "update", "restore", "delete") and (
            conflicts or _differs(entry, final, incoming)
        ):
            settled = self._applier.head(entry.entity_type, entry.entity_id)
            if settled is not None:
                # Whole, not a delta: the device whose change did not go in as
                # made holds values nobody else does (its own, or the thing
                # deleted), so a difference from what is held here would leave
                # them. The whole state puts every copy where this one is. Rare:
                # only a change that clashed, merged or met a delete has one.
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

    def _believable(self, stamp: str | None) -> str | None:
        """The stamp to keep for a change: the device's own, unless it claims to
        be further ahead than a clock may be, when the authority issues one."""
        if stamp is None or not hlc.is_ahead(stamp, _now_ms()):
            return stamp
        return hlc.tick(self._repo.latest_hlc(), _now_ms())


class _NotWhole(Exception):
    """Part of an action did not go in as made (its savepoint is undone)."""

    def __init__(self, results: list[OpResult]) -> None:
        super().__init__("not whole")
        self.results = results


def _kept_from_delete(results: list[OpResult], action: list[SyncEntry]):
    """Whether each part that didn't go in is a delete that met an edit."""
    for entry, result in zip(action, results):
        if result.status in (APPLIED, MERGED):
            continue
        yield entry.action == "delete" and all(
            c.get("kind") == "edit_vs_delete" for c in result.conflicts
        )


def _scope(entry: SyncEntry) -> dict[str, uuid.UUID]:
    key = "schema_id" if entry.entity_type == "schema" else "dataset_id"
    return {key: entry.entity_id}


def _changed(entries: list[SyncEntry]) -> list[tuple[str, uuid.UUID]]:
    """What the project's rules are asked about after these entries: the
    things they changed. A create is left out: it can't break a rule about
    what is already there (and filling an empty authority sends a schema before
    the fields its template uses); a record's own create is checked before it
    is written (`RecordService.check_incoming`)."""
    return [(e.entity_type, e.entity_id) for e in entries if e.action != "create"]


def _at_most(entries: list[SyncEntry], limit: int) -> list[SyncEntry]:
    """The first `limit` entries, and the rest of the action the last of them
    belongs to: an action is settled whole, so it is never cut in two."""
    kept = entries[:limit]
    if kept and kept[-1].op:
        last = kept[-1].op
        for entry in entries[limit:]:
            if entry.op != last:
                break
            kept.append(entry)
    return kept


def _actions(entries: list[SyncEntry]) -> list[list[SyncEntry]]:
    """Entries in runs of one action each (consecutive, sharing `op`); an entry
    with no `op` is an action of its own."""
    runs: list[list[SyncEntry]] = []
    for entry in entries:
        if runs and entry.op and runs[-1][-1].op == entry.op:
            runs[-1].append(entry)
        else:
            runs.append([entry])
    return runs


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _comparable(state: dict[str, Any]) -> dict[str, Any]:
    skip = LIFECYCLE_KEYS | DERIVED_KEYS
    return {k: v for k, v in state.items() if k not in skip}


def _edited_since(base: dict[str, Any] | None, head: dict[str, Any]) -> bool:
    """Whether head differs from what an edit started from."""
    return _comparable(base or {}) != _comparable(head)


def _differs(
    entry: SyncEntry, final: dict[str, Any] | None, incoming: dict[str, Any] | None
) -> bool:
    if entry.action == "delete":
        return final is not None  # the delete was not applied
    if final is None:
        return False
    return _comparable(final) != _comparable(incoming or {})


def _sides(
    entry: SyncEntry, head: dict[str, Any]
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """What an edit started from and what it made, as whole states. An entry of
    whole snapshots says so itself. A delta says only what it changed, so both
    sides are the thing as held here with those values put back or put in:
    everything it didn't touch is the same on all three sides of the merge,
    which is what "didn't touch" means to it. An edit is made to something that
    was, so what it made is deleted or not as the thing was where it was made
    (its identity says; an edit to something live that meets a delete keeps
    it, one made to something already deleted doesn't revive it)."""
    if entry.delta is None:
        return entry.old_data, entry.new_data or {}
    base = apply_delta(head, entry.delta, BEFORE)
    incoming = apply_delta(head, entry.delta, AFTER)
    if "deleted_at" not in entry.delta:
        incoming["deleted_at"] = (entry.new_data or {}).get("deleted_at")
    return base, incoming


def _claimed_author(name: str | None) -> str | None:
    """The author a device gives for a change, kept as a label: trimmed and
    capped. `sync` is the authority's own mark on what it writes (and what
    conflict descriptions skip), so a device can't take it."""
    if not isinstance(name, str):
        return None
    name = name.strip()[:100]
    return name if name and name != "sync" else None
