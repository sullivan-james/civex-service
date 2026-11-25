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
import functools
import threading

import time
import urllib.parse
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, BinaryIO, TypeVar

from civex import user_state
from civex.config import (
    COLLECTION_FILE_MODES,
    DOWNLOAD_MODES,
    LIBRARY_MODES,
    Config,
    ConfigStore,
)
from civex.domain import hlc
from civex.domain.audit_diff import (
    AFTER,
    BEFORE,
    PLACEMENT_KEYS,
    apply_delta,
    entry_snapshots,
)
from civex.domain.rates import RateWindow
from civex.domain.exceptions import (
    NotFoundError,
    CivexError,
    ConflictMovedError,
    ValidationError,
    VolumeUnavailableError,
)
from civex.domain.file_refs import without_file_locations
from civex.domain.hosts import is_loopback
from civex.domain.dtos import MissingFileGroupDTO, MissingFilesRemovalDTO
from civex.domain.sync import (
    KEPT_STRUCTURE,
    PUSH_BUDGET_BYTES,
    REFUSAL_PERMISSION,
    UNFIT,
    UNFIT_DATA,
    batch_by_budget,
    is_lock_contention,
    Joined,
    LoginStarted,
    DEFERRED,
    FOLLOWED,
    ENTITY_ORDER,
    NOT_SYNCED_KINDS,
    PROTOCOL_MAX,
    COPYING,
    DeviceCredentials,
    FILLING,
    HISTORY,
    REJECTED,
    SENDING,
    Hello,
    SyncConflictDTO,
    SyncEntry,
    SyncError,
    SyncProgress,
    agree,
    kinds_for,
    plain_failure,
    protocol_mismatch,
    retiring_notice,
    not_on_server_yet,
    SyncTransport,
    snapshot_cursor,
)
from civex.identity import local_actor
from civex.repositories.protocols import (
    AuditRepository,
    ObjectStore,
    SyncRepository,
)
from civex.services.record_service import RecordService
from civex.services.sync_applier import SyncApplier, stamp_of
from civex.services.sync_lock import sync_lock, sync_running
from civex.services import ssh_tunnel

# Changes per push. The authority settles at most 500 in one request
# (`sync_authority.PUSH_MAX`), so a batch never goes over that. Measured on
# PostgreSQL the authority's cost per change grows with the batch, so this
# sits between 100 and that limit.
PUSH_BATCH = 250
# How many flagged records are read, and flags settled, per statement.
FLAG_CHUNK = 500
# How many referenced files are checked against the authority per request.
FILE_CHECK_PAGE = 1000
# A file above this many bytes is sent alone, one at a time, and confirmed and
# committed as soon as it arrives: it never shares memory or bandwidth with
# another upload, and its arrival is never lost to a later failure.
LARGE_FILE_BYTES = 8 * 1024 * 1024
# Smaller files go several at a time (where the transport allows it:
# `upload_threads`), and are confirmed and committed in groups: after this many
# files, or this many seconds, whichever comes first.
SMALL_FILE_GROUP = 50
SMALL_FILE_GROUP_SECONDS = 2.0
# Where the authority takes packs (`file_packs`), small files go many to a
# request: a pack is closed at this many bytes or files, whichever comes
# first, and this many are on their way at once. (Each open file is a handle,
# so the files held at once are at most PACKS_IN_FLIGHT + 1 packs' worth.)
PACK_BYTES = 32 * 1024 * 1024
PACK_FILES = 100
PACKS_IN_FLIGHT = 4
# The slice asked about at a time when sending in packs: a slice is settled
# before the next is read, so a bigger one means fewer pauses for the packs
# still on their way (the authority answers up to 5000 per request).
PACKED_CHECK_PAGE = 4000
FEED_PAGE = 200
# The fewest changes of one kind in a row that a pulled page applies as a set.
RUN_MIN = 3
# The actions that put a record somewhere (a place is checked before they apply).
PLACING = ("create", "update", "restore")
# What a pulled run applies as a set (record changes of these actions).
RUN_ACTIONS = ("delete", "restore", "create", "update")
SNAPSHOT_PAGE = 200

# Stands for "the value on the record now" in an attempt's fields, until it is read.
_NOW: Any = object()

TransportFactory = Callable[[str, DeviceCredentials], SyncTransport]
# The cursor while a copy from the authority is being made (`_join`).
JOINING = -1
# How long a sync waits for another one on this project to finish before it
# gives up with `SyncBusy`; and the pauses before it runs again after the
# database turned out to be busy (see `_with_lock_retries`).
_T = TypeVar("_T")
# A refusal for permission is sent again by itself this many times at most
# (each time is an entry in the history); after that a person decides.
MAX_AUTO_RETRIES = 6
LOCK_WAIT_SECONDS = 10.0
LOCK_RETRY_DELAYS: tuple[float, ...] = (1.0, 3.0, 6.0)
# Told how far a long step (copying, filling, fetching history) has got.
ProgressFn = Callable[[SyncProgress], None]


log = logging.getLogger(__name__)


@dataclass
class SyncReport:
    pulled: int = 0  # changes from others brought in
    pushed: int = 0  # changes of ours the authority settled
    conflicts: int = 0  # values that did not go in as made
    rejected: int = 0  # changes the authority refused
    waiting: int = 0  # changes held back (a refusal waiting for review)
    # Refused changes sent again by themselves this time (they were refused for
    # permission, and the pause since has passed), and how many refused changes
    # still wait for a person at the end (`civex sync resolve --all --take retry
    # --kind rejected` sends them again).
    retried: int = 0
    open_rejected: int = 0
    # The civex the server runs, and what to tell a person when it will stop
    # accepting this one at its next update (`retiring_notice`), as it said.
    server_version: str | None = None
    notice: str | None = None

    @property
    def changed(self) -> bool:
        return bool(self.pulled or self.pushed)


@dataclass
class FileSendReport:
    """What a pass of sending files did (`SyncService.send_files`)."""

    sent: int = 0
    # Files the authority still lacks because this computer cannot read them
    # (a drive that is unplugged, bytes not recovered yet). The changes citing
    # them went long ago; the files follow when they can be read.
    owed: list[str] = field(default_factory=list)
    # Of `owed`, the files this project has never stored on any drive (records
    # came in citing them without their contents), and the collections of the
    # records citing them, as (name, records).
    never_stored: list[str] = field(default_factory=list)
    never_stored_in: list[tuple[str, int]] = field(default_factory=list)
    stopped: bool = False  # ran out of `seconds` with more to send
    # Where a stopped pass got to: the next one starts after it (`after`), so
    # files that can't be sent from here (tried first, in hash order, every
    # pass) don't keep it from reaching the ones that can.
    resume_after: str = ""


@dataclass
class ResolveManyReport:
    """What settling several conflicts at once did."""

    done: int = 0  # settled (or, for a dry run, that would be)
    settled: list[uuid.UUID] = field(default_factory=list)  # which (not a dry run)
    not_offered: int = 0  # left open: this way of settling isn't theirs to take
    failed: list[tuple[uuid.UUID, str]] = field(default_factory=list)  # left open


@dataclass
class CollectionFilesDTO:
    id: str
    name: str
    mode: str  # keep | opened (in force)
    chosen: bool  # set for this collection, rather than the project's setting
    files_here: int
    bytes_here: int
    files_on_server: int  # only on the server: not on any drive here


@dataclass
class FreeUpReport:
    files: int  # copies removed (or that would be)
    bytes: int
    kept_shared: int  # also used by a collection kept here, so kept
    not_on_server: int  # the server hasn't got them yet, so kept


@dataclass
class FileFetchReport:
    attempted: int = 0
    fetched: int = 0
    absent: list[str] = field(default_factory=list)  # the authority lacks them
    stopped: bool = False  # ran out of `limit` or `seconds` with more to do


@dataclass
class RecordSyncState:
    """Where one record stands with the authority (`SyncService.record_sync`).
    `state`: `not_connected` (no authority), `held_here` (this project is the
    authority), `synced`, `pending` (changes not yet sent), `first_upload`
    (set aside by a first upload that has not finished), `refused` (the
    authority would not take a change), `unfit` (taken, but its values break a
    data rule) or `conflict` (a value both sides changed, for a person to
    settle)."""

    state: str
    remote: str | None = None
    pending: int = 0
    seeding: int = 0
    hub_seq: int | None = None
    synced_at: str | None = None
    message: str | None = None  # the authority's reason, for `refused`
    conflict_id: str | None = None
    files: int = 0
    files_waiting: int = 0


@dataclass
class SyncStatus:
    configured: bool
    remote: str | None
    project_id: str
    paused: bool
    pending: int  # changes made here that the authority has not been sent
    # Changes of a first upload (seed) that was interrupted and has yet to be
    # finished: counted apart from `pending` and sent on the next sync.
    seeding: int
    open_conflicts: int
    cursor: int
    last_synced_at: str | None
    last_error: str | None
    last_error_at: str | None
    running: bool  # a sync is in progress right now
    interval_seconds: int = 60
    serving: bool = False  # this project is itself an authority
    download_files: str = "all"
    files_to_fetch: int = 0  # files records here cite that no drive here holds
    # Files records here cite that the authority hasn't said it holds and a
    # drive here has a copy of (readable or not): what goes up.
    files_to_send: int = 0
    # Why those haven't gone (`SyncService.files_waiting`), when there are any.
    files_waiting: FilesWaiting | None = None
    # Missing files a person chose to stop being told about.
    files_ignored: int = 0
    # files records here cite that the server said it hasn't got and no drive
    # here holds (less the ignored): missing everywhere, not downloading
    files_missing: int = 0


@dataclass
class MissingFilesReport:
    """Files records here cite that this project never stored and that nothing
    can supply (no copy on any drive here, and the authority hasn't got it
    either): `shas`, with where records cite them (`groups`), and `ignored`,
    those a person chose to stop hearing about."""

    shas: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    groups: list[MissingFileGroupDTO] = field(default_factory=list)
    # False when a remote is set but couldn't be asked whether it holds them:
    # the list is then only what is missing here.
    server_checked: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "shas": self.shas,
            "ignored": self.ignored,
            "groups": [g.to_dict() for g in self.groups],
            "server_checked": self.server_checked,
        }


@dataclass(frozen=True)
class DeviceIdentity:
    """Who this computer is to the authority of the current project."""

    remote: str | None
    device_id: str | None  # None until joined: asking never makes one
    joined: bool  # this computer holds the authority's key: it was let in
    device_name: (
        str | None
    )  # what the authority calls it; None when unasked/unreachable
    last_error: str | None
    last_error_at: str | None


@dataclass
class FilesWaiting:
    """Why files records here cite aren't on the server: what sending can
    move now, what is on a drive that can't be read (by drive, with its own
    reason), and what is missing: on no drive here, and the server said it
    hasn't got it either, so nothing here can send it (`files_to_send`
    doesn't count those)."""

    ready: int = 0
    offline: list[tuple[str, int, str]] = field(default_factory=list)
    missing: int = 0
    # Of `missing`, those this project never stored (no drive has ever held
    # them), and the collections whose records cite them, as (name, records).
    never_stored: int = 0
    never_stored_in: list[tuple[str, int]] = field(default_factory=list)
    # Missing files a person chose to stop being told about.
    ignored: int = 0


_F = TypeVar("_F", bound=Callable[..., Any])


def _closes_transports(fn: _F) -> _F:
    """A pass that ends, however it ends, closes the connections it opened."""

    @functools.wraps(fn)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        depth = self.__dict__.setdefault("_pass_depth", threading.local())
        depth.n = getattr(depth, "n", 0) + 1
        try:
            return fn(self, *args, **kwargs)
        finally:
            depth.n -= 1
            if depth.n == 0:  # not while an outer pass still uses them
                self._close_transports()

    return wrapper  # type: ignore[return-value]


