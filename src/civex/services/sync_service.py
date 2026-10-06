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

import logging

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from civex import user_state
from civex.config import Config, save_config
from civex.domain import hlc
from civex.domain.exceptions import (
    CivexError,
    ConflictMovedError,
    ValidationError,
    VolumeUnavailableError,
)
from civex.domain.file_refs import collect_sha256_refs, without_file_locations
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
from civex.services.record_service import RecordService
from civex.services.sync_applier import SyncApplier
from civex.services.sync_lock import sync_lock, sync_running

PUSH_BATCH = 100
# How many referenced files are checked against the authority per request.
FILE_CHECK_PAGE = 1000
FEED_PAGE = 200
SNAPSHOT_PAGE = 200

# Stands for "the value on the record now" in an attempt's fields, until it is read.
_NOW: Any = object()

TransportFactory = Callable[[str, str, str], SyncTransport]


log = logging.getLogger(__name__)


@dataclass
class SyncReport:
    pulled: int = 0  # changes from others brought in
    pushed: int = 0  # changes of ours the authority settled
    files_sent: int = 0
    conflicts: int = 0  # values that did not go in as made
    rejected: int = 0  # changes the authority refused
    waiting: int = 0  # changes held back (a file is not available yet)
    # Files the authority still lacks because this computer cannot read them
    # (a drive that is unplugged, bytes not recovered yet). The changes citing
    # them have gone; the files follow when they can be read.
    owed_files: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.pulled or self.pushed or self.files_sent)


