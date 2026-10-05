"""A device's side of sync: keep this project in step with its authority.

One sync is *pull, push, pull*. Pull brings in what others did (state-based, so
repeating it or missing part of it is harmless) and skips anything this device
has changed and not yet sent; push sends what this device changed, after the
files those changes cite; the second pull picks up what the authority settled
on when it merged them.

Everything here is safe to repeat. A change is identified by its history entry's
id, the cursor moves only after what it covers is saved, and a failure at any
point leaves the project as it was or one step further, never between.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from civex import user_state
from civex.config import Config, save_config
from civex.domain import hlc
from civex.domain.exceptions import ValidationError, VolumeUnavailableError
from civex.domain.file_refs import collect_sha256_refs
from civex.domain.sync import (
    DEFERRED,
    ENTITY_ORDER,
    PROTOCOL_VERSION,
    REJECTED,
    Hello,
    SyncConflictDTO,
    SyncEntry,
    SyncError,
    SyncTransport,
)
from civex.identity import local_actor
from civex.repositories.protocols import (
    AuditRepository,
    FileObjectStore,
    SyncRepository,
)
from civex.services.sync_applier import SyncApplier
from civex.services.sync_lock import sync_lock, sync_running

PUSH_BATCH = 100
FEED_PAGE = 200
SNAPSHOT_PAGE = 200

TransportFactory = Callable[[str, str, str], SyncTransport]


@dataclass
class SyncReport:
    pulled: int = 0  # changes from others brought in
    pushed: int = 0  # changes of ours the authority settled
    files_sent: int = 0
    conflicts: int = 0  # values that did not go in as made
    rejected: int = 0  # changes the authority refused
    waiting: int = 0  # changes held back (a file is not available yet)

    @property
    def changed(self) -> bool:
        return bool(self.pulled or self.pushed or self.files_sent)


@dataclass
class SyncStatus:
    configured: bool
    remote: str | None
    project_id: str
    paused: bool
    pending: int  # changes made here that the authority has not been sent
    open_conflicts: int
    cursor: int
    last_synced_at: str | None
    last_error: str | None
    last_error_at: str | None
    running: bool  # a sync is in progress right now
    interval_seconds: int = 60
    serving: bool = False  # this project is itself an authority


class SyncService:
    def __init__(
        self,
        config: Config,
        repo: SyncRepository,
        applier: SyncApplier,
        audit: AuditRepository,
        files: FileObjectStore,
        commit: Callable[[], None],
        make_transport: TransportFactory,
    ) -> None:
        self._config = config
        self._repo = repo
        self._applier = applier
        self._audit = audit
        self._files = files
        self._commit = commit
        self._make_transport = make_transport

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @property
    def configured(self) -> bool:
        return bool(self._config.sync.remote)

    def status(self) -> SyncStatus:
        meta = self._repo.meta()
        return SyncStatus(
            configured=self.configured,
            remote=self._config.sync.remote,
            project_id=str(meta.project_id),
            paused=self._config.sync.paused,
            pending=self._repo.count_pending() if self.configured else 0,
            open_conflicts=self._repo.count_conflicts("open"),
            cursor=meta.cursor,
            last_synced_at=meta.last_synced_at,
            last_error=meta.last_error,
            last_error_at=meta.last_error_at,
            running=sync_running(self._config.civex_dir),
            interval_seconds=self._config.sync.interval_seconds,
            serving=self._config.sync.serve,
        )

    def conflicts(self, status: str | None = "open") -> list[SyncConflictDTO]:
        return self._repo.list_conflicts(status)

    # ------------------------------------------------------------------
    # Connecting
    # ------------------------------------------------------------------

    def connect(self, url: str, token: str) -> str:
        """Point this project at an authority. What happens depends on who holds
        data: an empty project **joins** one that has some (it becomes a copy), an
        empty authority is **seeded** from a project that has some, and when both
        are empty they simply agree on a project id. Both holding data is refused:
        merging two histories needs a person to say which names are the same
        things, and that is not offered yet. Returns `joined`, `seeded`, `empty` or
        `resumed`."""
        url = url.strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            raise SyncError(
                "The address must start with http:// or https://", retryable=False
            )
        meta = self._repo.meta()
        probe = self._make_transport(
            url, token, str(user_state.device_id_for(meta.project_id))
        )
        hello = probe.hello()
        self._check_protocol(hello)

        local_empty = self._repo.entity_count() == 0
        mine = str(user_state.device_id_for(meta.project_id))
        if hello.project_id == meta.project_id:
            # Connected before. A first push that never finished leaves the
            # cursor at zero with this device named as the one that began it.
            unfinished = hello.seeded_by == mine and meta.cursor == 0
            mode = (
                "seeded"
                if not local_empty and (hello.empty or unfinished)
                else "resumed"
            )
        elif local_empty and hello.empty:
            mode = "empty"
        elif local_empty:
            mode = "joined"
        elif hello.empty or hello.seeded_by == mine:
            mode = "seeded"
        else:
            raise SyncError(
                "This project and the server both already hold data. Joining two "
                "separate projects is not supported yet: start from an empty "
                "project to copy the server's, or point an empty server here.",
                retryable=False,
            )

        # The project takes the authority's id; the device keeps its identity.
        if hello.project_id != meta.project_id:
            self._repo.set_project_id(hello.project_id)
            user_state.move_device(meta.project_id, hello.project_id)
            self._commit()
        user_state.save_token(url, token)
        self._config.sync.remote = url
        save_config(self._config)

        with sync_lock(self._config.civex_dir):
            transport = self._transport()
            if mode == "joined":
                self._join(transport)
            elif mode == "seeded":
                self._seed(transport)
            else:
                self._repo.set_cursor(
                    hello.head_seq if mode == "empty" else self._repo.meta().cursor
                )
                self._repo.mark_all_synced() if mode == "empty" else None
                self._commit()
            self._repo.record_outcome(None)
            self._commit()
        return mode

    def disconnect(self) -> None:
        remote = self._config.sync.remote
        self._config.sync.remote = None
        save_config(self._config)
        if remote:
            user_state.forget_token(remote)

    def set_paused(self, paused: bool) -> None:
        self._config.sync.paused = paused
        save_config(self._config)

    def set_interval(self, seconds: int) -> None:
        if seconds < 5:
            raise ValidationError("The interval must be at least 5 seconds")
        self._config.sync.interval_seconds = seconds
        save_config(self._config)

    def _check_protocol(self, hello: Hello) -> None:
        if hello.protocol_version != PROTOCOL_VERSION:
            raise SyncError(
                f"The server speaks sync protocol {hello.protocol_version}; this "
                f"civex speaks {PROTOCOL_VERSION}. Update the older one.",
                retryable=False,
            )

    def _transport(self) -> SyncTransport:
        remote = self._config.sync.remote
        if not remote:
            raise SyncError(
                "No server is set. Run `civex remote add <url> --token <token>`.",
                retryable=False,
            )
        token = user_state.token_for(remote)
        if not token:
            raise SyncError(
                f"This device has no token for {remote}. Run `civex remote add` again.",
                retryable=False,
            )
        device_id = user_state.device_id_for(self._repo.meta().project_id)
        return self._make_transport(remote, token, str(device_id))

    # ------------------------------------------------------------------
    # Syncing
    # ------------------------------------------------------------------

    def sync(self) -> SyncReport:
        """Pull, push, pull. Raises `SyncBusy` when another sync is running and
        `SyncError` when the authority can't be reached or refuses this device
        (`retryable` says whether trying later can help)."""
        with sync_lock(self._config.civex_dir):
            try:
                report = self._sync()
            except SyncError as e:
                self._commit_quietly()
                self._repo.record_outcome(str(e))
                self._commit()
                raise
            self._repo.record_outcome(None)
            self._commit()
            return report

    def _commit_quietly(self) -> None:
        try:
            self._commit()
        except Exception:  # noqa: BLE001 - nothing to save; the error matters more
            pass

    def _sync(self) -> SyncReport:
        transport = self._transport()
        hello = transport.hello()
        self._check_protocol(hello)
        meta = self._repo.meta()
        if hello.project_id != meta.project_id:
            raise SyncError(
                "The server holds a different project from this one", retryable=False
            )
        report = SyncReport()
        report.pulled += self._pull(transport)
        report.pushed += self._push(transport, report)
        if report.pushed or report.conflicts:
            report.pulled += self._pull(transport)
        return report

    def pull(self) -> int:
        with sync_lock(self._config.civex_dir):
            return self._pull(self._transport())

    # -- pull -------------------------------------------------------------

    def _pull(self, transport: SyncTransport) -> int:
        dirty = self._catch_up()
        cursor = self._repo.meta().cursor
        applied = 0
        while True:
            page = transport.feed(cursor, FEED_PAGE)
            for entry in page.entries:
                if entry.hub_seq is None:
                    raise SyncError("The server sent a change without a number")
                if self._repo.has_entry(entry.id):
                    self._repo.mark_seq(entry.id, entry.hub_seq)  # ours, now numbered
                else:
                    self._take(entry, dirty)
                    applied += 1
                cursor = entry.hub_seq
            self._repo.set_cursor(cursor)
            self._commit()
            if not page.more:
                return applied

    def _take(self, entry: SyncEntry, dirty: set[tuple[str, uuid.UUID]]) -> None:
        """Bring in one change from the authority. It is kept in the history
        either way. It is applied unless the authority did not settle on it as
        sent (a later entry carries what it settled on), or this device has a
        change to the same thing it hasn't sent yet. That one is kept *unapplied*
        and caught up once the push has settled the thing, whatever the outcome
        (merged, or refused): applying it then is what keeps this device from
        being left behind."""
        waiting = (entry.entity_type, entry.entity_id) in dirty
        if entry.superseded or self._repo.has_newer_state(
            entry.entity_type, entry.entity_id, entry.hub_seq or 0
        ):
            # Not where the thing ended up: the authority settled on something
            # else, or a change of ours that it numbered later already stands.
            # Applying it would roll the thing back.
            state = "superseded"
        elif waiting:
            state = "held"
        else:
            state = "applied"
            self._apply(entry)
        self._repo.insert_entry(entry, hub_seq=entry.hub_seq, apply_state=state)
        if state == "applied" and entry.action in ("create", "update", "restore"):
            self._reapply_later_delete(entry)

    def _reapply_later_delete(self, entry: SyncEntry) -> None:
        """A change can reach this device after a delete the authority numbered
        later (the delete was ours, and its answer came first). The state just
        applied would undo it, so the delete is applied again: it is the end."""
        thing = (entry.entity_type, entry.entity_id)
        entries = self._repo.effective_entries({thing}).get(thing) or []
        if (
            entries
            and entries[-1][1] in ("delete", "purge")
            and entries[-1][0] != entry.id
        ):
            last = self._repo.get_entry(entries[-1][0])
            if last is not None:
                self._apply(last)

    def _apply(self, entry: SyncEntry) -> None:
        try:
            with self._repo.savepoint():
                self._applier.apply_entry(entry)
        except ValidationError as e:
            self._repo.add_conflict(
                kind="not_applied",
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
                field=None,
                yours=None,
                theirs=entry.new_data,
                op_id=entry.id,
                device_name=entry.actor,
                message=f"Could not apply a change from the server: {e}",
            )

    def _catch_up(self) -> set[tuple[str, uuid.UUID]]:
        """Apply what was held back for things that are free now, but only
        where a held change is still where the thing ended up. An entry carries a
        whole state, so applying an old one over a newer would roll the thing
        back; if this device has since made (and sent) a change of its own, or
        the authority has settled on something later, the held entries are just
        history. Returns the things still waiting on a push of this device's own."""
        dirty = self._repo.dirty_entities()
        held = [
            e
            for e in self._repo.held_entries()
            if (e.entity_type, e.entity_id) not in dirty
        ]
        if not held:
            return dirty
        things = {(e.entity_type, e.entity_id) for e in held}
        effective = self._repo.effective_entries(things)
        by_id = {e.id: e for e in held}
        for thing in things:
            entries = effective.get(thing) or []
            # Where it ended up: the last entry that carries a state, and a delete
            # or purge after it. Each is applied if it is still held; one this
            # device already has (its own, say) is where the thing already is.
            carrier = next(
                (
                    e
                    for e in reversed(entries)
                    if e[1] in ("create", "update", "restore")
                ),
                None,
            )
            reapplied = bool(carrier and carrier[2] == "held")
            if reapplied and carrier:
                self._apply(by_id[carrier[0]])
            if entries and entries[-1][1] in ("delete", "purge"):
                last_id, _, last_state = entries[-1]
                # Applying a state can undo a delete (a restore brings the thing
                # back), so the delete after it is applied again even when it was
                # already applied before: it is idempotent, and it is the end.
                if reapplied or last_state == "held":
                    last = by_id.get(last_id) or self._repo.get_entry(last_id)
                    if last is not None:
                        self._apply(last)
        self._repo.mark_applied([e.id for e in held])
        self._commit()
        return dirty

    # -- push -------------------------------------------------------------

    def _push(self, transport: SyncTransport, report: SyncReport) -> int:
        total = 0
        while True:
            pending = self._repo.pending_entries(PUSH_BATCH)
            if not pending:
                return total
            ready = self._with_files(transport, pending, report)
            if not ready:
                report.waiting += len(pending)
                return total
            result = transport.push(ready)
            sent = {e.id: e for e in ready}
            self._repo.mark_sent(result.results)
            held = self._note(result.results, sent, report)
            self._commit()
            total += len(result.results) - held
            if held or len(result.results) < len(ready) or len(ready) < len(pending):
                report.waiting += held + (len(pending) - len(result.results))
                return total

    def _with_files(
        self, transport: SyncTransport, entries: list[SyncEntry], report: SyncReport
    ) -> list[SyncEntry]:
        """Send the files these changes cite that the authority lacks, and
        return the changes that may go: up to the first one citing a file this
        device can't read right now (a drive that is unplugged), since later
        changes may depend on it."""
        cited = {s for e in entries for s in collect_sha256_refs(e.new_data or {})}
        unavailable: set[str] = set()
        if cited:
            for sha in transport.missing_files(sorted(cited)):
                try:
                    transport.upload_file(sha, self._files.object_path(sha))
                    report.files_sent += 1
                except (FileNotFoundError, VolumeUnavailableError):
                    unavailable.add(sha)
        if not unavailable:
            return entries
        for i, entry in enumerate(entries):
            if collect_sha256_refs(entry.new_data or {}) & unavailable:
                return entries[:i]
        return entries

    def _note(
        self, results: list[Any], sent: dict[uuid.UUID, SyncEntry], report: SyncReport
    ) -> int:
        """Keep what the authority said that a person should see. Returns how
        many changes it held back."""
        held = 0
        for result in results:
            entry = sent.get(result.op_id)
            if entry is None:
                continue
            if result.status == DEFERRED:
                held += 1
            elif result.status == REJECTED:
                report.rejected += 1
                if not self._repo.has_conflict(result.op_id, None, "rejected"):
                    self._repo.add_conflict(
                        kind="rejected",
                        entity_type=entry.entity_type,
                        entity_id=entry.entity_id,
                        field=None,
                        yours=entry.new_data,
                        theirs=None,
                        op_id=result.op_id,
                        device_name=None,
                        message=result.message,
                    )
            for conflict in result.conflicts:
                kind = conflict.get("kind", "conflict")
                if self._repo.has_conflict(result.op_id, conflict.get("field"), kind):
                    continue
                report.conflicts += 1
                self._repo.add_conflict(
                    kind=kind,
                    entity_type=entry.entity_type,
                    entity_id=entry.entity_id,
                    field=conflict.get("field"),
                    yours=conflict.get("yours"),
                    theirs=conflict.get("theirs"),
                    op_id=result.op_id,
                    device_name=None,
                    message=conflict.get("message"),
                )
        return held

    # ------------------------------------------------------------------
    # Joining and seeding
    # ------------------------------------------------------------------

    def _join(self, transport: SyncTransport) -> None:
        """Become a copy of the authority: read everything as it is now, then
        its history. The number is taken before reading, so whatever changes
        meanwhile arrives in the feed, and state-based apply makes any overlap
        harmless."""
        head: int | None = None
        for kind in ENTITY_ORDER:
            offset = 0
            while True:
                page = transport.snapshot(kind, offset, SNAPSHOT_PAGE)
                head = page.head_seq if head is None else head
                for snap in page.items:
                    self._repo.apply_snapshot(kind, snap)
                self._commit()
                if not page.more:
                    break
                offset += len(page.items)
        head = head or 0
        self._backfill_history(transport, head)
        self._repo.set_cursor(head)
        self._repo.mark_all_synced()
        self._commit()
        self._pull(transport)

    def _backfill_history(self, transport: SyncTransport, upto: int) -> None:
        """Keep the authority's history as this project's own, without applying
        it (the snapshot already holds where it all ended up)."""
        after = 0
        while after < upto:
            page = transport.feed(after, FEED_PAGE)
            for entry in page.entries:
                if entry.hub_seq is None or entry.hub_seq > upto:
                    return
                if not self._repo.has_entry(entry.id):
                    self._repo.insert_entry(entry, hub_seq=entry.hub_seq)
                after = entry.hub_seq
            self._commit()
            if not page.more:
                return

    def _seed(self, transport: SyncTransport) -> None:
        """Give an empty authority everything this project holds. Each thing is
        sent as a create with an id made from the project and the thing, so an
        interrupted seed can simply be run again."""
        meta = self._repo.meta()
        device_id = str(user_state.device_id_for(meta.project_id))
        actor = local_actor()
        head = meta.cursor
        problems: list[str] = []
        batch: list[SyncEntry] = []

        def flush() -> None:
            nonlocal head, batch
            if not batch:
                return
            ready = self._with_files(transport, batch, SyncReport())
            if len(ready) < len(batch):
                raise SyncError(
                    "A file this project cites can't be read right now (is a drive "
                    "unplugged?), so it can't be sent yet",
                    retryable=True,
                )
            result = transport.push(batch)
            head = result.head_seq
            for r in result.results:
                if r.status == REJECTED:
                    problems.append(r.message or "refused")
                elif r.status == DEFERRED:
                    raise SyncError(
                        "The server is still waiting for a file", retryable=True
                    )
            batch = []

        for kind in ENTITY_ORDER:
            offset = 0
            while True:
                snaps = self._repo.snapshots_page(kind, offset, SNAPSHOT_PAGE)
                for snap in snaps:
                    now = datetime.now(timezone.utc)
                    batch.append(
                        SyncEntry(
                            id=uuid.uuid5(meta.project_id, f"seed:{kind}:{snap['id']}"),
                            action="create",
                            entity_type=kind,
                            entity_id=uuid.UUID(snap["id"]),
                            old_data=None,
                            new_data=snap,
                            timestamp=now.isoformat(),
                            actor=actor,
                            device_id=device_id,
                            hlc=hlc.tick(
                                self._repo.latest_hlc(), int(now.timestamp() * 1000)
                            ),
                        )
                    )
                    if len(batch) >= PUSH_BATCH:
                        flush()
                if len(snaps) < SNAPSHOT_PAGE:
                    break
                offset += len(snaps)
        flush()
        if problems:
            raise SyncError(
                f"The server refused {len(problems)} thing(s) while being filled: "
                f"{problems[0]}",
                retryable=False,
            )
        self._repo.mark_all_synced()
        self._repo.set_cursor(head)
        self._commit()

    # ------------------------------------------------------------------
    # Conflicts
    # ------------------------------------------------------------------

    def resolve_conflict(self, conflict_id: uuid.UUID, take: str) -> None:
        """Settle a conflict. `theirs` keeps what the authority has (nothing to
        do: this project already agrees). `mine` makes the value this device set
        an ordinary change of its own, which syncs like any edit."""
        conflict = self._repo.get_conflict(conflict_id)
        if conflict is None or conflict.status != "open":
            raise ValidationError("That conflict is not open")
        if take not in ("mine", "theirs"):
            raise ValidationError("Choose 'mine' or 'theirs'")
        if take == "mine":
            self._reapply(conflict)
        self._repo.resolve_conflict(conflict_id, take)
        self._commit()

    def _reapply(self, conflict: SyncConflictDTO) -> None:
        if conflict.kind != "conflict" or not conflict.field:
            raise ValidationError("Only a value that clashed can be put back as yours")
        current = self._repo.snapshot(conflict.entity_type, conflict.entity_id)
        if current is None:
            raise ValidationError("It no longer exists")
        edited = _with_value(current, conflict.field, conflict.yours)
        self._repo.apply_snapshot(conflict.entity_type, edited)
        self._audit.log_change(
            "update", conflict.entity_type, conflict.entity_id, current, edited
        )


def _with_value(snapshot: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    """`snapshot` with one value changed: `data.<field id>` for a record's value,
    else an attribute. A value that was removed (None) is removed."""
    edited = {k: (dict(v) if isinstance(v, dict) else v) for k, v in snapshot.items()}
    if "." in path:
        top, _, sub = path.partition(".")
        container = dict(edited.get(top) or {})
        if value is None:
            container.pop(sub, None)
        else:
            container[sub] = value
        edited[top] = container
    else:
        edited[path] = value
    return edited