class SyncService:
    def __init__(
        self,
        config: Config,
        repo: SyncRepository,
        applier: SyncApplier,
        audit: AuditRepository,
        files: ObjectStore,
        commit: Callable[[], None],
        make_transport: TransportFactory,
        records: RecordService,
        config_store: ConfigStore,
    ) -> None:
        self._config = config
        # Whether this pass's last pull reached the authority's head, and
        # whether anything came in, was answered or changed since the flags were
        # last judged (a new service judges once): `_settle_flags`.
        self._at_head = False
        self._flags_stale = True
        # Where `[sync]` is saved (config.toml for a local project); never
        # written to directly, so a hosted project's settings live elsewhere.
        self._config_store = config_store
        self._repo = repo
        self._applier = applier
        self._audit = audit
        self._files = files
        self._commit = commit
        self._make_transport = make_transport
        # What a person does about a conflict is an ordinary edit, made by the
        # record service like any other: validated, in the history, synced.
        self._records = records
        # Whether a pulled page applies runs of like changes as a set; off, every
        # change goes one at a time (what the equivalence tests compare with).
        self._bulk_pull = True

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @property
    def configured(self) -> bool:
        return bool(self._config.sync.remote)

    @_closes_transports
    def identity(self, *, ask: bool = True) -> DeviceIdentity:
        """This computer's standing with the authority. `ask` lets it say its
        name for the device (one request); an authority that can't be reached
        leaves the name `None`."""
        meta = self._repo.meta()
        remote = self._config.sync.remote
        joined = bool(remote and user_state.authority_for(remote))
        name: str | None = None
        if ask and joined and remote:
            try:
                name = self._made(remote).hello().device_name
            except (SyncError, OSError):
                name = None
        return DeviceIdentity(
            remote=remote,
            device_id=(
                str(user_state.device_id_for(meta.project_id)) if joined else None
            ),
            joined=joined,
            device_name=name,
            last_error=meta.last_error,
            last_error_at=meta.last_error_at,
        )

    def status(self) -> SyncStatus:
        meta = self._repo.meta()
        # Files the server hasn't got, and why (asked only when there are any).
        owed = self._repo.count_unconfirmed() if self.fetches_files else 0
        waiting = self.files_waiting() if owed else None
        return SyncStatus(
            configured=self.configured,
            remote=self._config.sync.remote,
            project_id=str(meta.project_id),
            paused=self._config.sync.paused,
            pending=self._repo.count_pending() if self.configured else 0,
            seeding=(
                (self._repo.count_seeding() or int(self._repo.seed_open()))
                if self.configured
                else 0
            ),
            open_conflicts=self._repo.count_conflicts("open"),
            cursor=meta.cursor,
            last_synced_at=meta.last_synced_at,
            last_error=meta.last_error,
            last_error_at=meta.last_error_at,
            running=sync_running(self._config.civex_dir),
            interval_seconds=self._config.sync.interval_seconds,
            serving=self._config.sync.serve,
            download_files=self._config.sync.download_files,
            files_ignored=len(self._repo.ignored_missing()),
            files_to_fetch=self.files_to_fetch(),
            files_missing=self.files_missing(),
            files_to_send=(
                waiting.ready + sum(n for _, n, _ in waiting.offline) if waiting else 0
            ),
            files_waiting=waiting,
        )

    def record_sync(self, record_id: uuid.UUID) -> RecordSyncState:
        """One record's standing with the authority, cheaply: a grouped read
        of its own audit entries, the files it cites, and its open conflicts."""
        if self._config.sync.serve:
            return RecordSyncState("held_here")
        if not self.configured:
            return RecordSyncState("not_connected")
        rows = self._repo.record_sync_rows(record_id)
        states = rows["states"]
        pending = states.get("pending", (0, None, None))[0]
        seeding = states.get("seeding", (0, None, None))[0]
        _, seq, at = states.get("synced", (0, None, None))
        out = RecordSyncState(
            "synced",
            remote=self._config.sync.remote,
            pending=pending,
            seeding=seeding,
            hub_seq=seq,
            synced_at=at.isoformat() if hasattr(at, "isoformat") else at,
            files=rows["files"],
            files_waiting=rows["files_waiting"],
        )
        open_ = self._repo.find_open_conflicts(entity_id=record_id)
        refused = next((c for c in open_ if c.kind == "rejected"), None)
        unfit = next((c for c in open_ if c.kind == UNFIT), None)
        clash = next((c for c in open_ if c.kind not in ("rejected", UNFIT)), None)
        if clash:
            out.state, out.conflict_id = "conflict", str(clash.id)
        elif refused:
            out.state, out.conflict_id = "refused", str(refused.id)
            out.message = refused.message
        elif unfit:
            out.state, out.conflict_id = "unfit", str(unfit.id)
            out.message = unfit.message
        elif pending:
            out.state = "pending"
        elif seeding:
            out.state = "first_upload"
        return out

    def history_position(self) -> tuple[int | None, int]:
        """Where this copy is in the authority's numbered history, and how many
        changes made here it hasn't been sent: the feed's head and 0 when this
        project serves devices (after numbering its own edits); the last number
        applied here and the unsent count when it follows one; (None, 0)
        otherwise. What a release records as the point it was taken at."""
        if self._config.sync.serve:
            self._repo.sequence_local_entries()
            return self._repo.head_seq(), 0
        if self.configured:
            return self._repo.meta().cursor, self._repo.count_pending()
        return None, 0

    def files_waiting(self, limit: int = 5000) -> FilesWaiting:
        """Why files haven't gone to the server, from the inventory and each
        drive's own status (asked once per drive): `limit` files at most are
        looked at, so a project with a great many waiting stays quick."""
        waiting = FilesWaiting()
        status: dict[str, Any] = {}
        offline: dict[str, int] = {}
        copies = self._repo.unconfirmed_copies(limit)
        lacking = self._repo.server_lacks_of({s for s, v in copies.items() if not v})
        for sha, volumes in copies.items():
            if not volumes:
                # Not here: missing once the server said it hasn't got it
                # either, else not asked about yet (nothing to send from here
                # whichever it is).
                waiting.missing += sha in lacking
                continue
            for v in volumes:
                if v not in status:
                    status[v] = self._files.volume_status(v)
            if any(status[v].reachable for v in volumes):
                waiting.ready += 1
            else:
                offline[volumes[0]] = offline.get(volumes[0], 0) + 1
        waiting.offline = [(v, n, status[v].reason) for v, n in sorted(offline.items())]
        ignored = self._repo.ignored_missing()
        absent = {s for s, v in copies.items() if not v and s in lacking}
        waiting.ignored = len(absent & ignored)
        waiting.missing -= waiting.ignored
        if waiting.missing:
            never = self._repo.never_stored(absent - ignored)
            waiting.never_stored = len(never)
            waiting.never_stored_in = self._citing_collections(never)
        return waiting

    # -- files nothing can supply -----------------------------------------

    def _forget_found(self) -> set[str]:
        """The files chosen to be ignored, less any that have since turned up
        here (they are not ignored any more, and go to the server as usual)."""
        ignored = self._repo.ignored_missing()
        found = ignored - self._repo.never_stored(ignored)
        if found:
            self._repo.unignore_missing(found)
            self._commit()
        return ignored - found

    @_closes_transports
    def missing_files(
        self, include_ignored: bool = False, with_groups: bool = True
    ) -> MissingFilesReport:
        """The files live records cite that this project has never stored, that
        no drive here holds, and (with a remote set) that the authority hasn't
        got either: the ones nothing can supply, with where records cite them.
        Never a file that exists anywhere here or on the server. A remote that
        can't be reached leaves `server_checked` false."""
        ignored = self._forget_found()
        candidates: list[str] = []
        after = ""
        while page := self._repo.referenced_shas(after, FILE_CHECK_PAGE):
            after = page[-1]
            candidates.extend(
                s
                for s in self._repo.never_stored(page)
                if self._files.size_of(s) is None
            )
        report = MissingFilesReport()
        if candidates and self.configured and self.fetches_files:
            try:
                transport = self._transport()
                lacking: set[str] = set()
                for at in range(0, len(candidates), FILE_CHECK_PAGE):
                    lacking.update(
                        transport.missing_files(candidates[at : at + FILE_CHECK_PAGE])
                    )
                candidates = [s for s in candidates if s in lacking]
                # Noted, so they are not counted as downloading or asked for
                # again until their wait is over.
                self._repo.note_server_lacks(candidates, backoff=False)
                self._commit()
            except SyncError:
                report.server_checked = False
        report.ignored = sorted(s for s in candidates if s in ignored)
        report.shas = sorted(s for s in candidates if s not in ignored)
        shown = set(candidates) if include_ignored else set(report.shas)
        if shown and with_groups:
            plan = self._records.remove_files(
                shown, [str(r) for r in self._repo.citing_records(shown)], dry_run=True
            )
            for planned in plan:
                report.groups = planned.groups
        return report

    def ignore_missing(self, shas: list[str] | None = None) -> int:
        """Stop warning about these missing files (the references stay), or
        every one listed when `shas` is None. Only files `missing_files` lists
        can be ignored."""
        report = self.missing_files(with_groups=False)
        if not report.server_checked:
            raise SyncError(
                "The server couldn't be asked whether it has these files, so none "
                "was ignored. Try again when it can be reached."
            )
        chosen = set(report.shas) if shas is None else set(shas) & set(report.shas)
        self._repo.ignore_missing(chosen)
        self._commit()
        return len(chosen)

    def ignored_missing(self) -> set[str]:
        return self._repo.ignored_missing()

    def unignore_missing(self, shas: list[str]) -> int:
        n = self._repo.unignore_missing(shas)
        self._commit()
        return n

    def remove_missing(
        self, shas: list[str] | None = None, dry_run: bool = False
    ) -> MissingFilesRemovalDTO:
        """Take missing files out of the records citing them (the field no longer
        points at them), as one batch of ordinary edits: validated, in the
        history, synced, undone whole from Activity. Only files `missing_files`
        lists (never one that exists here or that the authority holds), and
        never when the authority couldn't be asked. A required field that would
        be left empty leaves its record as it is, named in the result. Every
        such file when `shas` is None. Raises `SyncError` when the authority
        can't be asked."""
        report = self.missing_files(include_ignored=True, with_groups=False)
        if not report.server_checked:
            raise SyncError(
                "The server couldn't be asked whether it has these files, so none "
                "was removed. Try again when it can be reached."
            )
        every = set(report.shas) | set(report.ignored)
        chosen = every if shas is None else set(shas) & every
        result = MissingFilesRemovalDTO()
        if not chosen:
            return result
        ids = [str(r) for r in self._repo.citing_records(chosen)]
        for result in self._records.remove_files(chosen, ids, dry_run=dry_run):
            if not dry_run:
                self._commit()
        if not dry_run:
            # Forget the ignoring of files no record cites now; one a record
            # was left citing (a required field) keeps it.
            still = set().union(*self._repo.citing_records(chosen).values())
            self._repo.unignore_missing(chosen - still)
            self._commit()
        return result

    def _citing_collections(self, shas: set[str]) -> list[tuple[str, int]]:
        """The collections whose live records cite these files, as (name,
        records), the most affected first."""
        if not shas:
            return []
        names = self._repo.live_collections()
        counts = self._repo.collections_citing(shas)
        return sorted(
            ((names.get(d, "a removed collection"), n) for d, n in counts.items()),
            key=lambda x: (-x[1], x[0]),
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

    def _sits_under(self, c: SyncConflictDTO) -> list[dict[str, Any]]:
        """For an open refusal of a live record here that sits under deleted
        records: those records, topmost first (the server refuses such a record,
        so they have to come back first). Empty otherwise."""
        if c.kind != "rejected" or c.status != "open" or c.entity_type != "record":
            return []
        try:
            above = self._records.deleted_above(str(c.entity_id))
        except NotFoundError:
            return []
        return [
            {"id": str(a.id), "schema_name": a.schema_name, "name": a.natural_name}
            for a in above
        ]

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
            under = self._sits_under(c)
            if under and "retry" in takes:
                takes.insert(takes.index("retry"), "restore_above")
            v = values.get((str(c.entity_id), _field_id(c) or ""))
            if v is None:
                out.append(replace(c, takes=takes, sits_under=under, **self._named(c)))
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
                    sits_under=under,
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

    def _named(self, c: SyncConflictDTO) -> dict[str, Any]:
        """What a refused schema or field is called, for a person: the schema's
        name, and the field's (as `field_label`)."""
        if c.entity_type not in KEPT_STRUCTURE:
            return {}
        snap = self._repo.snapshot(c.entity_type, c.entity_id) or {}
        if c.entity_type == "schema":
            return {"schema_name": snap.get("name")}
        parent = (
            self._repo.snapshot("schema", uuid.UUID(str(snap["schema_id"])))
            if snap.get("schema_id")
            else None
        )
        return {
            "schema_name": (parent or {}).get("name"),
            "field_label": snap.get("label") or snap.get("name"),
        }

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

    def needs_approval(self, url: str, invite: str | None) -> bool:
        """Whether connecting to `url` must first ask to join: no invite was
        given and this computer has not joined that address before."""
        url = url.strip().rstrip("/")
        return not (invite and invite.strip()) and not user_state.authority_for(url)

    @_closes_transports
    def request_login(self, url: str) -> LoginStarted:
        """Ask the authority at `url` to let this computer join without an
        invite. The answer's `user_code` is for a person to approve there;
        `connect(url, None, login=...)` then waits for that and joins."""
        url = url.strip().rstrip("/")
        self._refuse_following_while_serving()
        _check_address(url)
        return self._made(url).request_login()

    @_closes_transports
    def check_connect(self, url: str, invite: str | None) -> str:
        """What connecting to this authority would do, found out without doing
        it: the address is read, the protocol accepted, and who holds data
        decided. Quick, so a mistake is said at once even when the copying
        itself then runs in the background. Returns the mode `connect` would.

        Given an invite, this computer joins the authority here (the invite is
        used up), so connecting afterwards needs none; without one, it must
        have joined that address before (connecting again after a copy stopped
        part way). The one rule both the app and the CLI connect through."""
        return self._plan_connect(url, invite)[0]

    def _credentials(self, url: str) -> DeviceCredentials:
        project = self._repo.meta().project_id
        return DeviceCredentials(
            device_id=str(user_state.device_id_for(project)),
            private_key=user_state.device_key_for(project),
            authority_key=user_state.authority_for(url),
        )

    def _plan_connect(
        self,
        url: str,
        invite: str | None,
        login: LoginStarted | None = None,
        on_code: Callable[[LoginStarted], None] | None = None,
    ) -> tuple[str, Hello, str]:
        url = url.strip().rstrip("/")
        self._refuse_following_while_serving()
        _check_address(url)
        probe = self._made(url)
        if invite and invite.strip():
            joined = probe.join(invite.strip())
            user_state.save_authority(url, joined.authority_key)
        elif not self._is_a_device(probe, url):
            # Never joined and no invite: ask to join, show the code (or take a
            # request already made), and wait for a person to approve it.
            if login is None and on_code is None:
                raise SyncError(
                    "This computer hasn't joined that server: ask its admin for an "
                    "invite, or connect in a way that can wait to be approved",
                    retryable=False,
                )
            if login is None:
                login = probe.request_login()
                assert on_code is not None
                on_code(login)
            joined = self._await_approval(probe, login)
            user_state.save_authority(url, joined.authority_key)
        hello = probe.hello()
        self._check_protocol(hello)
        meta = self._repo.meta()

        local_empty = self._repo.entity_count() == 0
        mine = str(user_state.device_id_for(meta.project_id))
        if hello.project_id == meta.project_id:
            # Connected before. A first push that never finished leaves the
            # cursor at zero with this device named as the one that began it;
            # a copy that never finished leaves it at JOINING (or nothing here).
            # (A pull that moved the cursor on does not hide it: entries
            # still `seeding` mean the first upload is not done.)
            unfinished = hello.seeded_by == mine and (
                meta.cursor == 0
                or self._repo.count_seeding() > 0
                or self._repo.seed_open()
            )
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

    def _is_a_device(self, probe: SyncTransport, url: str) -> bool:
        """Whether the authority at `url` knows THIS device. Asked, not
        guessed: this computer may have joined that address for another project
        (each project is its own device), or this device may have been revoked.
        Only a refusal that says so (`not_a_device`) means sign in again; any
        other (a bad signature, a clock) keeps its own message."""
        if not user_state.authority_for(url):
            return False
        try:
            probe.hello()  # signs in
        except SyncError as e:
            if e.code == "not_a_device":
                return False
            raise
        return True

    def _await_approval(self, probe: SyncTransport, login: LoginStarted) -> Joined:
        """Poll until a person approves the request, it is denied, or it
        expires (the authority answers the last two with a refusal)."""
        while True:
            joined = probe.poll_login(login.device_code)
            if joined is not None:
                return joined
            if time.time() >= login.expires_at:
                raise SyncError(
                    "Nobody approved this computer before the code expired. Ask again.",
                    retryable=False,
                )
            self._sleep(login.interval)

    # How waiting is done; a test makes it instant.
    _sleep: Callable[[float], None] = staticmethod(time.sleep)

    @_closes_transports
    def connect(
        self,
        url: str,
        invite: str | None,
        progress: ProgressFn | None = None,
        login: LoginStarted | None = None,
        on_code: Callable[[LoginStarted], None] | None = None,
    ) -> str:
        """Point this project at an authority. What happens depends on who holds
        data: an empty project **joins** one that has some (it becomes a copy), an
        empty authority is **seeded** from a project that has some, and when both
        are empty they simply agree on a project id. Both holding data is refused:
        merging two histories needs a person to say which names are the same
        things, and that is not offered yet. Returns `joined`, `seeded`, `empty` or
        `resumed`.

        `progress` hears how far copying has got. A joined project is usable
        once it returns; the history from before it joined is fetched after
        (`fetch_history`), by whatever runs sync next.

        Without an invite, a computer that never joined asks to: `on_code` is
        told the code a person must approve on the authority (and this waits
        until they do), or `login` is a request already made, to wait on."""
        mode, hello, url = self._plan_connect(url, invite, login, on_code)
        meta = self._repo.meta()

        # The project takes the authority's id; the device keeps its identity.
        if hello.project_id != meta.project_id:
            self._repo.set_project_id(hello.project_id)
            user_state.move_device(meta.project_id, hello.project_id)
            # Where this project had got to, what it was waiting to have
            # reviewed, and the numbers its history was given, were all the
            # authority it followed before: kept, they would be read as this
            # one's (the same number means another change here).
            self._repo.set_cursor(0)
            self._repo.forget_numbers()
            self._repo.resolve_conflicts(
                [c.id for c in self._repo.find_open_conflicts()],
                FOLLOWED,
            )
            self._commit()
        self._config.sync.remote = url
        self._config_store.save(self._config)

        with sync_lock(self._config.civex_dir):
            try:
                transport = self._transport()
                if mode == "joined":
                    self._join(transport, hello, progress)
                elif mode == "seeded":
                    # After a pull, not what the authority already has.
                    skip = (
                        self._repo.already_sent_entities()
                        if self._repo.meta().cursor != 0 and not hello.empty
                        else None
                    )
                    extra: dict[str, Any] = {"skip": skip} if skip else {}
                    self._seed(
                        transport,
                        progress,
                        hello.protocol_version,
                        **extra,
                    )
                else:
                    self._repo.set_cursor(
                        hello.head_seq if mode == "empty" else self._repo.meta().cursor
                    )
                    self._repo.mark_all_synced() if mode == "empty" else None
                    self._commit()
            except Exception as raw:
                # Say why it stopped (the next sync finishes a seed from where
                # it got to), instead of leaving no trace.
                self._record_failure(raw)
                raise
            self._repo.record_outcome(None)
            self._commit()
        return mode

    def _record_failure(self, raw: Exception) -> None:
        try:
            if is_lock_contention(raw):
                self._repo.rollback()
            else:
                self._commit_quietly()
            self._repo.record_outcome(str(plain_failure(raw)))
            self._commit()
        except Exception:  # noqa: BLE001 - the original error is what matters
            self._repo.rollback()

    def disconnect(self) -> None:
        remote = self._config.sync.remote
        self._config.sync.remote = None
        self._config_store.save(self._config)
        if remote:
            user_state.forget_authority(remote)

    def set_serving(self, on: bool) -> None:
        """Whether this project accepts devices (is an authority for them). The
        devices it knows stay on record either way. A project following an
        authority can't be one (`_one_role`)."""
        remote = self._config.sync.remote
        if on and remote and not self._config.sync.serve:
            raise ValidationError(
                f"This project follows {remote}, so it can't be a server for other "
                f"devices too: they can follow {remote} instead. To make this "
                "project the server, disconnect it first."
            )
        self._config.sync.serve = on
        self._config_store.save(self._config)

    @property
    def library_mode(self) -> str:
        return self._config.sync.library

    def set_library(self, mode: str) -> None:
        """What devices may publish to this authority's library: nothing,
        workflows, or plugins too (`LIBRARY_MODES`)."""
        if mode not in LIBRARY_MODES:
            raise ValidationError(
                f"The library takes one of: {', '.join(LIBRARY_MODES)}"
            )
        self._config.sync.library = mode
        self._config_store.save(self._config)

    def set_paused(self, paused: bool) -> None:
        self._config.sync.paused = paused
        self._config_store.save(self._config)

    def set_interval(self, seconds: int) -> None:
        if seconds != 0 and seconds < 5:
            raise ValidationError(
                "The interval must be at least 5 seconds, or 0 to sync only when asked"
            )
        self._config.sync.interval_seconds = seconds
        self._config_store.save(self._config)

    def _one_role(self) -> str | None:
        """Why this project can't sync as it is set up, when it both serves
        devices and follows an authority: the star has one authority, so such a
        project's records would go up while its files (which only a follower
        sends) never did, and what its own devices change would reach nobody
        else. None when it is one or the other. The one rule; connecting,
        serving and every sync ask it."""
        remote = self._config.sync.remote
        if not (remote and self._config.sync.serve):
            return None
        return (
            f"This project follows {remote} and is also a server for other "
            "devices: it can be one or the other. To keep following "
            f"{remote}, stop it serving (Settings → Sync, or `civex sync "
            "authority disable`) and connect its devices to "
            f"{remote} instead; to keep it a server, disconnect it."
        )

    def _refuse_following_while_serving(self) -> None:
        if self._config.sync.serve:
            raise SyncError(
                "This project is a server other devices follow, so it can't "
                "follow another server too. Stop it serving first (Settings → "
                "Sync, or `civex sync authority disable`); its devices can then "
                "connect to the new server.",
                retryable=False,
            )

    def _check_protocol(self, hello: Hello) -> None:
        theirs = (hello.protocol_min, hello.protocol_max)
        if agree(theirs) is None:
            raise SyncError(
                protocol_mismatch(
                    theirs, "the server", "this computer", hello.server_version
                ),
                retryable=False,
            )

    def transport(self) -> SyncTransport:
        """A connection to the authority this project follows, signed in as
        this device (for the library, which is not part of syncing)."""
        transport = self._transport()
        # The caller's to close: not closed when a pass of ours ends.
        self._opened().remove(transport)
        return transport

    def _made(self, url: str) -> SyncTransport:
        """A transport for `url` that the pass in hand closes when it ends."""
        transport = self._make_transport(url, self._credentials(url))
        self._opened().append(transport)
        return transport

    def _transport(self) -> SyncTransport:
        remote = self._config.sync.remote
        if not remote:
            raise SyncError(
                "No server is set: connect to one first.",
                retryable=False,
            )
        _check_address(remote)
        if not user_state.authority_for(remote):
            raise SyncError(
                f"This computer hasn't joined {remote}: connect again with an invite.",
                retryable=False,
            )
        return self._made(remote)

    def _opened(self) -> list[Any]:
        """The transports this thread has made since it last closed them."""
        local = self.__dict__.setdefault("_transports", threading.local())
        if not hasattr(local, "list"):
            local.list = []
        return local.list  # type: ignore[no-any-return]

    def _close_transports(self) -> None:
        """Close the connections of every transport this thread opened: a pass
        leaves no socket behind."""
        opened, self._opened()[:] = list(self._opened()), []
        for transport in opened:
            close = getattr(transport, "close", None)
            if close is not None:
                close()

    # ------------------------------------------------------------------
    # Syncing
    # ------------------------------------------------------------------

    _sync_progress: ProgressFn | None = None
    # Where a background run hears of a first upload being finished.
    on_progress: ProgressFn | None = None

    def sync(self, progress: ProgressFn | None = None) -> SyncReport:
        """Pull, push, pull: the project's data only. Files go separately and
        afterwards (`send_files`, `fetch_files`), so a large upload never holds
        up a change. Raises `SyncBusy` when another sync is running and
        `SyncError` when the authority can't be reached or refuses this device
        (`retryable` says whether trying later can help)."""
        self._sync_progress = progress or self.on_progress
        with sync_lock(self._config.civex_dir, wait=LOCK_WAIT_SECONDS):
            log.info("sync with %s: starting", self._config.sync.remote)
            try:
                report = self._with_lock_retries(self._sync)
            except Exception as raw:
                e = plain_failure(raw)
                log.warning(
                    "sync with %s failed (%s): %s%s",
                    self._config.sync.remote,
                    "will retry" if e.retryable else "will not retry until fixed",
                    e,
                    f" [{e.detail}]" if e.detail else "",
                    exc_info=e is not raw,
                )
                if is_lock_contention(raw):
                    self._repo.rollback()
                else:
                    self._commit_quietly()
                try:
                    self._repo.record_outcome(str(e))
                    self._commit()
                except Exception as again:  # noqa: BLE001
                    if not is_lock_contention(again):
                        raise
                    # The database is busy even for saying so: the message is
                    # already in the log and in what is raised.
                    self._repo.rollback()
                if e is raw:
                    raise
                raise e from raw
            log.info(
                "sync with %s: received %d, sent %d, conflicts %d, refused %d, "
                "waiting %d",
                self._config.sync.remote,
                report.pulled,
                report.pushed,
                report.conflicts,
                report.rejected,
                report.waiting,
            )
            self._repo.record_outcome(None)
            self._commit()
            return report

    def _with_lock_retries(self, work: Callable[[], _T]) -> _T:
        """Run `work`; when the database is only busy (another process holds
        its write lock past the busy timeout, or a read that turned into a
        write lost a race and SQLite refuses at once) drop what the failed
        attempt had not committed and run it again a few times. Every step of a
        sync resumes from what was committed, so running it again is safe."""
        for delay in (*LOCK_RETRY_DELAYS, None):
            try:
                return work()
            except Exception as e:
                if delay is None or not is_lock_contention(e):
                    raise
                log.info(
                    "sync with %s: the database is busy (another civex process is "
                    "using this project); trying again in %.1fs",
                    self._config.sync.remote,
                    delay,
                )
                self._repo.rollback()
                time.sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    def _commit_quietly(self) -> None:
        try:
            self._commit()
        except Exception:  # noqa: BLE001 - nothing to save; the error matters more
            pass

    @_closes_transports
    def _sync(self) -> SyncReport:
        progress = self._sync_progress
        self._at_head = False
        if problem := self._one_role():
            raise SyncError(problem, retryable=False)
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
        report = SyncReport(
            server_version=hello.server_version,
            notice=retiring_notice(hello.protocol_retiring, hello.protocol_version),
        )
        if hello.head_seq < meta.cursor:
            # Not an error, but "sent 0" would hide that it is not the server
            # this copy followed (a pull only asks for what follows the cursor).
            where = (
                f"The server is at change {hello.head_seq} but this copy had "
                f"followed it to {meta.cursor}: it may be a different server, or "
                "one restored from a backup."
            )
            log.warning("sync with %s: %s", self._config.sync.remote, where)
            report.notice = " ".join(filter(None, [report.notice, where]))
        # A first upload that never finished (the process stopped, or the
        # connection dropped) goes first, whatever the cursor says: a pull
        # would only bring back what of it had gone, and the rest would stay
        # `seeding`, sent by nothing. It is safe to run again (see `_seed`).
        # (`seed_open` says so even when the seed set nothing aside: a history
        # all settled with another authority has nothing to set aside.)
        if self._repo.count_seeding() or self._repo.seed_open():
            mine = str(user_state.device_id_for(meta.project_id))
            if hello.seeded_by == mine or (hello.seeded_by is None and hello.empty):
                log.info(
                    "sync with %s: finishing the first upload",
                    self._config.sync.remote,
                )
                # The whole project goes again, as a first upload does (what
                # the authority already holds it answers from its record),
                # except what it already numbered a change of. The cursor
                # stays: the pull below brings in whatever others did.
                restarted = hello.empty
                if restarted:
                    # An empty server holds none of what was numbered before
                    # (reset, or restored from before the upload): all goes
                    # again, and it is followed from the start.
                    self._repo.forget_numbers()
                    self._repo.set_cursor(0)
                    self._commit()
                self._seed(
                    transport,
                    progress,
                    hello.protocol_version,
                    advance=restarted,
                    skip=None if restarted else self._repo.already_sent_entities(),
                )
                meta = self._repo.meta()
            else:
                # Not this copy's upload to finish (another began or finished
                # it: its ids would be answered with the other's results, and
                # these changes would be marked sent without being seen). This
                # copy's own are sent under ids of its own, so the authority
                # judges them like any other change and a clash is kept for
                # review. (A device id lost on this computer lands here too: a
                # clash is recoverable, a silent loss is not.)
                log.info(
                    "sync with %s: the first upload was not begun by this copy; "
                    "its changes are sent as ordinary ones",
                    self._config.sync.remote,
                )
                self._seed(
                    transport,
                    progress,
                    hello.protocol_version,
                    advance=False,
                    skip=self._repo.already_sent_entities(),
                    salt=str(user_state.device_id_for(meta.project_id)),
                )
                meta = self._repo.meta()
        if meta.cursor < hello.feed_floor:
            self._copy_again(transport, hello, report)
        self._catch_up_readable(transport, hello)
        report.pulled += self._pull(transport)
        report.pushed += self._push(transport, report)
        report.retried = self._resend_permission_refusals()
        if report.retried:
            report.pushed += self._push(transport, report)
        if report.pushed or report.conflicts:
            report.pulled += self._pull(transport)
        report.open_rejected = len(self._repo.find_open_conflicts(kind="rejected"))
        self._settle_flags()
        return report

    def _resend_permission_refusals(self) -> int:
        """Send again the open refusals the authority made for permission, once
        their pause has passed (`_retry_pause`): the device may have been given
        the permission since, and a change that is still forbidden is only asked
        again with growing gaps, up to once a day. A refusal for anything else
        (a value that breaks a rule) would only fail again, so a person decides.
        Returns how many were sent."""
        now = datetime.now(timezone.utc)
        sent = 0
        for listed in self._repo.find_open_conflicts(kind="rejected"):
            # Read again: sending one part of an action again settled the others'
            # items as "retrying" since the list was made, and sending the action
            # a second time would duplicate it.
            c = self._repo.get_conflict(listed.id)
            if (
                c is None
                or c.status != "open"
                or c.code != REFUSAL_PERMISSION
                or c.resolution == "retrying"
            ):
                continue
            # The later of the last automatic try and the latest refusal (a
            # refusal renewed after a person's own retry starts its pause again).
            since = max(
                datetime.fromisoformat(t) for t in (c.retried_at, c.created_at) if t
            )
            if c.retries >= MAX_AUTO_RETRIES or now - since < _retry_pause(c.retries):
                continue
            self._repo.note_auto_retry(c.id)
            try:
                self.resolve_conflict(c.id, "retry")
                sent += 1
            except CivexError as e:  # noqa: BLE001 - left for a person
                log.info("refused change %s not sent again: %s", c.id, e)
            self._commit()
        return sent

    @_closes_transports
    def pull(self) -> int:
        with sync_lock(self._config.civex_dir):
            return self._pull(self._transport())

    # -- pull -------------------------------------------------------------

    def _pull(self, transport: SyncTransport) -> int:
        self._at_head = False
        dirty = self._catch_up()
        cursor = self._repo.meta().cursor
        applied = 0
        # An action cut across pages is kept on disk as it arrives (state
        # `arriving`, or `arrhold` once any entry of it must wait), and the
        # cursor goes past it: nothing is held in memory, and a stop picks up
        # where it was. Its fate (applied whole, or held whole) is decided when
        # its last entry has arrived.
        arriving, to_hold = self._repo.arriving_action()
        start = cursor  # what was staged before this pass is at or below it
        while True:
            page = transport.feed(cursor, FEED_PAGE)
            entries = list(page.entries)
            # The trailing run of one action, when the page may end inside it.
            tail = len(entries)
            if page.more and entries and entries[-1].op:
                while tail > 0 and entries[tail - 1].op == entries[-1].op:
                    tail -= 1
            if page.more and not entries and not (page.through or 0) > cursor:
                return applied  # no progress: asking again would repeat itself
            # An action is taken whole or held whole: if one of its entries
            # must wait for a push of this device's own, every entry of it
            # waits with that one (a tree moved to another collection can't
            # be half moved: a child's collection is its parent's).
            above = self._above_dirty(dirty)
            if self._bulk_pull:
                waited = [
                    e
                    for i, e in enumerate(entries)
                    if e.op and i < tail and e.op != arriving
                ]
                waiting = {
                    e.op
                    for e, w in zip(
                        waited, self._waits_many(waited, dirty, above), strict=True
                    )
                    if w
                }
                ids = [e.id for e in entries]
                # (A page that repeats an entry is left to the one-at-a-time path.)
                owned: set[uuid.UUID] | None = (
                    self._repo.existing_entry_ids(ids)
                    if len(set(ids)) == len(ids)
                    else None
                )
            else:
                waiting = {
                    e.op
                    for i, e in enumerate(entries)
                    if e.op
                    and i < tail
                    and e.op != arriving
                    and self._waits(e, dirty, above)
                }
                owned = None
            skip = 0  # the entries before this one were applied as a run
            no_run = 0  # a run that failed: its entries go one at a time
            touched: list[uuid.UUID] = []
            settled = False
            try:
                with self._repo.savepoint():
                    for i, entry in enumerate(entries):
                        if i < skip:
                            continue
                        if entry.hub_seq is None:
                            raise SyncError("The server sent a change without a number")
                        if arriving is not None and entry.op != arriving:
                            self._settle_arriving(arriving, to_hold, dirty, start)
                            arriving, to_hold = None, False
                            settled = True
                        if (
                            owned is not None
                            and arriving is None
                            and i >= no_run
                            and entry.entity_type == "record"
                            and entry.action in RUN_ACTIONS
                        ):
                            taken, tried = self._run(
                                entries, i, tail, dirty, above, waiting, owned
                            )
                            if taken:
                                applied += len(taken)
                                touched.extend(e.entity_id for e in taken)
                                skip = i + len(taken)
                                cursor = taken[-1].hub_seq or cursor
                                continue
                            no_run = i + tried
                        if entry.entity_type in NOT_SYNCED_KINDS:
                            # An authority on protocol 5 or older still feeds
                            # releases: they are never taken (published on a
                            # host), only read past.
                            pass
                        elif self._repo.has_entry(entry.id):
                            # Ours, now numbered, and stamped with the device
                            # it came through.
                            self._repo.mark_seq(entry.id, entry.hub_seq, entry.device)
                        elif entry.op and (entry.op == arriving or i >= tail):
                            arriving = entry.op
                            to_hold = self._stage(entry, dirty, above, to_hold)
                            applied += 1
                        else:
                            self._take(
                                entry,
                                dirty,
                                hold=entry.op in waiting
                                or self._waits(entry, dirty, above),
                            )
                            applied += 1
                            if entry.entity_type == "record":
                                touched.append(entry.entity_id)
                        cursor = entry.hub_seq
                    if entries:
                        self._flags_stale = True  # (something came in)
                    if arriving is not None and not page.more:
                        self._settle_arriving(arriving, to_hold, dirty, start)
                        arriving, to_hold = None, False
                        settled = True
                    # The server may have looked past changes it did not send
                    # (ones this device may not see): the cursor goes where it
                    # got to, or they would be read again at every sync.
                    if page.through is not None and page.through > cursor:
                        cursor = page.through
                    # A collection that came in the feed is one this device
                    # holds: it is not read again when the next hello lists it.
                    born = {
                        str(e.entity_id)
                        for e in entries
                        if e.entity_type == "dataset" and e.action == "create"
                    }
                    known = self._repo.readable() if born else None
                    if known is not None:
                        self._repo.set_readable(known | born)
                    self._repo.set_cursor(cursor)
                    # What this page settled may have freed a held change (a
                    # parent's move held while a child's change was unsent,
                    # the child now settled by this page): it goes in with the
                    # page, in the same transaction, since a child in another
                    # collection than its parent is refused at commit.
                    if touched or settled:
                        self._replay_held(dirty)
                    if (
                        not page.more
                        and touched
                        and self._records.placement_mismatches(touched)
                    ):
                        raise _NotYet()
            except _NotYet:
                raise SyncError(
                    "The changes from the server left a record in another "
                    "collection than the record above it"
                ) from None
            # A page may end between a parent's move and its child's: the
            # next page settles it, and both are committed together.
            if page.more and touched and self._records.placement_mismatches(touched):
                continue
            self._commit()
            if not page.more:
                self._at_head = True
                return applied

    def _stage(
        self,
        entry: SyncEntry,
        dirty: set[tuple[str, uuid.UUID]],
        above: set[uuid.UUID],
        to_hold: bool,
    ) -> bool:
        """Keep an entry of an action that is still arriving, on disk and not
        applied. The first entry that must wait for a push of this device's
        own turns the whole action (what has arrived, and what will) to
        `arrhold`. Answers whether the action is to be held."""
        assert entry.op
        if not to_hold and not entry.superseded and self._waits(entry, dirty, above):
            self._repo.set_arriving(entry.op, ("arriving",), "arrhold")
            to_hold = True
        state = (
            "superseded" if entry.superseded else "arrhold" if to_hold else "arriving"
        )
        self._repo.insert_entry(entry, hub_seq=entry.hub_seq, apply_state=state)
        return to_hold

    def _arriving_waits(
        self, op: str, dirty: set[tuple[str, uuid.UUID]], start: int
    ) -> bool:
        """Whether an entry of an arriving action that an earlier pass kept (up
        to number `start`) must wait for a push of this device's own *now*: the
        person may have edited since, and a pass pulls before it pushes.
        (What this pass staged was checked as it came in.)"""
        above = self._above_dirty(dirty)
        after = 0
        while chunk := self._repo.arriving_entries(op, after, 500, upto=start):
            if any(self._waits(e, dirty, above) for e in chunk if not e.superseded):
                return True
            after = chunk[-1].hub_seq or after
        return False

    def _settle_arriving(
        self,
        op: str,
        to_hold: bool,
        dirty: set[tuple[str, uuid.UUID]],
        start: int,
    ) -> None:
        """An action's last entry has arrived: hold it whole (it stays in the
        held store, `_replay_held` applies it once nothing of this device's own
        keeps it waiting) or apply it whole, a chunk of entries at a time from
        disk. One transaction: a child in another collection than its parent is
        refused at commit, so it can't be applied in steps that commit."""
        if to_hold:
            self._repo.set_arriving(op, ("arrhold",), "held")
            return
        if self._arriving_waits(op, dirty, start):
            self._repo.set_arriving(op, ("arriving",), "held")
            return
        try:
            with self._repo.savepoint():
                # `settling`: now steps, which `arriving` rows are not.
                self._repo.set_arriving(op, ("arriving",), "settling")
                after = 0
                while chunk := self._repo.arriving_entries(
                    op, after, 500, state="settling"
                ):
                    self._apply_chunk(chunk)
                    after = chunk[-1].hub_seq or after
                after = 0
                while chunk := self._repo.arriving_entries(
                    op, after, 500, state="settling"
                ):
                    ids = [e.entity_id for e in chunk if e.entity_type == "record"]
                    if ids and self._records.placement_mismatches(ids):
                        raise _NotYet()
                    after = chunk[-1].hub_seq or after
                self._repo.set_arriving(op, ("settling",), "applied")
        except _NotYet:
            self._repo.set_arriving(op, ("arriving",), "held")

    def _apply_chunk(self, chunk: list[SyncEntry]) -> None:
        """Apply a chunk of an action's entries under one savepoint (a savepoint
        for each entry would pile up thousands in one transaction). If one of
        them can't be applied, the chunk is undone and done again an entry at a
        time, each with its own savepoint and its refusal recorded as a
        conflict: the action stays whole either way."""
        try:
            with self._repo.savepoint():
                for e in chunk:
                    self._replay(
                        (e.entity_type, e.entity_id), e.hub_seq or 0, isolate=False
                    )
        except ValidationError:
            for e in chunk:
                self._replay((e.entity_type, e.entity_id), e.hub_seq or 0)

    def _above_dirty(self, dirty: set[tuple[str, uuid.UUID]]) -> set[uuid.UUID]:
        """Every record here that an unsent change is to or beneath: those
        records, and the ones above them."""
        ids = [eid for kind, eid in dirty if kind == "record"]
        return set(ids) | self._tree(ids)

    def _tree(self, ids: list[uuid.UUID]) -> set[uuid.UUID]:
        """The records above these, here (deleted ones too)."""
        if not ids:
            return set()
        trails = self._records.ancestor_trails(
            self._records.labels([str(i) for i in ids])
        )
        return {above.id for trail in trails.values() for above in trail}

    def _places(self, entry: SyncEntry) -> tuple[uuid.UUID, uuid.UUID | None] | None:
        """The record and the parent it would sit under, when applying `entry`
        puts a record somewhere: a new record, or one moved to another
        collection or under another record. None for anything else."""
        if entry.entity_type != "record" or entry.action not in PLACING:
            return None
        return self._placed(entry, self._repo.snapshot("record", entry.entity_id))

    @staticmethod
    def _placed(
        entry: SyncEntry, current: dict[str, Any] | None
    ) -> tuple[uuid.UUID, uuid.UUID | None] | None:
        """`_places`, given the record as it is here now (None: not here)."""
        if entry.delta is not None and current is not None:
            state = apply_delta(current, entry.delta, AFTER)
        else:
            state = entry.new_data or {}
        parent = state.get("parent_record_id")
        try:
            parent_id = uuid.UUID(str(parent)) if parent else None
        except ValueError:
            parent_id = None
        if current is None:
            return entry.entity_id, parent_id
        if any(
            str(state.get(key) or "") != str(current.get(key) or "")
            for key in PLACEMENT_KEYS
        ):
            return entry.entity_id, parent_id
        return None

    def _waits_many(
        self,
        entries: list[SyncEntry],
        dirty: set[tuple[str, uuid.UUID]],
        above: set[uuid.UUID],
    ) -> list[bool]:
        """`_waits` of each of these, as the records are now, with the reads
        done once for all: the records' current state in one query, and the
        records above every one that places a record in one trail lookup."""
        found = [(e.entity_type, e.entity_id) in dirty for e in entries]
        if not above:
            # Nothing unsent is at or beneath any record: placing one can't
            # wait (only an unsent change to the thing itself does).
            return found
        placing = [
            k
            for k, e in enumerate(entries)
            if not found[k] and e.entity_type == "record" and e.action in PLACING
        ]
        if not placing:
            return found
        _, current = self._repo.record_rows([entries[k].entity_id for k in placing])
        where = {
            k: self._placed(entries[k], current.get(entries[k].entity_id))
            for k in placing
        }
        trails = self._trails([i for p in where.values() if p for i in p if i])
        for k, placed in where.items():
            if placed is not None:
                found[k] = _waits_on(placed, above, trails)
        return found

    def _trails(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, set[uuid.UUID]]:
        """The ids of the records above each of these (the ones here; deleted
        ones too), from one lookup of the trails."""
        if not ids:
            return {}
        trails = self._records.ancestor_trails(
            self._records.labels([str(i) for i in dict.fromkeys(ids)])
        )
        return {rid: {a.id for a in trail} for rid, trail in trails.items()}

    def _run(
        self,
        entries: list[SyncEntry],
        start: int,
        tail: int,
        dirty: set[tuple[str, uuid.UUID]],
        above: set[uuid.UUID],
        waiting: set[str | None],
        owned: set[uuid.UUID],
    ) -> tuple[list[SyncEntry], int]:
        """Apply the run of changes from `start` that are of one kind (deletes,
        restores, makes or edits of records) as a set, if they are plain: what
        `_take` does for each of them, with the reads and writes done once for
        the run. Answers the entries it took (none: the first goes the ordinary
        way) and how many it looked at.

        A run ends before a change that is anything but plain: one already here
        (ours, numbered now), to a record already in the run, to a thing with an
        unsent change, held, superseded, of an action still arriving, one that
        moves a record or sits under another of the run, or one the record is
        later changed by (this device's own, numbered after it). Those go one at
        a time, in their place, after the run. Any doubt (a write the database
        refuses, a change that can't be read) undoes the run and does the same."""
        kind = entries[start].action
        run: list[SyncEntry] = []
        seen: set[uuid.UUID] = set()
        odd = 0
        for j in range(start, len(entries)):
            e = entries[j]
            if e.entity_type != "record" or e.action != kind:
                break  # (the next kind of change starts a run of its own)
            if e.entity_id in seen:
                break  # (a repeat: it may begin the next run)
            if (
                e.hub_seq is None
                or e.superseded
                or e.id in owned
                or ("record", e.entity_id) in dirty
                or (e.op and (j >= tail or e.op in waiting))
            ):
                # not plain: it goes by itself, after the run (and cannot begin
                # one, so a run too short skips it too)
                odd = 1
                break
            seen.add(e.entity_id)
            run.append(e)
        if len(run) < RUN_MIN:
            return [], len(run) + odd
        try:
            # (Reads and writes alike under one savepoint: a database error in
            # either must leave the transaction usable for the one at a time way.)
            with self._repo.savepoint():
                # A run that stops early must not cost a read of all of it, again
                # for each change after it: look at its start first, in growing
                # steps, and stop at the first that is cut.
                size = RUN_MIN
                while size * 2 < len(run):
                    head = self._plain(kind, run[:size], above, {}, [])
                    if len(head) < size:
                        return [], len(head) + 1
                    size *= 4
                rows: dict[uuid.UUID, Any] = {}
                states: list[tuple[uuid.UUID, dict[str, Any]]] = []
                plain = self._plain(kind, run, above, rows, states)
                if len(plain) < RUN_MIN:
                    return [], len(plain) + 1
                run = plain
                self._repo.insert_pulled_entries(run)
                if kind == "delete":
                    self._repo.soft_delete_records(
                        [(e.entity_id, stamp_of(e)) for e in run]
                    )
                else:
                    self._repo.apply_record_states(rows, states)
                if self.fetches_files:
                    self._repo.forget_records_lacks([e.entity_id for e in run])
        except Exception:  # noqa: BLE001 - the one at a time way says what is wrong
            log.warning("pull: a run was not applied as a set", exc_info=True)
            return [], max(len(run), 1)
        return run, len(run)

    def _plain(
        self,
        kind: str,
        run: list[SyncEntry],
        above: set[uuid.UUID],
        rows: dict[uuid.UUID, Any],
        states: list[tuple[uuid.UUID, dict[str, Any]]],
    ) -> list[SyncEntry]:
        """The start of `run` that is plain to apply as a set: up to the first
        change the record is later changed by (this device's own, numbered after
        it), and for makes, edits and restores the first that is not plain
        (`_run_states`, which fills `rows` and `states`)."""
        later = self._repo.record_entries_after(
            {e.entity_id: e.hub_seq or 0 for e in run}
        )
        for k, e in enumerate(run):
            if e.entity_id in later:
                run = run[:k]
                break
        if kind != "delete" and len(run) >= RUN_MIN:
            run = self._run_states(run, above, rows, states)
        return run

    def _run_states(
        self,
        run: list[SyncEntry],
        above: set[uuid.UUID],
        rows: dict[uuid.UUID, Any],
        states: list[tuple[uuid.UUID, dict[str, Any]]],
    ) -> list[SyncEntry]:
        """Where each record of a run of makes, edits or restores ends up, and
        the shorter run (up to the first change that is not plain: one that moves
        a record, sits under one of the run, must wait for an unsent change here,
        or says nothing to apply). Fills `rows` (the records here) and `states`."""
        found, current = self._repo.record_rows([e.entity_id for e in run])
        rows.update(found)
        made: set[uuid.UUID] = set()
        wanted: list[
            tuple[SyncEntry, dict[str, Any], tuple[uuid.UUID, uuid.UUID | None] | None]
        ] = []
        for e in run:
            here = current.get(e.entity_id)
            if e.delta is not None:
                if here is None:
                    break
                state = apply_delta(here, e.delta, AFTER)
            elif e.new_data:
                state = e.new_data
            else:
                break
            placed = self._placed(e, here)
            if placed is not None and (here is not None or placed[1] in made):
                break  # moved, or put beneath a record of this run
            made.add(e.entity_id)
            wanted.append((e, state, placed))
        if above:
            where = [p for _, _, p in wanted if p is not None]
            trails = self._trails([i for p in where for i in p if i is not None])
            for k, (_, _, placed) in enumerate(wanted):
                if placed is not None and _waits_on(placed, above, trails):
                    wanted = wanted[:k]
                    break
        states.extend((e.entity_id, state) for e, state, _ in wanted)
        return [e for e, _, _ in wanted]

    def _waits(
        self,
        entry: SyncEntry,
        dirty: set[tuple[str, uuid.UUID]],
        above: set[uuid.UUID],
    ) -> bool:
        """Whether a change from the authority must wait for a push of this
        device's own: it is to a thing with an unsent change here, or it
        places a record (makes, moves or brings one back) where an unsent
        change is at or beneath: the record itself, where it is, or where it
        goes. A child's collection is its parent's, so neither can go
        without the other; the push settles where the unsent change ends
        up, and the placement follows."""
        if (entry.entity_type, entry.entity_id) in dirty:
            return True
        if self._bulk_pull and not above:
            return False  # nothing unsent is at or beneath any record
        placed = self._places(entry)
        if placed is None:
            return False
        ids = [i for i in placed if i is not None]
        if any(i in above for i in ids):
            return True  # (no lookup of the trails needed)
        return _waits_on(placed, above, self._trails(ids))

    def _take(
        self,
        entry: SyncEntry,
        dirty: set[tuple[str, uuid.UUID]],
        hold: bool = False,
    ) -> None:
        """Bring in one change from the authority. It is kept in the history
        either way. It is applied unless the authority did not settle on it as
        sent (a later entry carries what it settled on), or it must wait
        (`hold`, see `_waits`: this device has a change it hasn't sent yet to
        the same thing, to a record beneath one this moves, or to a thing the
        same action changed). That one is kept *unapplied* and caught up once
        the push has settled the thing, whatever the outcome (merged, or
        refused): applying it then is what keeps this device from being left
        behind."""
        thing = (entry.entity_type, entry.entity_id)
        if entry.superseded:
            state = "superseded"
        elif hold or thing in dirty:
            state = "held"
        else:
            state = "applied"
        self._repo.insert_entry(entry, hub_seq=entry.hub_seq, apply_state=state)
        if state == "applied":
            self._replay(thing, entry.hub_seq or 0)

    def _replay(
        self, thing: tuple[str, uuid.UUID], from_seq: int, isolate: bool = True
    ) -> None:
        """Bring a thing to where the authority's numbered changes leave it,
        from `from_seq` on: each in turn, in the authority's order. Every
        numbered change it did not supersede is a step the authority took (an
        edit as made, the state it settled on, its own edits), so taking the
        same steps in the same order ends in the same place. Changes of this
        device's own that were numbered later are already applied here, but
        they are taken again after the one arriving now, since that is their
        order; taking a step twice is harmless."""
        for step in self._repo.numbered_entries(thing[0], thing[1], from_seq):
            self._apply(step, isolate)

    def _apply(self, entry: SyncEntry, isolate: bool = True) -> None:
        if not isolate:
            # The caller's savepoint covers it: a refusal undoes all of that.
            self._applier.apply_entry(entry)
            self._recheck_cited_lacks(entry)
            return
        try:
            with self._repo.savepoint():
                self._applier.apply_entry(entry)
            self._recheck_cited_lacks(entry)
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

    def _recheck_cited_lacks(self, entry: SyncEntry) -> None:
        """A change from the authority to a record that cites a file it said
        it hadn't got is the sign the file may have arrived there (the wire has
        no news of uploads): it is asked for again at the next pass, not at the
        end of its wait."""
        if entry.entity_type == "record" and self.fetches_files:
            self._repo.forget_record_lacks(entry.entity_id)

    def _catch_up(self) -> set[tuple[str, uuid.UUID]]:
        """Apply what was held back for things that are free now: each from its
        first held change on, in the authority's order, together with this
        device's own changes numbered among them (`_replay`). Returns the things
        still waiting on a push of this device's own."""
        dirty = self._repo.dirty_entities()
        if self._replay_held(dirty):
            self._commit()
        return dirty

    def _replay_held(self, dirty: set[tuple[str, uuid.UUID]]) -> bool:
        """Apply the held changes that no longer need to wait (see `_waits`),
        each thing's in order from the first held. Nothing is committed here.
        Returns whether anything was applied. The held changes stay held when
        applying them would leave a record in another collection than the
        record above it (a child still where a change of this device's own
        put it, whose settled state is still to arrive)."""
        every = self._repo.held_entries()
        above = self._above_dirty(dirty)
        # An action waits whole while any part of it must (`_waits`).
        blocked = {e.op for e in every if e.op and self._waits(e, dirty, above)}
        held = [
            e for e in every if not self._waits(e, dirty, above) and e.op not in blocked
        ]
        if not held:
            return False
        first: dict[tuple[str, uuid.UUID], int] = {}
        for e in held:
            thing = (e.entity_type, e.entity_id)
            first[thing] = min(first.get(thing, e.hub_seq or 0), e.hub_seq or 0)
        try:
            with self._repo.savepoint():
                for thing, seq in first.items():
                    self._replay(thing, seq)
                records = [eid for kind, eid in first if kind == "record"]
                if records and self._records.placement_mismatches(records):
                    raise _NotYet()
        except _NotYet:
            return False
        self._repo.mark_applied([e.id for e in held])
        return True

    def _push(self, transport: SyncTransport, report: SyncReport) -> int:
        total = 0
        last_first: uuid.UUID | None = None
        while True:
            pending = self._repo.pending_entries(PUSH_BATCH)
            if not pending:
                return total
            if self._drop_done(pending):
                continue  # (settled here: what is left is read again)
            if pending[0].id == last_first:
                # The same change is still first: the last answer took nothing
                # off the queue, and asking again would only repeat it.
                report.waiting += len(pending)
                return total
            last_first = pending[0].id
            ready, folded = self._send_whole(pending)
            if not ready:
                report.waiting += len(pending)
                return total
            # By entries and bytes, whole actions only: how much one request
            # carries doesn't depend on how wide the records are.
            ready = batch_by_budget(ready, PUSH_BATCH, PUSH_BUDGET_BYTES)
            result = transport.push(ready)
            sent = {e.id: e for e in ready}
            self._repo.mark_sent(result.results)
            for r in result.results:
                if r.op_id in folded and r.status != DEFERRED:
                    self._repo.mark_folded(
                        folded[r.op_id],
                        "rejected" if r.status == REJECTED else "synced",
                    )
            held = self._note(result.results, sent, report, set(folded))
            self._commit()
            total += len(result.results) - held
            if held:
                report.waiting += held + (len(pending) - len(result.results))
                return total
            if not result.results:
                # A short answer that settled nothing: going round again would
                # ask the same question.
                report.waiting += len(pending)
                return total
            # Anything the answer left (it may answer fewer than were sent, to
            # keep its own request short) is sent in the next round.

    def _drop_done(self, pending: list[SyncEntry]) -> bool:
        """A pulled change already says what a pending delete or restore of
        this device says (the last change held for that record is the same, and
        this is the only one of this device's to it): there is nothing to send,
        as a rebase drops a change already in what it is put onto. Returns
        whether any was settled."""
        mine = [e for e in pending if e.action in ("delete", "restore")]
        if not mine:
            return False
        count: dict[uuid.UUID, int] = {}
        for e in pending:
            count[e.entity_id] = count.get(e.entity_id, 0) + 1
        latest = {
            (e.entity_type, e.entity_id): e.action for e in self._repo.held_entries()
        }
        done = [
            e.id
            for e in mine
            if count[e.entity_id] == 1
            and latest.get((e.entity_type, e.entity_id)) == e.action
        ]
        self._repo.mark_folded(done, "synced")
        return bool(done)

    def _send_whole(
        self, pending: list[SyncEntry]
    ) -> tuple[list[SyncEntry], dict[uuid.UUID, list[uuid.UUID]]]:
        """What to send for these pending changes. A thing the authority never
        took (its create was refused, say a value its field no longer allows)
        can't be edited there: the edits made to it since, fixing it or not, go
        as one create of the thing as it is now, in place of the first of them.
        Returns what to send and, for each such create, every entry it stands
        for (settled together)."""
        untaken = self._repo.never_taken(
            {
                (e.entity_type, e.entity_id)
                for e in pending
                if e.action in ("update", "restore")
            }
        )
        if not untaken:
            return pending, {}
        ready: list[SyncEntry] = []
        folded: dict[uuid.UUID, list[uuid.UUID]] = {}
        first: dict[uuid.UUID, uuid.UUID] = {}
        for entry in pending:
            if entry.entity_id not in untaken or entry.action not in (
                "update",
                "restore",
            ):
                ready.append(entry)
                continue
            if entry.entity_id in first:
                folded[first[entry.entity_id]].append(entry.id)
                continue
            current = self._repo.snapshot(entry.entity_type, entry.entity_id)
            first[entry.entity_id] = entry.id
            folded[entry.id] = [entry.id]
            if current is None or current.get("deleted_at"):
                continue  # gone here too: nothing to send, settled below
            ready.append(
                replace(
                    entry, action="create", old_data=None, new_data=current, delta=None
                )
            )
        for entry_id, entries in folded.items():
            if not any(e.id == entry_id for e in ready):
                self._repo.mark_folded(entries, "synced")
        return ready, {k: v for k, v in folded.items() if any(e.id == k for e in ready)}

    @_closes_transports
    def send_files(
        self,
        everything: bool = False,
        seconds: float | None = None,
        progress: ProgressFn | None = None,
        after: str = "",
        should_stop: Callable[[], bool] | None = None,
    ) -> FileSendReport:
        """Make the authority hold every file a live record here cites and this
        computer can read. Apart from syncing: the records citing them went
        already (or go whenever they sync), and the authority takes a change
        whatever files it holds, so data and files converge separately. What is
        missing is worked out from the references catalog and the authority's
        answer, so a drive plugged back in, or files added later, are simply
        found. Without `everything`, only files the authority hasn't yet said
        it holds are asked about (no request at all when there are none); with
        it, every file is asked about again, in case one it held has gone.
        `seconds` stops a background pass between files, and `should_stop`
        (a pause, a shutdown) is asked between slices; a file that can't be
        read is counted in `owed` and left for next time. Raises `SyncError`
        when the authority can't be reached. Takes no sync lock: uploading
        changes no record, and the same file sent twice is stored once."""
        report = FileSendReport()
        if not self.fetches_files:
            return report
        self._forget_found()
        first = self._repo.referenced_shas(
            after, FILE_CHECK_PAGE, unconfirmed=not everything
        )
        if not first:
            return report
        self._send_files(
            self._transport(),
            first,
            report,
            progress,
            seconds,
            after,
            everything,
            should_stop,
        )
        self._commit()
        if report.owed:
            self._log_owed(report)
        return report

    def _log_owed(self, report: FileSendReport) -> None:
        """One line for the files the authority lacks that can't be read here:
        how many, a few ids, and (for those this project never stored) which
        collections cite them. Each file is at DEBUG."""
        ignored = self._repo.ignored_missing()
        report.owed = [s for s in report.owed if s not in ignored]
        if not report.owed:
            return
        report.never_stored = sorted(self._repo.never_stored(report.owed))
        report.never_stored_in = self._citing_collections(set(report.never_stored))
        where = ", ".join(f"{n} in {name}" for name, n in report.never_stored_in[:5])
        log.info(
            "sync with %s: %d file(s) the authority lacks cannot be read here; "
            "they go when they can: %s%s",
            self._config.sync.remote,
            len(report.owed),
            ", ".join(x[:10] for x in report.owed[:5]),
            f". {len(report.never_stored)} of them were never stored in this "
            f"project (records cite them without their contents)"
            + (f": records {where}" if where else "")
            if report.never_stored
            else "",
        )

    def _send_files(
        self,
        transport: SyncTransport,
        page: list[str],
        report: FileSendReport,
        progress: ProgressFn | None = None,
        seconds: float | None = None,
        after: str = "",
        everything: bool = False,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        """The one way files go to the authority: starting from `page` (the
        first slice of hashes after `after`), the authority is asked which of
        a slice it lacks, the rest are noted as on the server, and each it
        lacks that can be read here is uploaded and noted, then the next slice
        is read and asked about, so it is only ever asked about the slice about
        to go (not about every file still owed, on every pass). `progress` is
        told how far along it is: files and bytes settled (sent, found on the
        server already) of everything still to settle (a file that can't be read
        here is counted apart, as `owed`, never as sent),
        counted from the inventory in one query before the first file, so the
        total is known from the start and does not grow as slices are asked
        about. Stops between files once `seconds` of uploading are spent;
        asking is not charged to it."""
        rate = RateWindow()
        # Of what is still unconfirmed after `after`: the files, and their bytes
        # where this computer holds a copy (the size the bar goes by).
        total_files, total_bytes = (
            self._repo.unconfirmed_totals(after, self._files.volume_names())
            if progress
            else (0, 0)
        )
        done = settled_bytes = inflight = sent_bytes = tried = unread = 0
        spent = 0.0  # time uploading: the clock `seconds` is measured on
        said = 0.0

        started = time.monotonic()

        def over() -> bool:
            if seconds is None:
                return False
            # Asking isn't charged to the upload budget, but a pass that has
            # only asked (nothing to send) still yields now and then.
            now = time.monotonic()
            charged = spent + (now - group_began[0] if group_began else 0.0)
            return (tried > 0 and charged >= seconds) or (
                now - started >= max(seconds * 2, 1.0)
            )

        def say(force: bool = False) -> None:
            nonlocal said, total_files, total_bytes
            now = time.monotonic()
            if progress and total_files and (force or now - said >= 0.25):
                said = now
                # Grows only when a file is cited after the total was counted
                # (a record edited mid-run): it is then really more to send.
                total_files = max(total_files, done + unread)
                total_bytes = max(total_bytes, settled_bytes + inflight)
                progress(
                    SyncProgress(
                        SENDING,
                        done,
                        total_files,
                        owed=unread,
                        bytes_done=settled_bytes + inflight,
                        bytes_total=total_bytes,
                        rate=rate.add(now, sent_bytes),
                    )
                )

        bytes_lock = threading.Lock()

        def went(n: int) -> None:
            nonlocal sent_bytes, inflight
            with bytes_lock:
                sent_bytes += n
                inflight += n
            say()

        def went_in_pool(n: int) -> None:
            # From an upload thread: counted only. The progress line is said
            # by the sending thread (`drain` while it waits).
            nonlocal sent_bytes, inflight
            with bytes_lock:
                sent_bytes += n
                inflight += n

        def settle(sha: str, why: str | None) -> None:
            """A file is settled: sent (`why` None) or not (`why` says why)."""
            nonlocal done, settled_bytes, unread, inflight, total_bytes
            if why is None:
                done += 1
                settled_bytes += sizes.get(sha, inflight)
                if sha in sizes:  # others in flight keep the bytes they sent
                    with bytes_lock:
                        inflight = max(0, inflight - sizes[sha])
                else:
                    inflight = 0
            else:
                if sha not in report.owed:
                    report.owed.append(sha)
                log.debug("file %s not sent: %s", sha[:12], why)
                unread += 1  # not sent: counted apart, no bytes claimed
                # Its bytes can never be sent from here: the byte total is
                # of what can be read (known once it was tried).
                total_bytes = max(settled_bytes, total_bytes - sizes.get(sha, 0))
            if why is not None:
                inflight = 0
            report.resume_after = sha  # settled: the next pass starts after
            say(force=True)

        # Small files go through `add`: opened here (the store's session is not
        # for other threads), sent by the pool where the transport allows it
        # (many to a request where it takes packs), and confirmed and committed
        # together as they arrive. Large ones never do.
        threads = max(1, int(getattr(transport, "upload_threads", 1)))
        pool = ThreadPoolExecutor(threads) if threads > 1 else None
        accepts = getattr(transport, "accepts_packs", None)
        packing = pool is not None and callable(accepts) and bool(accepts())
        arrived: list[str] = []
        # What is on its way: the hashes sent together, and the answer to come
        # (per hash: None when stored, else why not; a hash missing from it was
        # not answered and is simply left for the next pass).
        flying: list[tuple[list[str], Future[dict[str, str | None]]]] = []
        pack: list[tuple[str, BinaryIO, int]] = []
        pack_bytes = 0
        failed = threading.Event()
        unreadable: list[tuple[str, str]] = []
        group_began: list[float] = []

        def run(f: BinaryIO, sha: str, size: int) -> dict[str, str | None]:
            try:
                if failed.is_set():
                    return {}  # a file before it failed: nothing more goes
                transport.upload_file(sha, _Counting(f, went_in_pool), size)  # type: ignore[arg-type]
                return {sha: None}
            except BaseException:
                failed.set()
                raise
            finally:
                f.close()

        def run_pack(items: list[tuple[str, BinaryIO, int]]) -> dict[str, str | None]:
            try:
                if failed.is_set():
                    return {}
                counted = [
                    (sha, _Counting(f, went_in_pool), size) for sha, f, size in items
                ]
                return transport.upload_pack(counted)  # type: ignore[attr-defined,arg-type]
            except BaseException:
                failed.set()
                raise
            finally:
                for _, f, _ in items:
                    f.close()

        def keep(shas: list[str], answer: dict[str, str | None]) -> None:
            for sha in shas:
                if sha not in answer:
                    continue
                if answer[sha] is None:
                    arrived.append(sha)
                else:
                    unreadable.append((sha, f"the server refused it: {answer[sha]}"))

        def record() -> None:
            """What arrived is confirmed and committed together."""
            if not arrived:
                return
            self._repo.confirm_on_server(arrived)
            self._commit()
            report.sent += len(arrived)
            for sha in arrived:
                log.debug("sent file %s", sha[:12])
                settle(sha, None)
            arrived.clear()

        def send_pack() -> None:
            nonlocal pack_bytes
            items = list(pack)
            pack.clear()
            pack_bytes = 0
            while pool is not None and len(flying) >= PACKS_IN_FLIGHT:
                reap()
            assert pool is not None
            flying.append(([s for s, _, _ in items], pool.submit(run_pack, items)))

        def reap() -> None:
            """Wait for the oldest pack on its way and keep what arrived (so
            settling goes in the order sent). If it failed, everything on its
            way is waited for and the failure is raised."""
            shas, fut = flying[0]
            wait([fut])
            if fut.exception() is not None:
                drain()  # raises it, after keeping what arrived
            flying.pop(0)
            keep(shas, fut.result())
            record()

        def drain(quiet: bool = False) -> None:
            """Wait for the small files in flight, then keep every one that
            arrived (confirmed and committed together), whatever happened to
            the others. The first failure is raised once that is done."""
            nonlocal spent, pack_bytes, inflight
            error: BaseException | None = None
            if pack:
                if quiet:
                    for _, f, _ in pack:
                        f.close()
                    pack.clear()
                    pack_bytes = 0
                else:
                    send_pack()
            if flying:
                pending_uploads = {f for _, f in flying}
                while pending_uploads:
                    _done, pending_uploads = wait(pending_uploads, timeout=0.25)
                    say()  # bytes move while the small files go
            for shas, fut in flying:
                try:
                    keep(shas, fut.result())
                except BaseException as e:
                    error = error or e
            flying.clear()
            failed.clear()
            inflight = 0  # the group is settled (or failed): nothing in flight
            record()
            if group_began:
                spent += time.monotonic() - group_began.pop()
            if error is None:
                # Settled after the group's files, so the point to go on from
                # never passes a file that did not arrive.
                for sha, why in unreadable:
                    settle(sha, why)
            unreadable.clear()
            if error is not None and not quiet:
                raise error

        def add(sha: str, size: int) -> None:
            nonlocal tried, inflight, pack_bytes
            tried += 1
            if not group_began:
                group_began.append(time.monotonic())
            try:
                f = self._files.open(sha)
            except VolumeUnavailableError as e:
                unreadable.append((sha, str(e)))
                return
            except (FileNotFoundError, OSError):
                # (Too many files open at once is an OSError too: that one
                # waits for the next pass, as a file that can't be read does.)
                unreadable.append((sha, "its copy here couldn't be read"))
                return
            if packing:
                if f.seek(0, 2) != size:  # shorter or longer than recorded
                    f.close()
                    unreadable.append((sha, "its copy here is not the size recorded"))
                    return
                f.seek(0)
                pack.append((sha, f, size))
                pack_bytes += size
                if pack_bytes >= PACK_BYTES or len(pack) >= PACK_FILES:
                    send_pack()
                return
            if pool is not None:
                flying.append(([sha], pool.submit(run, f, sha, size)))
            else:
                try:
                    transport.upload_file(sha, _Counting(f, went), size)
                finally:
                    f.close()
                    inflight = 0  # counted as settled when it is confirmed
                arrived.append(sha)
            if (
                len(arrived) + len(flying) >= SMALL_FILE_GROUP
                or time.monotonic() - group_began[0] >= SMALL_FILE_GROUP_SECONDS
            ):
                drain()

        sizes: dict[str, int] = {}
        say(force=True)
        try:
            while page:
                if over() or (should_stop is not None and should_stop()):
                    report.stopped = True
                    return
                # Which of these the authority hasn't confirmed yet: the ones the
                # total counted. (A confirmed file found lost on an `everything`
                # pass is new work, so the total grows by it.)
                pending = self._repo.unconfirmed_of(set(page)) if progress else set()
                missing = set(transport.missing_files(page))
                self._repo.confirm_on_server(set(page) - missing)
                self._repo.note_server_lacks(missing, backoff=False)
                lacking = [sha for sha in page if sha in missing]
                if not lacking:
                    self._commit()
                # Where each is and how big, for the whole slice in one go.
                skipped = pending - missing
                sizes = {
                    sha: max(size for _v, size in rows)
                    for sha, rows in self._files.copies(
                        list(skipped | set(lacking))
                    ).items()
                    if rows
                }
                if progress:
                    done += len(skipped)
                    settled_bytes += sum(sizes.get(sha, 0) for sha in skipped)
                    lost = [sha for sha in lacking if sha not in pending]
                    total_files += len(lost)
                    total_bytes += sum(sizes.get(sha, 0) for sha in lost)
                    say(force=True)
                for sha in lacking:
                    if over():
                        drain()
                        report.stopped = True
                        return
                    size = sizes.get(sha)
                    if size is not None and size <= LARGE_FILE_BYTES:
                        add(sha, size)
                        continue
                    # Large (or with no copy here, which says why): alone, after
                    # everything before it is confirmed, and confirmed and
                    # committed the moment it arrives.
                    drain()
                    tried += 1
                    inflight = 0
                    began = time.monotonic()
                    why = self._upload(transport, sha, went, size)
                    spent += time.monotonic() - began
                    if why is None:
                        self._repo.confirm_on_server([sha])
                        self._commit()  # each file's arrival is kept, whatever follows
                        report.sent += 1
                        log.debug("sent file %s", sha[:12])
                    settle(sha, why)
                drain()
                report.resume_after = page[-1]
                page = self._repo.referenced_shas(
                    page[-1],
                    PACKED_CHECK_PAGE if packing else FILE_CHECK_PAGE,
                    unconfirmed=not everything,
                )
        finally:
            try:
                try:
                    drain(quiet=True)  # what arrived is kept, even on the way out
                except Exception:
                    log.warning(
                        "could not record the files that arrived", exc_info=True
                    )
            finally:
                if pool is not None:
                    pool.shutdown(wait=True)

    def _upload(
        self,
        transport: SyncTransport,
        sha: str,
        on_bytes: Callable[[int], None] | None = None,
        size: int | None = None,
    ) -> str | None:
        """Upload one file: None once it is sent, else why no copy here could
        be read (a failure of the upload itself raises). `size` is the size
        already looked up, if it was."""
        try:
            if size is None:
                size = self._files.size_of(sha)
            if size is None:
                return "it isn't on this computer"
            with self._files.open(sha) as f:
                transport.upload_file(sha, _Counting(f, on_bytes), size)
        except VolumeUnavailableError as e:
            return str(e)
        except FileNotFoundError:
            return "its copy here couldn't be read"
        return None

    def _note(
        self,
        results: list[Any],
        sent: dict[uuid.UUID, SyncEntry],
        report: SyncReport,
        whole: set[uuid.UUID] | None = None,
    ) -> int:
        """Keep what the authority said that a person should see: a clash, or a
        refusal (the same kind of row, so one path). A thing has at most one
        refusal waiting: a newer one replaces the one before (the person fixes
        the thing once, not every attempt), and when a thing never taken before
        goes in as a whole (`whole`), its refusal is settled by that. Returns
        how many changes it held back."""
        held = 0
        if results:
            self._flags_stale = True  # (answers may open, or settle, a flag)
        # Which things have a refusal waiting: asked once, not of each (almost
        # none do), and kept up as refusals are added below.
        refused = self._repo.with_open_refusals(
            e.entity_id for r in results if (e := sent.get(r.op_id)) is not None
        )
        for result in results:
            entry = sent.get(result.op_id)
            if entry is None:
                continue
            if result.status == DEFERRED:
                held += 1
                continue
            waiting = (
                [
                    c
                    for c in self._repo.find_open_conflicts(
                        kind="rejected", entity_id=entry.entity_id
                    )
                    if c.op_id != result.op_id
                ]
                if entry.entity_id in refused
                else []
            )
            retried: list[uuid.UUID] = []
            if result.status == REJECTED:
                if waiting:
                    # Refused again: the item already open says so (the
                    # latest change and why), rather than another beside it.
                    report.rejected += 1
                    newest, *older = sorted(
                        waiting, key=lambda c: c.created_at, reverse=True
                    )
                    self._repo.renew_refusal(
                        newest.id,
                        result.op_id,
                        result.message,
                        entry.new_data,
                        _refused_field(result),
                        _refused_code(result),
                    )
                    self._repo.resolve_conflicts([c.id for c in older], "replaced")
                    continue
            elif whole and result.op_id in whole:
                self._repo.resolve_conflicts([c.id for c in waiting], "sent")
            else:
                # A change sent again went in: its refusal is settled.
                retried = [c.id for c in waiting if c.resolution == "retrying"]
                self._repo.resolve_conflicts(retried, "sent")
            problems = result.conflicts
            if result.status != REJECTED and retried:
                # Sent again to bring it back (it was deleted on the server):
                # being kept despite that delete is what was asked for, not
                # something new to review.
                problems = [p for p in problems if p.get("kind") != "edit_vs_delete"]
            if result.status == REJECTED:
                report.rejected += 1
                problems = [
                    {
                        "kind": "rejected",
                        "field": _refused_field(result),
                        "code": _refused_code(result),
                        "yours": entry.new_data,
                        "message": result.message,
                    }
                ]
            for problem in problems:
                kind = problem.get("kind", "conflict")
                if self._repo.has_conflict(result.op_id, problem.get("field"), kind):
                    continue
                if kind == UNFIT:
                    # One flag per field of a record: a newer one replaces the
                    # one before. (It is no clash: nothing to pull again.)
                    self._repo.resolve_conflicts(
                        [
                            c.id
                            for c in self._repo.find_open_conflicts(
                                kind=UNFIT, entity_id=entry.entity_id
                            )
                            if c.field == problem.get("field")
                        ],
                        "replaced",
                    )
                elif result.status != REJECTED:
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
                    theirs_device=problem.get("theirs_device"),
                    theirs_at=problem.get("theirs_at"),
                    op_id=result.op_id,
                    device_name=None,
                    message=problem.get("message"),
                    code=problem.get("code") if kind in ("rejected", UNFIT) else None,
                )
                if kind == "rejected":
                    refused.add(entry.entity_id)
        return held

    def _settle_flags(self) -> None:
        """Settle the flags (`unfit` items) the data no longer earns. See
        `_judge_flags`; whatever goes wrong there leaves the flags as they are
        and never fails the sync."""
        try:
            self._judge_flags()
        except Exception:  # noqa: BLE001 - a flag is a reminder, never a reason to fail
            log.warning("sync: could not judge the flags again", exc_info=True)
            try:
                self._repo.rollback()
            except Exception:  # noqa: BLE001 - nothing more to do about it
                log.warning("sync: could not undo the flag pass", exc_info=True)

    def _judge_flags(self) -> None:
        """A flag is the authority's judgement of a record's values by its
        rules, so a copy shows what the authority says: it goes only when this
        copy is level with the authority (nothing unsent, no change of its own
        structure refused, none of the server's structure it could not apply,
        the feed read to its head), where the schemas and values it holds are
        the authority's. Then every open flag (there are few) is judged again,
        with one resolver and the records read in chunks, and those whose field
        no longer breaks a rule, or whose record is deleted or gone, are
        settled. Nothing is done when nothing came in, was answered or was
        copied since the last time they were judged. Kept as they are: a record
        with a refused change of its own, one in a collection this copy may no
        longer read, and one that cannot be judged here."""
        if not (self._at_head and self._repo.count_pending() == 0):
            return
        if not self._flags_stale:
            return
        flags: dict[uuid.UUID, list[SyncConflictDTO]] = {}
        for c in self._repo.find_open_conflicts(kind=UNFIT):
            if c.entity_type == "record":
                flags.setdefault(c.entity_id, []).append(c)
        if not flags:
            self._flags_stale = False
            return
        # (a change of this copy's structure the authority refused, or one of
        # the authority's it could not apply: the rules here are not its)
        refused = self._repo.find_open_conflicts(kind="rejected")
        if any(c.entity_type in ("schema", "field") for c in refused) or any(
            c.entity_type in ("schema", "field")
            for c in self._repo.find_open_conflicts(kind="not_applied")
        ):
            return
        refused_records = {c.entity_id for c in refused}
        readable = self._repo.readable()
        cache = self._records.incoming_cache()
        done: list[uuid.UUID] = []
        ids = [r for r in flags if r not in refused_records]
        for at in range(0, len(ids), FLAG_CHUNK):
            chunk = ids[at : at + FLAG_CHUNK]
            held = {
                uuid.UUID(str(st["id"])): st
                for st in self._repo.record_snapshots([str(i) for i in chunk])
            }
            for record_id in chunk:
                state = held.get(record_id)
                if state is None:
                    done += [c.id for c in flags[record_id]]  # (purged here or there)
                    continue
                if (
                    readable is not None
                    and str(state.get("dataset_id")) not in readable
                ):
                    continue
                try:
                    broken = {
                        f["field"] for f in self._records.rule_findings(state, cache)
                    }
                except (
                    ValidationError,
                    ValueError,
                    TypeError,
                    KeyError,
                    AttributeError,
                ):
                    continue
                done += [c.id for c in flags[record_id] if c.field not in broken]
        if done:
            self._repo.resolve_conflicts(done, "fixed")
            self._commit()
        self._flags_stale = False

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
        self._repo.finish_seed()  # a copy has no first upload to finish
        # What this project recorded before it joined is about nothing the copy
        # holds (a joining project is empty), so there is nothing to send. Until
        # the copy is whole the cursor says so (JOINING): syncing is refused and
        # connecting again copies again, never a feed applied to half a copy.
        self._repo.mark_all_synced()
        self._repo.set_cursor(JOINING)
        self._commit()
        head, _ = self._copy_state(transport, hello, progress)
        head = head or 0
        self._repo.set_cursor(head)
        self._repo.set_history_from(head or None)
        self._repo.set_history_scan(None)
        if hello.readable is not None:
            self._repo.set_readable({c["id"] for c in hello.readable})
        self._commit()
        self._pull(transport)

    def _copy_state(
        self,
        transport: SyncTransport,
        hello: Hello,
        progress: ProgressFn | None = None,
    ) -> tuple[int, dict[str, set[str]]]:
        """Write everything the authority holds as it is now, kind by kind.
        Returns the number taken before reading (what changes meanwhile is in
        the feed past it) and, by kind, the ids it holds."""
        total = sum(hello.counts.get(k, 0) for k in ENTITY_ORDER) or None
        done = 0
        head: int | None = None
        held: dict[str, set[str]] = {}
        for kind in kinds_for(hello.protocol_version):
            # Things that sit under another of their kind that has not arrived
            # yet (it was made later, on a clock that was ahead): the database
            # refuses them until it has, so they wait for it, by its id.
            waiting: dict[str, list[dict[str, Any]]] = {}
            seen = held.setdefault(kind, set())
            after: str | None = None
            while True:
                page = transport.snapshot(kind, after, SNAPSHOT_PAGE)
                head = page.head_seq if head is None else head
                above = {p for snap in page.items if (p := _sits_under(kind, snap))}
                present = self._repo.existing_ids(kind, above)
                for snap in page.items:
                    seen.add(snap["id"])
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
                    "copying: %d %s(s) whose parent was removed meanwhile were "
                    "left out",
                    sum(len(v) for v in waiting.values()),
                    kind,
                )
        return head or 0, held

    def _catch_up_readable(self, transport: SyncTransport, hello: Hello) -> None:
        """Take the collections this device has been given access to since it
        last synced. The feed past the cursor carries only what changes from
        now on, so what those collections already held is read as it is now,
        and what this device held of them from before (it may have lost access
        and been given it back) is made to match: what the authority no longer
        has goes, except changes still waiting to be sent. What a device held of
        a collection it *lost* access to is left as it is: nothing it holds can
        be taken back, the authority only stops sending."""
        if hello.readable is None:
            return  # an authority that does not say (protocol 4): nothing to ask
        made = {c["id"]: c["seq"] for c in hello.readable}
        now = set(made)
        had = self._repo.readable()
        if had is None:
            # First told (a device from before, or one that has just seeded):
            # it holds the collections it has. One it was given while on an
            # older protocol, which did not tell it, is one it does not have
            # and is read now like any other it was given.
            had = self._repo.existing_ids("dataset", now)
            # (Kept before any is read, so one cut short is still to do.)
            self._repo.set_readable(had)
            self._commit()
        cursor = self._repo.meta().cursor
        for collection in sorted(now - had):
            # One made after the cursor (the authority numbered it later than
            # this device has read) arrives in the feed like anything new; only
            # one that was already there is one this device was not allowed.
            if made[collection] <= cursor:
                self._copy_collection(
                    transport, collection, hello.protocol_version, cursor
                )
                if self._repo.meta().history_from:
                    # What this device was sent of the earlier history was
                    # without that collection: it is read again from the start
                    # (what is held is not stored twice).
                    self._repo.set_history_scan(0)
            had.add(collection)
            self._repo.set_readable(had)
            self._commit()
        if now != had:
            self._repo.set_readable(now)
            self._commit()

    def _copy_collection(
        self, transport: SyncTransport, collection: str, protocol: int, cursor: int
    ) -> None:
        """One collection, its records and their notes, as the authority holds
        them now (`snapshot` with `dataset`), and then the records that left it
        since `cursor` for another collection this device may read: the feed
        past the cursor will say they moved, and the device must hold them by
        then or that, and every change after it, would be to a record it lacks."""
        self._flags_stale = True  # (records come in as the authority has them)
        dirty = {(kind, str(i)) for kind, i in self._repo.dirty_entities()}
        held: set[str] = set()
        passes: list[tuple[str, int | None]] = [
            ("dataset", None),
            ("record", None),
            ("note", None),
            ("record", cursor),
            ("note", cursor),
        ]
        for kind, left_after in passes:
            if kind not in kinds_for(protocol):
                continue
            after: str | None = None
            # Things under another of their kind that is on a later page wait
            # for it across pages (as in `_copy_state`).
            waiting: dict[str, list[dict[str, Any]]] = {}
            while True:
                page = transport.snapshot(
                    kind, after, SNAPSHOT_PAGE, collection, left_after
                )
                above = {p for snap in page.items if (p := _sits_under(kind, snap))}
                present = self._repo.existing_ids(kind, above)
                for snap in page.items:
                    if kind == "record" and left_after is None:
                        held.add(snap["id"])
                    if (kind, snap["id"]) not in dirty:
                        self._join_one(kind, snap, present, waiting)
                self._commit()
                if not page.more:
                    break
                after = page.next
            if waiting:
                log.info(
                    "catching up on a collection: %d %s(s) whose parent was "
                    "removed meanwhile were left out",
                    sum(len(v) for v in waiting.values()),
                    kind,
                )
        # (What this device made while the pages were read is its own to send.)
        dirty = {(kind, str(i)) for kind, i in self._repo.dirty_entities()}
        gone = self._repo.record_ids_in(uuid.UUID(collection)) - held
        for thing in sorted(gone):
            if ("record", thing) not in dirty:
                self._applier.apply_purge("record", uuid.UUID(thing))
        self._commit()

    def _copy_again(
        self, transport: SyncTransport, hello: Hello, report: SyncReport
    ) -> None:
        """Catch up by copying, when the feed no longer holds what this device
        has yet to read (the authority pruned its history past its cursor). What
        this device made and hasn't sent goes first, as in any sync; then
        everything is written as the authority holds it, and what it no longer
        holds is removed here, except what this device is still waiting on (a
        change not sent, or one a person has yet to settle)."""
        log.info(
            "sync: the server's history starts after %d and this copy read up to "
            "%d; copying it again",
            hello.feed_floor,
            self._repo.meta().cursor,
        )
        report.pushed += self._push(transport, report)
        head, held = self._copy_state(transport, hello)
        # (A flag alone keeps nothing: a record the authority no longer holds
        # goes, and its flag with it, `_settle_flags`.)
        keep = {(kind, str(i)) for kind, i in self._repo.dirty_entities()} | {
            (c.entity_type, str(c.entity_id))
            for c in self._repo.find_open_conflicts()
            if c.kind != UNFIT
        }
        for kind in reversed(ENTITY_ORDER):
            gone = self._repo.all_ids(kind) - held.get(kind, set())
            for thing in sorted(gone):
                if (kind, thing) not in keep:
                    self._applier.apply_purge(kind, uuid.UUID(thing))
            self._commit()
        self._repo.set_cursor(head)
        if hello.readable is not None:
            self._repo.set_readable({c["id"] for c in hello.readable})
        self._commit()
        self._flags_stale = True  # (everything was rewritten as the authority has it)

    @_closes_transports
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
            # Where it got to, which a device that may not read everything can
            # have taken past the last entry it holds (a hidden run).
            scan = self._repo.history_scan()
            after = scan if scan is not None else self._repo.history_fetched_upto(upto)
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
                # (A device that may not read everything is told how far the
                # authority looked: past entries it was not sent too.)
                if page.through is not None and page.through > after:
                    after = min(page.through, upto)
                self._repo.set_history_scan(after)
                self._commit()
                if progress:
                    progress(SyncProgress(HISTORY, min(after, upto), upto))
                last = page.entries[-1].hub_seq if page.entries else None
                if page.through is not None and page.more and after < upto:
                    continue  # more to look through, nothing to conclude yet
                if not page.more or last is None or last > upto:
                    after = upto  # nothing more up to it (some may be pruned)
            if after >= upto:
                self._repo.set_history_from(None)
                self._repo.set_history_scan(None)
                self._commit()
                return True
            return False

    # -- files from the authority ----------------------------------------

    @property
    def fetches_files(self) -> bool:
        """Whether files missing here can come from an authority: this project
        follows one (an authority itself has nobody to fetch from)."""
        return self.configured and not self._config.sync.serve

    def server_lacks(self, shas: set[str]) -> set[str]:
        """Of these files, those the authority said it hasn't got when last
        asked (none, when this project follows no authority)."""
        return self._repo.server_lacks_of(shas) if self.fetches_files else set()

    def not_on_server(self, shas: set[str]) -> set[str]:
        """Of these files, those the authority hasn't said it holds (none,
        when this project follows no authority)."""
        return self._repo.unconfirmed_of(shas) if self.fetches_files else set()

    def files_to_fetch(self) -> int:
        """How many files this computer keeps a copy of (those of collections
        kept here, see `collection_mode`) that no drive here holds yet: what the
        background download still has to fetch."""
        if not self.fetches_files:
            return 0
        return self._repo.count_files_not_here(self._kept_collections())

    def files_to_try(self) -> int:
        """What a background download pass has to request: `files_to_fetch`,
        plus the files the server said it hadn't got that are due to be asked
        about again (see `LACK_RETRY_FIRST`)."""
        if not self.fetches_files:
            return 0
        return self._repo.count_files_not_here(self._kept_collections(), "wait")

    def files_missing(self) -> int:
        """How many files records here cite that no drive here holds and the
        server said it hasn't got: missing everywhere, so nothing is
        downloading them (`civex files missing` lists them). Files a person
        chose to ignore are not counted."""
        if not self.fetches_files:
            return 0
        return self._repo.count_files_not_here(None, "only")

    def collection_mode(self, collection_id: str) -> str:
        """Whether a collection's files are kept on this computer (`keep`) or
        fetched when opened or exported (`opened`): its own setting, else the
        project's `download_files`."""
        return self._config.sync.collection_files.get(collection_id) or (
            "keep" if self._config.sync.download_files == "all" else "opened"
        )

    def _kept_collections(self) -> set[uuid.UUID]:
        return {
            cid
            for cid in self._repo.live_collections()
            if self.collection_mode(str(cid)) == "keep"
        }

    def _collection_id(self, ref: str) -> uuid.UUID:
        """A live collection, by id or name."""
        live = self._repo.live_collections()
        for cid, name in live.items():
            if str(cid) == ref or name == ref:
                return cid
        raise NotFoundError(f"There is no collection '{ref}'")

    def collection_files(self) -> list[CollectionFilesDTO]:
        """Each live collection's files on this computer: how many are here and
        their size, how many are only on the server, and whether it keeps a
        copy here. From the catalog, nothing read from disk or the server."""
        counts = self._repo.files_by_collection()
        out = []
        for cid, name in sorted(
            self._repo.live_collections().items(), key=lambda kv: kv[1].casefold()
        ):
            here, size, remote = counts.get(cid, (0, 0, 0))
            out.append(
                CollectionFilesDTO(
                    id=str(cid),
                    name=name,
                    mode=self.collection_mode(str(cid)),
                    chosen=str(cid) in self._config.sync.collection_files,
                    files_here=here,
                    bytes_here=size,
                    files_on_server=remote,
                )
            )
        return out

    def set_collection_mode(self, collection: str, mode: str | None) -> str:
        """Keep a collection's files on this computer (`keep`), fetch them
        only when opened (`opened`), or follow the project's setting (None).
        Keeping means the background download fetches what is missing. Returns
        the mode now in force."""
        if mode is not None and mode not in COLLECTION_FILE_MODES:
            raise ValidationError(
                f"Choose one of: {', '.join(COLLECTION_FILE_MODES)} (got '{mode}')"
            )
        cid = str(self._collection_id(collection))
        if mode is None:
            self._config.sync.collection_files.pop(cid, None)
        else:
            self._config.sync.collection_files[cid] = mode
        self._config_store.save(self._config)
        return self.collection_mode(cid)

    def free_up(self, collection: str, dry_run: bool = True) -> FreeUpReport:
        """Remove this computer's copies of a collection's files, to free space
        (see `free_up_files` for what is kept and why). Done for real, the
        collection is set to `opened` first, so the background download doesn't
        fetch them straight back."""
        self._can_free_up()
        cid = self._collection_id(collection)
        here = self._room_of(list(self._repo.files_here_of(cid)))
        report = self._free(here, self._kept_collections() - {cid}, dry_run=True)
        if dry_run:
            return report
        self.set_collection_mode(str(cid), "opened")
        return self._free(here, self._kept_collections(), dry_run=False)

    def free_up_files(self, shas: list[str], dry_run: bool = True) -> FreeUpReport:
        """Remove this computer's copies of these files, to free space; each is
        fetched again when opened or exported. Safe by construction: only
        files the server says it holds, asked at that moment (one never sent
        stays), and never one a collection kept on this computer uses (the
        background download would only fetch it back: switch that collection to
        `opened` first). Counts only unless `dry_run` is False. Holds the
        store's clean-up lock, so no clean-up or file move runs meanwhile."""
        self._can_free_up()
        return self._free(self._room_of(shas), self._kept_collections(), dry_run)

    def _room_of(self, shas: list[str]) -> dict[str, int]:
        """Of these files, those on a drive here, with the room removing them
        frees: every copy goes, so each copy's bytes count."""
        return {
            sha: sum(size for _volume, size in rows)
            for sha, rows in self._files.copies(shas).items()
        }

    def _can_free_up(self) -> None:
        if not self.fetches_files:
            raise ValidationError(
                "This project doesn't follow a server, so its files have nowhere "
                "else to come from: they can't be removed to free space."
            )

    @_closes_transports
    def _free(
        self, here: dict[str, int], kept: set[uuid.UUID], dry_run: bool
    ) -> FreeUpReport:
        """The one rule for removing copies: of these files on this computer
        (sha -> size), all but those a kept collection uses and those the
        server hasn't got."""
        kept_shared = self._repo.used_by(list(here), kept)
        candidates = [sha for sha in here if sha not in kept_shared]
        transport = self._transport()
        missing: set[str] = set()
        for i in range(0, len(candidates), FILE_CHECK_PAGE):
            missing |= set(transport.missing_files(candidates[i : i + FILE_CHECK_PAGE]))
        removable = [sha for sha in candidates if sha not in missing]
        report = FreeUpReport(
            files=len(removable),
            bytes=sum(here[sha] for sha in removable),
            kept_shared=len(kept_shared),
            not_on_server=len(missing),
        )
        if dry_run:
            return report
        with self._files.gc_lock():
            for sha in removable:
                self._files.delete(sha)
        self._commit()
        return report

    def not_here_reasons(self, shas: list[str]) -> dict[str, tuple[str, str]]:
        """(reason, fix) for each of these files the server hasn't got either:
        which computer added it, when known, and what brings it."""
        return {
            sha: not_on_server_yet(who)
            for sha, who in self._repo.added_by(shas).items()
        }

    def set_download_files(self, mode: str) -> None:
        """Which files this device keeps a copy of: `all` (fetched in the
        background) or `opened` (only when opened or exported)."""
        if mode not in DOWNLOAD_MODES:
            raise ValidationError(
                f"Choose one of: {', '.join(DOWNLOAD_MODES)} (got '{mode}')"
            )
        self._config.sync.download_files = mode
        self._config_store.save(self._config)

    def fetch_file(self, sha256: str) -> bool:
        """Download one file a record here cites from the authority, onto the
        drive its collection's files go to. True once it is here (it may have
        been already); False when the authority hasn't got it either (the device
        that added it hasn't sent it yet). Raises `SyncError` when the authority
        can't be reached. Doesn't take the sync lock: a download changes no
        record, and two of the same file store the same content once."""
        return self.fetch_files(shas=[sha256]).fetched == 1 or self._files.exists(
            sha256
        )

    @_closes_transports
    def fetch_files(
        self,
        shas: list[str] | None = None,
        limit: int | None = None,
        skip: set[str] | None = None,
        seconds: float | None = None,
        progress: Callable[[int], None] | None = None,
        volume: str | None = None,
        on_bytes: Callable[[int], None] | None = None,
    ) -> FileFetchReport:
        """Download files the records here cite that no drive here holds (all
        of them, or those of `shas`), each checked against its hash and saved
        as it arrives. `limit` files or `seconds` at most (a background pass
        stops between files once either is spent); `skip` names files not to
        ask for again (the authority hadn't got them a moment ago). `progress`
        is told each file done. What the authority hasn't got is in `absent`."""
        report = FileFetchReport()
        if not self.fetches_files:
            return report
        transport = self._transport()
        # The background download fetches only what this computer keeps; a
        # file asked for by hash (opened, exported) comes whatever its
        # collection's setting.
        collections = self._kept_collections() if shas is None else None
        started = time.monotonic()
        after = ""
        while True:
            page = self._repo.files_not_here(after, FILE_CHECK_PAGE, shas, collections)
            if not page:
                break
            after = page[-1][0]
            for sha, collection in page:
                if skip and sha in skip:
                    continue
                if (limit is not None and report.attempted >= limit) or (
                    seconds is not None and time.monotonic() - started >= seconds
                ):
                    report.stopped = True
                    return report
                report.attempted += 1
                if self._files.exists(sha):  # on a drive, just not inventoried
                    report.fetched += 1
                    continue
                try:
                    chunks = transport.file_chunks(sha)
                except FileNotFoundError:
                    report.absent.append(sha)
                    # A file asked for by name (opened) doesn't lengthen the
                    # background wait.
                    self._repo.note_server_lacks([sha], backoff=shas is None)
                    continue
                # Straight onto the drive (the one asked for, when it is
                # fetched to go there, else its collection's): each byte
                # written once, counted as it comes.
                stored = self._files.put_chunks(
                    _counted(chunks, on_bytes),
                    sha,
                    collection_id=str(collection) if collection else None,
                    volume=volume,
                )
                if stored.sha256 != sha:
                    self._files.delete(stored.sha256)
                    raise SyncError("The server sent the wrong content for a file")
                self._repo.confirm_on_server([sha])  # it came from there
                self._commit()
                report.fetched += 1
                if progress:
                    progress(report.fetched)
        return report

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

    def _seed_snapshots(
        self, kind: str, leave: Callable[[str], bool] | None = None
    ) -> Iterator[dict[str, Any]]:
        """What to send for `kind`, in an order the authority can accept: a
        record only after the one it sits under and the ones it refers to, since
        the authority checks both and remembers a refusal for good. Things
        `leave` names (by id) are not read at all."""
        if kind == "record":
            order = self._repo.record_seed_order()
            if leave:
                order = [i for i in order if not leave(i)]
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
        self,
        transport: SyncTransport,
        progress: ProgressFn | None = None,
        protocol: int = PROTOCOL_MAX,
        skip: set[tuple[str, str]] | None = None,
        advance: bool = True,
        salt: str | None = None,
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
        # What the authority answered of this seed before it was interrupted:
        # not sent again (the ids are the same every run, so what is left goes
        # as it would have).
        acked = self._repo.seed_acked()
        if acked:
            hello = transport.hello()
            if hello.empty or hello.head_seq < self._repo.seed_acked_head():
                # The authority holds nothing now, or is behind where it was
                # when it answered (reset, or restored from a backup taken
                # mid-seed): what it once answered is no longer there.
                self._repo.forget_seed_acks()
                self._commit()
                acked = set()
        resumed = bool(acked)

        def answered(kind: str) -> Callable[[str], bool]:
            return lambda thing: str(entry_id(kind, thing)) in acked

        def entry_id(kind: str, thing: str) -> uuid.UUID:
            return uuid.uuid5(
                meta.project_id,
                f"seed:{salt}:{kind}:{thing}" if salt else f"seed:{kind}:{thing}",
            )

        total = self._repo.entity_count() or None
        sent = 0

        def flush() -> None:
            nonlocal head, batch, sent
            if not batch:
                return
            # Records only: the files they cite follow separately
            # (`send_files`), so an empty authority has the whole project in
            # moments, however large its files.
            result = transport.push(batch)
            head = result.head_seq
            if any(r.status == DEFERRED for r in result.results):
                raise SyncError(
                    "The server is still waiting for a file", retryable=True
                )
            # A refusal is kept for review, like any other (the person keeps what
            # they made and can fix it and retry); it doesn't stop the rest.
            self._note(result.results, {e.id: e for e in batch}, report)
            # What it took it holds now, whatever refused it before (another
            # server, or this one before a fix): an edit of it goes as an edit.
            # (Refused again, by one taken before and since reset, it is
            # missing there again.)
            things = {e.id: e.entity_id for e in batch}
            answers = [
                (things[r.op_id], r.status) for r in result.results if r.op_id in things
            ]
            self._repo.forget_refusals(
                {i for i, status in answers if status not in (REJECTED, DEFERRED)},
                {i for i, status in answers if status == REJECTED},
            )
            sent += len(batch)
            # Kept at once, so a restart goes on from here.
            self._repo.note_seed_acked([e.id for e in batch], head)
            self._commit()
            if progress:
                kind = batch[-1].entity_type
                progress(SyncProgress(FILLING, sent, total and max(total, sent), kind))
            batch = []

        last_stamp = self._repo.latest_hlc()

        # Only the kinds the authority reads (one on an older protocol has no
        # Analytics page to take, say).
        for kind in kinds_for(protocol):
            for snap in self._seed_snapshots(kind, answered(kind) if acked else None):
                if skip and (kind, str(snap["id"])) in skip:
                    continue  # a resumed upload leaves other devices' things
                if str(entry_id(kind, str(snap["id"]))) in acked:
                    continue  # the authority has answered it already
                now = datetime.now(timezone.utc)
                # Each stamp follows the last (a seed adds nothing to the log
                # here, so the newest stamp is read once, not per entry).
                last_stamp = stamp = hlc.tick(last_stamp, int(now.timestamp() * 1000))
                batch.append(
                    SyncEntry(
                        id=entry_id(kind, str(snap["id"])),
                        action="create",
                        entity_type=kind,
                        entity_id=uuid.UUID(snap["id"]),
                        old_data=None,
                        new_data=snap,
                        timestamp=now.isoformat(),
                        actor=actor,
                        device_id=device_id,
                        hlc=stamp,
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
        if resumed and not head and not skip:
            # Everything had been answered before: the head is still needed.
            head = transport.hello().head_seq
        self._repo.finish_seed()
        # Only a first seed (connect) moves the cursor to the head: a resumed one may
        # follow a pull, and other devices may have written since.
        if advance and self._repo.meta().cursor == 0 and not skip:
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
        if (
            take not in _takes_for(conflict)
            and not (take == "edited" and conflict.kind == "conflict")
            and not (take == "restore_above" and self._sits_under(conflict))
        ):
            raise ValidationError(f"A {conflict.kind} can't be settled with '{take}'")
        if take in ("mine", "value"):
            self._put_value(
                conflict, conflict.yours if take == "mine" else value, force
            )
        elif take == "delete":
            self._records.delete(str(conflict.entity_id))
        elif take in ("retry", "restore_above"):
            if take == "restore_above":
                # Refused because what it sits under is deleted: bring that
                # back (its restores go first), then send the record again.
                self._records.restore_above(str(conflict.entity_id))
            # Not settled yet: it is settled by the authority's answer (it goes
            # in, or the same item says why it was refused again).
            self._resend(conflict)
            self._repo.mark_retrying(conflict_id)
            self._commit()
            return
        if take == "theirs" and self._keeps_structure(conflict):
            self._let_structure_go(conflict)  # (settles it, or says why not)
        else:
            self._repo.resolve_conflict(conflict_id, take)
        self._flags_stale = True  # (a refusal let go may make this copy level)
        self._commit()

    @staticmethod
    def _keeps_structure(conflict: SyncConflictDTO) -> bool:
        return (
            conflict.kind == "rejected"
            and conflict.entity_type in KEPT_STRUCTURE
            and conflict.code == UNFIT_DATA
        )

    def _let_structure_go(
        self,
        conflict: SyncConflictDTO,
        read: dict[str, dict[str, dict[str, Any]]] | None = None,
    ) -> None:
        """A refused change to a schema or a field is let go: this copy becomes
        what the authority holds now (what it holds of the thing, read from it;
        a thing it never had is put in the trash here, with what went with it),
        and takes what it said meanwhile (held while the change was kept). The
        other parts of the action go with it: it can't be kept by halves.
        Refused, the item left open, when the thing has another change still
        to send (letting go would drop it) or the authority can't be reached."""
        original = self._repo.get_entry(conflict.op_id) if conflict.op_id else None
        ids = (
            {e.id for e in self._repo.entries_of_action(original.op)}
            if original and original.op
            else set()
        )
        mine = (conflict.entity_type, conflict.entity_id)
        open_ = [
            c
            for c in self._repo.find_open_conflicts(kind="rejected")
            if c.id == conflict.id
            or (c.op_id in ids)
            or (c.entity_type, c.entity_id) == mine
        ]
        things = {(c.entity_type, c.entity_id) for c in open_}
        structure = {t for t in things if t[0] in KEPT_STRUCTURE}
        for kind, thing_id in sorted(things, key=str):
            if self._repo.has_unsent(kind, thing_id):
                named = self._named(conflict)
                name = named.get("field_label") or named.get("schema_name") or kind
                raise ValidationError(f"Send or undo your other change to {name} first")
        held = self._authority_holds(structure, read)
        for (kind, thing_id), state in held.items():
            if state is not None:
                self._applier.apply_state(kind, thing_id, state)
            elif not (self._repo.snapshot(kind, thing_id) or {}).get("deleted_at"):
                self._applier.apply_delete(kind, thing_id, datetime.now(timezone.utc))
        self._repo.resolve_conflicts([c.id for c in open_], "theirs")
        self._replay_held(self._repo.dirty_entities())

    def _authority_holds(
        self,
        things: set[tuple[str, uuid.UUID]],
        read: dict[str, dict[str, dict[str, Any]]] | None = None,
    ) -> dict[tuple[str, uuid.UUID], dict[str, Any] | None]:
        """What the authority holds of each of these schemas and fields now
        (None: nothing). A kind is read from it once, page by page, as a copy
        of it is: into `read` when the caller keeps one across several."""
        read = {} if read is None else read
        try:
            transport = self._transport()
            for kind in {k for k, _ in things} - set(read):
                held: dict[str, dict[str, Any]] = {}
                after: str | None = None
                while True:
                    page = transport.snapshot(kind, after, SNAPSHOT_PAGE)
                    held.update({snap["id"]: snap for snap in page.items})
                    if not page.more:
                        break
                    after = page.next
                read[kind] = held
            out: dict[tuple[str, uuid.UUID], dict[str, Any] | None] = {
                (k, i): read[k].get(str(i)) for k, i in things
            }
            return out
        except SyncError as e:
            raise ValidationError(
                f"The server can't be reached to take its version: {e}"
            ) from None

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
            kept = [c for c in offered if self._keeps_structure(c)]
            plain = [c for c in offered if c not in kept]
            report.settled = [c.id for c in plain]
            report.done = self._repo.resolve_conflicts(report.settled, take)
            read: dict[str, dict[str, dict[str, Any]]] = {}
            for c in kept:
                if self._repo.get_conflict(c.id).status != "open":  # type: ignore[union-attr]
                    continue  # (settled with an earlier part of its action)
                try:
                    with self._repo.savepoint():
                        self._let_structure_go(c, read)
                    report.done += 1
                    report.settled.append(c.id)
                except CivexError as e:
                    report.failed.append((c.id, str(e)))
            self._flags_stale = True
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
            # The change itself isn't kept here (a thing sent when the authority
            # was filled is sent, not recorded). If the authority never took
            # the thing, sending it again is sending it as it is now.
            thing = (conflict.entity_type, conflict.entity_id)
            if conflict.entity_id not in self._repo.never_taken({thing}):
                raise ValidationError("The change is no longer held here")
            current = self._repo.snapshot(*thing)
            self._audit.log_change("create", thing[0], thing[1], None, current)
            return
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
        for c in self._repo.find_open_conflicts(kind="rejected"):
            if c.op_id in others:
                self._repo.mark_retrying(c.id)

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
    # Taken as it is: nothing to send again. Fixing the values clears it (see
    # `_note`); `theirs` only lets the reminder go.
    "unfit": ("theirs",),
}
_RECORD_ONLY = frozenset({"mine", "value", "delete"})


def _takes_for(conflict: SyncConflictDTO) -> tuple[str, ...]:
    """What a row offers by its kind. `SyncService._describe` adds
    `restore_above` for a refused record that sits under deleted records here,
    which takes looking the record up."""
    if conflict.status == "open" and conflict.resolution == "retrying":
        return ("theirs",)  # on its way: only letting it go is left to choose
    takes = _TAKES.get(conflict.kind, ("theirs",))
    if conflict.entity_type == "record":
        return takes
    return tuple(t for t in takes if t not in _RECORD_ONLY)


def _retry_pause(retries: int) -> timedelta:
    """How long a refused change waits before it is sent again by itself: 15
    minutes, then four times as long each time, up to a day."""
    return min(timedelta(days=1), timedelta(minutes=15) * 4 ** min(retries, 6))


def _refused_code(result: Any) -> str | None:
    """Why the authority refused (`REFUSAL_*`), when it said: absent from an
    older one, whose refusals are then never sent again by themselves."""
    for problem in result.conflicts or []:
        if problem.get("code"):
            return str(problem["code"])
    return None


def _refused_field(result: Any) -> str | None:
    """The field a refusal names (`data.<field id>`), if the authority said."""
    for problem in result.conflicts or []:
        if problem.get("field"):
            return problem["field"]
    return None


def _waits_on(
    placed: tuple[uuid.UUID, uuid.UUID | None],
    above: set[uuid.UUID],
    trails: dict[uuid.UUID, set[uuid.UUID]],
) -> bool:
    """Whether a record placed here (itself, its parent) is, or sits beneath, a
    record with an unsent change (`above`), given the records above each of them
    (`trails`): the one rule `_waits`, `_waits_many` and `_run_states` share."""
    return any(
        i in above or bool(trails.get(i, set()) & above)
        for i in placed
        if i is not None
    )


def _sits_under(kind: str, snap: dict[str, Any]) -> str | None:
    """The id of the thing of the same kind that `snap` can't exist without:
    a record's parent record, a schema's parent schema."""
    key = {"record": "parent_record_id", "schema": "parent_id"}.get(kind)
    return snap.get(key) if key else None


def _field_id(conflict: SyncConflictDTO) -> str | None:
    """The field id a conflict is about (`data.<field id>`), if it is about one."""
    top, _, sub = (conflict.field or "").partition(".")
    return sub if top == "data" and sub else None


class _NotYet(Exception):
    """Held changes that must stay held a little longer (`_catch_up`)."""


class _Counting:
    """A file being uploaded, telling `on_bytes` how many bytes each read took
    (and taking them back when it is read again from the start)."""

    def __init__(self, f: BinaryIO, on_bytes: Callable[[int], None] | None) -> None:
        self._f = f
        self._on_bytes = on_bytes or (lambda _: None)

    def read(self, size: int = -1) -> bytes:
        data = self._f.read(size)
        self._on_bytes(len(data))
        return data

    def tell(self) -> int:
        return self._f.tell()

    def seek(self, offset: int, whence: int = 0) -> int:
        before = self._f.tell()
        after = self._f.seek(offset, whence)
        self._on_bytes(after - before)
        return after


def _counted(
    chunks: Iterator[bytes], on_bytes: Callable[[int], None] | None
) -> Iterator[bytes]:
    """The chunks, telling `on_bytes` how many bytes each brought."""
    for chunk in chunks:
        if on_bytes:
            on_bytes(len(chunk))
        yield chunk


def _check_address(url: str) -> None:
    """An authority is reached over HTTPS or SSH: an invite and a session token
    travel in requests, readable by anyone on the network over plain HTTP.
    Plain HTTP is left for this machine itself (tests, a local authority)."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" and parts.hostname:
        return
    if parts.scheme == ssh_tunnel.SCHEME:
        ssh_tunnel.SshAddress.parse(url)  # says what is wrong with it
        return
    if parts.scheme == "http" and parts.hostname and is_loopback(parts.hostname):
        return
    raise SyncError(
        "The address must start with https:// or ssh:// (http:// only for this "
        "computer)",
        retryable=False,
    )
