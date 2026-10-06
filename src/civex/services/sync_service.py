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
from civex.domain.audit_diff import BEFORE, apply_delta, entry_snapshots
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
    COPYING,
    FILLING,
    HISTORY,
    REJECTED,
    Hello,
    SyncConflictDTO,
    SyncEntry,
    SyncError,
    SyncProgress,
    SyncTransport,
    snapshot_cursor,
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
# The cursor while a copy from the authority is being made (`_join`).
JOINING = -1
# Told how far a long step (copying, filling, fetching history) has got.
ProgressFn = Callable[[SyncProgress], None]


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
        old, new = entry_snapshots(entry.old_data, entry.new_data, entry.delta)
        before = (old or {}).get("data") or {}
        after = (new or {}).get("data") or {}
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
        old, new = entry_snapshots(entry.old_data, entry.new_data, entry.delta)
        before = (old or {}).get("data") or {}
        after = (new or {}).get("data") or {}
        clashing = {_field_id(c) for c in rows if c.op_id == conflict.op_id}
        return [
            fid
            for fid in sorted(set(before) | set(after))
            if before.get(fid) != after.get(fid) and fid not in clashing
        ]

    # ------------------------------------------------------------------
    # Connecting
    # ------------------------------------------------------------------

    def check_connect(self, url: str, token: str) -> str:
        """What connecting to this authority would do, found out without doing
        it: the address is read, the token and protocol accepted, and who holds
        data decided. Quick, so a mistake is said at once even when the copying
        itself then runs in the background. Returns the mode `connect` would."""
        return self._plan_connect(url, token)[0]

    def _plan_connect(self, url: str, token: str) -> tuple[str, Hello, str]:
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
            # cursor at zero with this device named as the one that began it;
            # a copy that never finished leaves it at JOINING (or nothing here).
            unfinished = hello.seeded_by == mine and meta.cursor == 0
            if meta.cursor == JOINING or (local_empty and not hello.empty):
                mode = "joined"
            elif not local_empty and (hello.empty or unfinished):
                mode = "seeded"
            else:
                mode = "resumed"
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
        return mode, hello, url

    def connect(self, url: str, token: str, progress: ProgressFn | None = None) -> str:
        """Point this project at an authority. What happens depends on who holds
        data: an empty project **joins** one that has some (it becomes a copy), an
        empty authority is **seeded** from a project that has some, and when both
        are empty they simply agree on a project id. Both holding data is refused:
        merging two histories needs a person to say which names are the same
        things, and that is not offered yet. Returns `joined`, `seeded`, `empty` or
        `resumed`.

        `progress` hears how far copying has got. A joined project is usable
        once it returns; the history from before it joined is fetched after
        (`fetch_history`), by whatever runs sync next."""
        mode, hello, url = self._plan_connect(url, token)
        meta = self._repo.meta()

        # The project takes the authority's id; the device keeps its identity.
        if hello.project_id != meta.project_id:
            self._repo.set_project_id(hello.project_id)
            user_state.move_device(meta.project_id, hello.project_id)
            # Where this project had got to, and what it was waiting to have
            # reviewed, were about the authority it followed before.
            self._repo.set_cursor(0)
            self._repo.resolve_conflicts(
                [c.id for c in self._repo.find_open_conflicts()],
                "followed another server",
            )
            self._commit()
        user_state.save_token(url, token)
        self._config.sync.remote = url
        save_config(self._config)

        with sync_lock(self._config.civex_dir):
            transport = self._transport()
            if mode == "joined":
                self._join(transport, hello, progress)
            elif mode == "seeded":
                self._seed(transport, progress)
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
        if meta.cursor == JOINING:
            raise SyncError(
                "Copying the project from the server did not finish. Connect again "
                "to finish it.",
                retryable=False,
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
        thing = (entry.entity_type, entry.entity_id)
        if entry.superseded:
            state = "superseded"
        elif thing in dirty:
            state = "held"
        else:
            state = "applied"
        self._repo.insert_entry(entry, hub_seq=entry.hub_seq, apply_state=state)
        if state == "applied":
            self._replay(thing, entry.hub_seq or 0)

    def _replay(self, thing: tuple[str, uuid.UUID], from_seq: int) -> None:
        """Bring a thing to where the authority's numbered changes leave it,
        from `from_seq` on: each in turn, in the authority's order. Every
        numbered change it did not supersede is a step the authority took (an
        edit as made, the state it settled on, its own edits), so taking the
        same steps in the same order ends in the same place. Changes of this
        device's own that were numbered later are already applied here, but
        they are taken again after the one arriving now, since that is their
        order; taking a step twice is harmless."""
        for step in self._repo.numbered_entries(thing[0], thing[1], from_seq):
            self._apply(step)

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
        """Apply what was held back for things that are free now: each from its
        first held change on, in the authority's order, together with this
        device's own changes numbered among them (`_replay`). Returns the things
        still waiting on a push of this device's own."""
        dirty = self._repo.dirty_entities()
        held = [
            e
            for e in self._repo.held_entries()
            if (e.entity_type, e.entity_id) not in dirty
        ]
        if not held:
            return dirty
        first: dict[tuple[str, uuid.UUID], int] = {}
        for e in held:
            thing = (e.entity_type, e.entity_id)
            first[thing] = min(first.get(thing, e.hub_seq or 0), e.hub_seq or 0)
        for thing, seq in first.items():
            self._replay(thing, seq)
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

    def _join(
        self,
        transport: SyncTransport,
        hello: Hello,
        progress: ProgressFn | None = None,
    ) -> None:
        """Become a copy of the authority: read everything as it is now. The
        number is taken before reading, so whatever changes meanwhile arrives in
        the feed, and applying it over the copy is harmless. Anything changed
        here while joining is a change of this device's own and is sent like any
        other. The history from before is not read here: the copy is usable
        without it, and `fetch_history` brings it after."""
        # What this project recorded before it joined is about nothing the copy
        # holds (a joining project is empty), so there is nothing to send. Until
        # the copy is whole the cursor says so (JOINING): syncing is refused and
        # connecting again copies again, never a feed applied to half a copy.
        self._repo.mark_all_synced()
        self._repo.set_cursor(JOINING)
        self._commit()
        total = sum(hello.counts.get(k, 0) for k in ENTITY_ORDER) or None
        done = 0
        head: int | None = None
        for kind in ENTITY_ORDER:
            # Things that sit under another of their kind that has not arrived
            # yet (it was made later, on a clock that was ahead): the database
            # refuses them until it has, so they wait for it, by its id.
            waiting: dict[str, list[dict[str, Any]]] = {}
            after: str | None = None
            while True:
                page = transport.snapshot(kind, after, SNAPSHOT_PAGE)
                head = page.head_seq if head is None else head
                above = {p for snap in page.items if (p := _sits_under(kind, snap))}
                present = self._repo.existing_ids(kind, above)
                for snap in page.items:
                    self._join_one(kind, snap, present, waiting)
                self._commit()
                done += len(page.items)
                if progress:
                    # Things made while copying can take it past the count.
                    progress(
                        SyncProgress(COPYING, done, total and max(total, done), kind)
                    )
                if not page.more:
                    break
                after = page.next
            if waiting:
                # What they sit under was removed for good while the copy was
                # read, and they went with it there.
                log.info(
                    "joining: %d %s(s) whose parent was removed meanwhile were "
                    "left out",
                    sum(len(v) for v in waiting.values()),
                    kind,
                )
        head = head or 0
        self._repo.set_cursor(head)
        self._repo.set_history_from(head or None)
        self._commit()
        self._pull(transport)

    def fetch_history(
        self, progress: ProgressFn | None = None, pages: int | None = None
    ) -> bool:
        """Fetch the history from before this project joined, oldest first, a
        page at a time (each saved as it arrives, so stopping loses nothing and
        the next call carries on). `pages` limits how much one call does, for a
        background sync that shouldn't hold the lock for long. Returns True once
        all of it is here. It is history only: nothing is applied, since the
        copy already holds where it all ended up."""
        upto = self._repo.meta().history_from
        if not upto:
            return True
        with sync_lock(self._config.civex_dir):
            transport = self._transport()
            after = self._repo.history_fetched_upto(upto)
            read = 0
            while after < upto and (pages is None or read < pages):
                page = transport.feed(after, FEED_PAGE)
                read += 1
                for entry in page.entries:
                    if entry.hub_seq is None or entry.hub_seq > upto:
                        break
                    if not self._repo.has_entry(entry.id):
                        self._repo.insert_entry(entry, hub_seq=entry.hub_seq)
                    after = entry.hub_seq
                self._commit()
                if progress:
                    progress(SyncProgress(HISTORY, min(after, upto), upto))
                last = page.entries[-1].hub_seq if page.entries else None
                if not page.more or last is None or last > upto:
                    after = upto  # nothing more up to it (some may be pruned)
            if after >= upto:
                self._repo.set_history_from(None)
                self._commit()
                return True
            return False

    def _join_one(
        self,
        kind: str,
        snap: dict[str, Any],
        present: set[str],
        waiting: dict[str, list[dict[str, Any]]],
    ) -> None:
        """Write one thing from the copy, or keep it until what it sits under
        has been written; then whatever was waiting for it."""
        above = _sits_under(kind, snap)
        if above and above not in present:
            waiting.setdefault(above, []).append(snap)
            return
        ready = [snap]
        while ready:
            item = ready.pop()
            self._repo.apply_snapshot(kind, item)
            present.add(item["id"])
            ready.extend(waiting.pop(item["id"], ()))

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
        after: str | None = None
        while True:
            snaps = self._repo.snapshots_page(kind, after, SNAPSHOT_PAGE)
            yield from snaps
            if len(snaps) < SNAPSHOT_PAGE:
                return
            after = snapshot_cursor(snaps[-1])

    def _seed(
        self, transport: SyncTransport, progress: ProgressFn | None = None
    ) -> None:
        """Give an empty authority everything this project holds. Each thing is
        sent as a create with an id made from the project and the thing, so an
        interrupted seed can simply be run again. Something the server refuses
        (a value the field no longer allows, say) is kept for review and does not
        stop the rest: the project is connected once everything else is in.

        The project stays in use meanwhile, so only the changes recorded before
        the first attempt began are counted as sent by it (`begin_seed`): a
        change made after a thing's page went is sent afterwards like any other.
        A run again after an interruption keeps the first attempt's line, since
        the authority answers a thing it was already sent from its record of
        that first sending, not from the thing as it is now."""
        self._repo.begin_seed()
        self._commit()
        meta = self._repo.meta()
        device_id = str(user_state.device_id_for(meta.project_id))
        actor = local_actor(self._config.identity.name)
        head = 0
        report = SyncReport()
        batch: list[SyncEntry] = []
        total = self._repo.entity_count() or None
        sent = 0

        def flush() -> None:
            nonlocal head, batch, sent
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
            if any(r.status == DEFERRED for r in result.results):
                raise SyncError(
                    "The server is still waiting for a file", retryable=True
                )
            # A refusal is kept for review, like any other (the person keeps what
            # they made and can fix it and retry); it doesn't stop the rest.
            self._note(result.results, {e.id: e for e in batch}, report)
            sent += len(batch)
            if progress:
                kind = batch[-1].entity_type
                progress(SyncProgress(FILLING, sent, total and max(total, sent), kind))
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
        if report.rejected:
            log.warning(
                "seeding the server: it refused %d thing(s); they are kept for review",
                report.rejected,
            )
        self._repo.finish_seed()
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
        authority remembers the old one's answer by its id). A change that was
        part of one action (a field renamed with the templates it rewrote) is
        sent again whole, as one new action, and the review items of its other
        parts are settled with it: it can't go in by halves."""
        if self._repo.snapshot(conflict.entity_type, conflict.entity_id) is None:
            raise ValidationError(
                "It no longer exists here, so there is nothing to send"
            )
        original = self._repo.get_entry(conflict.op_id) if conflict.op_id else None
        if original is None:
            raise ValidationError("The change is no longer held here")
        if original.op is None:
            self._resend_entry(original, strict=True, in_action=False)
            return
        parts = self._repo.entries_of_action(original.op)
        with self._audit.operation():
            for entry in parts:
                self._resend_entry(
                    entry, strict=entry.id == original.id, in_action=True
                )
        others = {e.id for e in parts} - {original.id}
        self._repo.resolve_conflicts(
            [
                c.id
                for c in self._repo.find_open_conflicts(kind="rejected")
                if c.op_id in others
            ],
            "retry",
        )

    def _resend_entry(self, original: SyncEntry, strict: bool, in_action: bool) -> None:
        """Log `original` again from its thing as it is now. `strict`: say why
        when it can't be (the part a person chose); a part that went away or
        changed kind since is just left out."""
        current = self._repo.snapshot(original.entity_type, original.entity_id)
        if current is None:
            if strict:
                raise ValidationError(
                    "It no longer exists here, so there is nothing to send"
                )
            return
        if original.action == "delete":
            # A delete is sent again only as a part of an action sent whole
            # (its thing still deleted here); alone, it is a delete to make.
            if current.get("deleted_at") and in_action:
                self._audit.log_change(
                    "delete",
                    original.entity_type,
                    original.entity_id,
                    {**current, "deleted_at": None},
                    None,
                    timestamp=datetime.fromisoformat(current["deleted_at"]),
                )
                return
            if strict:
                raise ValidationError(
                    "Only a created or edited thing can be sent again"
                )
            return
        if original.action not in ("create", "update", "restore"):
            if strict:
                raise ValidationError(
                    "Only a created or edited thing can be sent again"
                )
            return
        start = original.old_data
        if original.delta is not None:
            # Only what the change touched is known of where it started: the
            # thing as it is, with those values as they were before it.
            start = apply_delta(current, original.delta, BEFORE)
        self._audit.log_change(
            original.action,
            original.entity_type,
            original.entity_id,
            start,
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


def _sits_under(kind: str, snap: dict[str, Any]) -> str | None:
    """The id of the thing of the same kind that `snap` can't exist without:
    a record's parent record, a schema's parent schema."""
    key = {"record": "parent_record_id", "schema": "parent_id"}.get(kind)
    return snap.get(key) if key else None


def _field_id(conflict: SyncConflictDTO) -> str | None:
    """The field id a conflict is about (`data.<field id>`), if it is about one."""
    top, _, sub = (conflict.field or "").partition(".")
    return sub if top == "data" and sub else None