@dataclass
class ResolveManyReport:
    """What settling several conflicts at once did."""

    done: int = 0  # settled (or, for a dry run, that would be)
    settled: list[uuid.UUID] = field(default_factory=list)  # which (not a dry run)
    not_offered: int = 0  # left open: this way of settling isn't theirs to take
    failed: list[tuple[uuid.UUID, str]] = field(default_factory=list)  # left open


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
        records: RecordService,
    ) -> None:
        self._config = config
        self._repo = repo
        self._applier = applier
        self._audit = audit
        self._files = files
        self._commit = commit
        self._make_transport = make_transport
        # What a person does about a conflict is an ordinary edit, made by the
        # record service like any other: validated, in the history, synced.
        self._records = records

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

    def conflicts(
        self, status: str | None = "open", entity_id: uuid.UUID | None = None
    ) -> list[SyncConflictDTO]:
        """The conflicts (of one thing, if `entity_id`), each described for a
        person (`_describe`)."""
        return self._describe(self._repo.list_conflicts(status, entity_id=entity_id))

    def conflicts_of_entries(
        self, entry_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[SyncConflictDTO]]:
        """The conflicts, open or settled, each history entry gave rise to (an
        entry is the change that was sent, and a conflict remembers which), so
        history can show that a change did not go in as made and how it ended.
        One lookup for the whole page."""
        out: dict[uuid.UUID, list[SyncConflictDTO]] = {}
        for c in self._describe(self._repo.conflicts_of_ops(entry_ids)):
            if c.op_id is not None:
                out.setdefault(c.op_id, []).append(c)
        return out

    def _describe(self, found: list[SyncConflictDTO]) -> list[SyncConflictDTO]:
        """Add what a row needs to be recognised and acted on: the record's name
        and where it is, the field's label and type, the value on the record now
        (and whether it is still the one that stayed), what can be done, and what
        else the same edit saved. Worked out when read, so a rename shows and
        nothing is copied into the row."""
        saved = {c.id: self._also_saved(c, found) for c in found}
        attempts = {c.id: self._attempt(c) for c in found}
        pairs = [
            (str(c.entity_id), fid)
            for c in found
            if c.entity_type == "record"
            for fid in [
                _field_id(c) or "",
                *saved[c.id],
                *attempts[c.id][1],
            ]
        ]
        values = self._records.field_values(pairs)
        out = []
        for c in found:
            takes = list(_takes_for(c))
            v = values.get((str(c.entity_id), _field_id(c) or ""))
            if v is None:
                out.append(replace(c, takes=takes))
                continue
            current = without_file_locations(v.value) if c.field else None
            also = [
                {"field_label": w.field_label, "value": without_file_locations(w.value)}
                for fid in saved[c.id]
                if (w := values.get((str(c.entity_id), fid))) and w.field_label
            ]
            out.append(
                replace(
                    c,
                    record_name=v.record_name,
                    dataset_name=v.dataset_name,
                    schema_name=v.schema_name,
                    field_label=v.field_label,
                    dtype=v.dtype,
                    current=current,
                    stale=c.kind == "conflict"
                    and c.status == "open"
                    and current != c.theirs,
                    record_deleted=v.record_deleted,
                    takes=takes,
                    also_saved=also,
                    attempted=attempts[c.id][0],
                    changes=[
                        {
                            "field_id": fid,
                            "field_name": w.field_name,
                            "field_label": w.field_label,
                            "dtype": w.dtype,
                            "before": without_file_locations(before),
                            "after": without_file_locations(
                                w.value if after is _NOW else after
                            ),
                            "current": without_file_locations(w.value),
                        }
                        for fid, (before, after) in attempts[c.id][1].items()
                        if (w := values.get((str(c.entity_id), fid)))
                        and w.field_label
                        and (
                            after is not _NOW
                            or without_file_locations(before)
                            != without_file_locations(w.value)
                        )
                    ],
                )
            )
        return out

    def _attempt(
        self, conflict: SyncConflictDTO
    ) -> tuple[str | None, dict[str, tuple[Any, Any]]]:
        """What the change behind a refusal, or an edit that met a delete, was
        trying to do: its action and, field id by field id, the value before and
        the value it set (only those it changed). `(None, {})` for a clash (which
        names its own field) or when the entry is not there."""
        if conflict.kind == "conflict" or conflict.entity_type != "record":
            return None, {}
        entry = self._repo.get_entry(conflict.op_id) if conflict.op_id else None
        if entry is None:
            return None, {}
        before = (entry.old_data or {}).get("data") or {}
        after = (entry.new_data or {}).get("data") or {}
        if entry.action == "delete":
            # A delete sets nothing. What there is to see is what the other side
            # did meanwhile (the reason it was not applied): the record as it was
            # when it was deleted, and as it is now. `_describe` fills in "now".
            return entry.action, {fid: (before[fid], _NOW) for fid in sorted(before)}
        return entry.action, {
            fid: (before.get(fid), after.get(fid))
            for fid in sorted(set(before) | set(after))
            if before.get(fid) != after.get(fid)
        }

    def _also_saved(
        self, conflict: SyncConflictDTO, rows: list[SyncConflictDTO]
    ) -> list[str]:
        """Field ids the edit behind a clash set that did go in: those it changed
        that are not themselves clashing (in this list or settled since)."""
        if conflict.kind != "conflict" or conflict.entity_type != "record":
            return []
        entry = self._repo.get_entry(conflict.op_id) if conflict.op_id else None
        if entry is None:
            return []
        before = (entry.old_data or {}).get("data") or {}
        after = (entry.new_data or {}).get("data") or {}
        clashing = {_field_id(c) for c in rows if c.op_id == conflict.op_id}
        return [
            fid
            for fid in sorted(set(before) | set(after))
            if before.get(fid) != after.get(fid) and fid not in clashing
        ]

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
        if seconds != 0 and seconds < 5:
            raise ValidationError(
                "The interval must be at least 5 seconds, or 0 to sync only when asked"
            )
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

    def sync(self, check_files: bool = True) -> SyncReport:
        """Pull, push, pull. Raises `SyncBusy` when another sync is running and
        `SyncError` when the authority can't be reached or refuses this device
        (`retryable` says whether trying later can help). `check_files` also
        looks for files the authority lacks that can be read here now (a
        drive plugged back in); a background sync does that every few minutes
        rather than every time."""
        with sync_lock(self._config.civex_dir):
            log.info("sync with %s: starting", self._config.sync.remote)
            try:
                report = self._sync(check_files)
            except SyncError as e:
                log.warning(
                    "sync with %s failed (%s): %s",
                    self._config.sync.remote,
                    "will retry" if e.retryable else "will not retry until fixed",
                    e,
                )
                self._commit_quietly()
                self._repo.record_outcome(str(e))
                self._commit()
                raise
            log.info(
                "sync with %s: received %d, sent %d, files sent %d, conflicts %d, "
                "refused %d, waiting %d",
                self._config.sync.remote,
                report.pulled,
                report.pushed,
                report.files_sent,
                report.conflicts,
                report.rejected,
                report.waiting,
            )
            self._repo.record_outcome(None)
            self._commit()
            return report

    def _commit_quietly(self) -> None:
        try:
            self._commit()
        except Exception:  # noqa: BLE001 - nothing to save; the error matters more
            pass

    def _sync(self, check_files: bool = True) -> SyncReport:
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
        if check_files:
            self._send_missing_files(transport, report)
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
        """Send the files these changes cite that the authority lacks. The
        changes always go: a file this computer cannot read right now (a drive
        that is unplugged, bytes still to be recovered) is skipped, and
        `_send_missing_files` finds it again once it can be read. Data and files
        converge separately, so a missing file never holds up a change."""
        cited = {s for e in entries for s in collect_sha256_refs(e.new_data or {})}
        if cited:
            for sha in transport.missing_files(sorted(cited)):
                self._upload(transport, sha, report)  # unreadable: caught up later
        return entries

    def _upload(self, transport: SyncTransport, sha: str, report: SyncReport) -> bool:
        try:
            transport.upload_file(sha, self._files.object_path(sha))
        except (FileNotFoundError, VolumeUnavailableError):
            return False
        report.files_sent += 1
        return True

    def _send_missing_files(self, transport: SyncTransport, report: SyncReport) -> None:
        """Make the authority hold every file a live record here cites and this
        computer can read. Nothing is remembered between syncs: what is missing
        is worked out from the references catalog and the authority's answer, so
        a drive plugged back in, or files added later, are simply found. A file
        that still can't be read is counted and left for next time."""
        after = ""
        while True:
            page = self._repo.referenced_shas(after, FILE_CHECK_PAGE)
            if not page:
                break
            after = page[-1]
            for sha in transport.missing_files(page):
                if not self._upload(transport, sha, report):
                    report.owed_files.append(sha)
        if report.owed_files:
            log.info(
                "sync with %s: %d file(s) the authority lacks cannot be read here "
                "yet; they go when they can: %s",
                self._config.sync.remote,
                len(report.owed_files),
                ", ".join(x[:10] for x in report.owed_files[:5]),
            )

    def _note(
        self, results: list[Any], sent: dict[uuid.UUID, SyncEntry], report: SyncReport
    ) -> int:
        """Keep what the authority said that a person should see: a clash, or a
        refusal (the same kind of row, so one path). Returns how many changes it
        held back."""
        held = 0
        for result in results:
            entry = sent.get(result.op_id)
            if entry is None:
                continue
            if result.status == DEFERRED:
                held += 1
                continue
            problems = result.conflicts
            if result.status == REJECTED:
                report.rejected += 1
                problems = [
                    {
                        "kind": "rejected",
                        "field": None,
                        "yours": entry.new_data,
                        "message": result.message,
                    }
                ]
            for problem in problems:
                kind = problem.get("kind", "conflict")
                if self._repo.has_conflict(result.op_id, problem.get("field"), kind):
                    continue
                if result.status != REJECTED:
                    report.conflicts += 1
                self._repo.add_conflict(
                    kind=kind,
                    entity_type=entry.entity_type,
                    entity_id=entry.entity_id,
                    field=problem.get("field"),
                    yours=problem.get("yours"),
                    theirs=problem.get("theirs"),
                    base=problem.get("base"),
                    theirs_actor=problem.get("theirs_actor"),
                    theirs_at=problem.get("theirs_at"),
                    op_id=result.op_id,
                    device_name=None,
                    message=problem.get("message"),
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

    def _seed_snapshots(self, kind: str) -> Iterator[dict[str, Any]]:
        """What to send for `kind`, in an order the authority can accept: a
        record only after the one it sits under and the ones it refers to, since
        the authority checks both and remembers a refusal for good."""
        if kind == "record":
            order = self._repo.record_seed_order()
            for start in range(0, len(order), SNAPSHOT_PAGE):
                yield from self._repo.record_snapshots(
                    order[start : start + SNAPSHOT_PAGE]
                )
            return
        offset = 0
        while True:
            snaps = self._repo.snapshots_page(kind, offset, SNAPSHOT_PAGE)
            yield from snaps
            if len(snaps) < SNAPSHOT_PAGE:
                return
            offset += len(snaps)

    @staticmethod
    def _why_refused(problems: list[str]) -> str:
        """The distinct reasons, most common first, so a thousand records with
        the same cause read as one line."""
        counts: dict[str, int] = {}
        for p in problems:
            counts[p] = counts.get(p, 0) + 1
        top = sorted(counts.items(), key=lambda kv: -kv[1])[:3]
        return " ".join(f"{n} \u00d7 {why}." for why, n in top)

    def _seed(self, transport: SyncTransport) -> None:
        """Give an empty authority everything this project holds. Each thing is
        sent as a create with an id made from the project and the thing, so an
        interrupted seed can simply be run again."""
        meta = self._repo.meta()
        device_id = str(user_state.device_id_for(meta.project_id))
        actor = local_actor(self._config.identity.name)
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
            for snap in self._seed_snapshots(kind):
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
        flush()
        if problems:
            raise SyncError(
                f"The server refused {len(problems)} thing(s) while being filled. "
                f"{self._why_refused(problems)}",
                retryable=False,
            )
        self._repo.mark_all_synced()
        self._repo.set_cursor(head)
        self._commit()

    # ------------------------------------------------------------------
    # Conflicts
    # ------------------------------------------------------------------

    def resolve_conflict(
        self,
        conflict_id: uuid.UUID,
        take: str,
        value: Any = None,
        force: bool = False,
    ) -> None:
        """Settle a conflict. What can be done depends on what it is:

        - a clashing value: `theirs` keeps what the authority has (nothing to do:
          this project already agrees), `mine` puts this device's value back,
          `value` puts another one, and `edited` closes it because the person
          has just set the field on the record page themselves (an ordinary edit
          there, so nothing is put back here);
        - an edit to something deleted there: `theirs` keeps it as it is,
          `delete` deletes it;
        - a refused change: `retry` sends it again from the thing as it is now
          (after the cause was put right), `theirs` lets it go.

        Putting a value back is an ordinary edit by the record service, so it is
        checked like any, appears in the history and syncs. If the value on the
        record is no longer the one that was kept (it changed again since the
        person looked), this refuses with what is there now unless `force`."""
        conflict = self._repo.get_conflict(conflict_id)
        if conflict is None or conflict.status != "open":
            raise ValidationError("That conflict is not open")
        # `edited` is not a choice to offer: the record page sends it once the
        # person has set the field themselves, so a clash is all it closes.
        if take not in _takes_for(conflict) and not (
            take == "edited" and conflict.kind == "conflict"
        ):
            raise ValidationError(f"A {conflict.kind} can't be settled with '{take}'")
        if take in ("mine", "value"):
            self._put_value(
                conflict, conflict.yours if take == "mine" else value, force
            )
        elif take == "delete":
            self._records.delete(str(conflict.entity_id))
        elif take == "retry":
            self._resend(conflict)
        self._repo.resolve_conflict(conflict_id, take)
        self._commit()

    def resolve_many(
        self,
        take: str,
        *,
        ids: list[uuid.UUID] | None = None,
        kind: str | None = None,
        entity_id: uuid.UUID | None = None,
        force: bool = False,
        dry_run: bool = False,
    ) -> ResolveManyReport:
        """Settle every open conflict matching all that is given (`ids`, `kind`,
        the record it is about; nothing given = all of them) the same way.

        A conflict that doesn't offer `take` is left open and counted in
        `not_offered`; one that fails its checks (a value that changed again, a
        field that is gone) is left open and listed in `failed`, and the rest still
        go. `theirs` is bookkeeping (this project already holds the authority's
        value), so it is one statement and one commit however many there are; any
        other way is an ordinary edit per conflict. `dry_run` only counts."""
        report = ResolveManyReport()
        offered: list[SyncConflictDTO] = []
        for c in self._repo.find_open_conflicts(
            ids=ids, kind=kind, entity_id=entity_id
        ):
            if take in _takes_for(c):
                offered.append(c)
            else:
                report.not_offered += 1
        if dry_run:
            report.done = len(offered)
            return report
        if take == "theirs":
            report.settled = [c.id for c in offered]
            report.done = self._repo.resolve_conflicts(report.settled, take)
            self._commit()
            return report
        for c in offered:
            try:
                self.resolve_conflict(c.id, take, force=force)
                report.done += 1
                report.settled.append(c.id)
            except CivexError as e:
                report.failed.append((c.id, str(e)))
        return report

    def reopen_conflicts(self, ids: list[uuid.UUID]) -> int:
        """Take back conflicts settled with `theirs`: that choice changed nothing
        in the data, so the row can simply be open again. Putting a value back,
        deleting or sending again each made an edit, which is undone from
        Activity (they are not reopened here). Returns how many were reopened."""
        n = self._repo.reopen_conflicts(ids, "theirs")
        self._commit()
        return n

    def _put_value(self, conflict: SyncConflictDTO, value: Any, force: bool) -> None:
        field_id = _field_id(conflict)
        if conflict.entity_type != "record" or field_id is None:
            raise ValidationError("Only a record's value can be put back")
        rid = str(conflict.entity_id)
        found = self._records.field_values([(rid, field_id)]).get((rid, field_id))
        if found is None or found.record_deleted:
            raise ValidationError("The record is deleted: restore it first")
        if found.field_name is None:
            raise ValidationError("That field no longer exists")
        current = without_file_locations(found.value)
        if not force and current != conflict.theirs:
            raise ConflictMovedError(
                f"{found.field_label} has changed since this was recorded", current
            )
        self._records.patch(rid, {found.field_name: value})

    def _resend(self, conflict: SyncConflictDTO) -> None:
        """Send a refused change again, from the thing as it is now: the same
        kind of change on the same starting point, new content. A new entry (the
        authority remembers the old one's answer by its id)."""
        current = self._repo.snapshot(conflict.entity_type, conflict.entity_id)
        if current is None:
            raise ValidationError(
                "It no longer exists here, so there is nothing to send"
            )
        original = self._repo.get_entry(conflict.op_id) if conflict.op_id else None
        if original is None:
            raise ValidationError("The change is no longer held here")
        if original.action not in ("create", "update", "restore"):
            raise ValidationError("Only a created or edited thing can be sent again")
        self._audit.log_change(
            original.action,
            conflict.entity_type,
            conflict.entity_id,
            original.old_data,
            current,
        )


# What each kind of conflict can be settled with. Only a record's values can be
# put back or deleted by a person; a refused change of anything can be sent again.
_TAKES: dict[str, tuple[str, ...]] = {
    "conflict": ("theirs", "mine", "value"),
    "edit_vs_delete": ("theirs", "delete"),
    "rejected": ("theirs", "retry"),
}
_RECORD_ONLY = frozenset({"mine", "value", "delete"})


def _takes_for(conflict: SyncConflictDTO) -> tuple[str, ...]:
    takes = _TAKES.get(conflict.kind, ("theirs",))
    if conflict.entity_type == "record":
        return takes
    return tuple(t for t in takes if t not in _RECORD_ONLY)


def _field_id(conflict: SyncConflictDTO) -> str | None:
    """The field id a conflict is about (`data.<field id>`), if it is about one."""
    top, _, sub = (conflict.field or "").partition(".")
    return sub if top == "data" and sub else None
