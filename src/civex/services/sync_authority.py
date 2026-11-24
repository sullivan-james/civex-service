"""The authority: the one copy of a project that settles what is true.

Devices send the changes they made; the authority checks each against what it
holds, merges it (see `domain/merge`), numbers what it accepts and serves
everyone's changes back in that order. Nothing a device says about *when* or
*which device* is trusted: the order is the authority's, and the device is the
one the caller's credentials prove (`Principal`, from an `Authenticator`).

Sending a change twice is harmless: each is recorded by its id, and a repeat is
answered with the first answer. A change that cannot be taken yet (a file has
not arrived) is neither recorded nor refused, and is sent again later.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from functools import wraps

import uuid
from types import SimpleNamespace
from datetime import datetime, timezone
from typing import Any, cast

from civex import __version__
from civex.domain import hlc
from civex.domain.audit_diff import (
    AFTER,
    BEFORE,
    PLACEMENT_KEYS,
    apply_delta,
    identity,
)
from civex.domain.exceptions import ValidationError
from civex.domain.permissions import FILE_UNAVAILABLE, file_changes
from civex.domain.merge import LIFECYCLE_KEYS, DERIVED_KEYS, merge
from civex.domain.permissions import ReadScope
from civex.services.sync_scope import FeedShaper
from civex.domain.sync_page import json_size, take
from civex.domain.sync import (
    APPLIED,
    CAPABILITIES,
    CONFLICT,
    DEFERRED,
    ENTITY_ORDER,
    MERGED,
    NOT_SYNCED_KINDS,
    NOT_SYNCED_MESSAGE,
    SCOPED_PROTOCOL,
    PROTOCOL_MAX,
    PROTOCOL_RETIRING,
    PROTOCOL_MIN,
    REFUSAL_INVALID,
    REFUSAL_NOT_SYNCED,
    REFUSAL_PERMISSION,
    REJECTED,
    FeedPage,
    Hello,
    OpResult,
    PushResult,
    SnapshotPage,
    Authenticator,
    Principal,
    SyncEntry,
    SyncPolicy,
    problem_with,
    snapshot_cursor,
)
from civex.repositories.protocols import ObjectStore, SyncRepository
from civex.services.cascades import States, changed_records, record_states
from civex.services.project_rules import ProjectRules
from civex.services.record_service import IncomingCache, RecordService
from civex.services.sync_applier import SyncApplier, stamp_of

FEED_MAX = 500
# The most raw entries one request to a restricted device looks at, whatever it
# may see of them (`feed`).
FEED_SCAN_MAX = 2000
SNAPSHOT_MAX = 500
PUSH_MAX = 500
# How many changes' records one read of what a push asks of them covers.
PREFETCH_MAX = 150


log = logging.getLogger(__name__)


def _whole_project(method: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(method)
    def run(self: SyncAuthorityService, *args: Any, **kwargs: Any) -> Any:
        with self._unscoped():
            return method(self, *args, **kwargs)

    return run


class SyncAuthorityService:
    def __init__(
        self,
        repo: SyncRepository,
        applier: SyncApplier,
        files: ObjectStore,
        records: RecordService,
        rules: ProjectRules,
        authenticator: Authenticator,
        policy: SyncPolicy | None = None,
        capabilities: tuple[str, ...] = CAPABILITIES,
        notes: Any = None,
        unscoped: Callable[[], AbstractContextManager[None]] | None = None,
        readable: Callable[[str], bool] | None = None,
        sees: Callable[[Any], bool] | None = None,
        scope: Callable[[], ReadScope] | None = None,
    ) -> None:
        self._repo = repo
        # Whether the device may see a collection, None when it may see all.
        self._sees = sees
        # Whether a file may be given to this device, None when it may have
        # every one: a file it may not read is neither cited by it nor said to
        # be here (`missing_files`).
        self._readable = readable
        # Lifts the host's limit on which collections a query can see, for the
        # work that settles a push or serves a device: those see the whole
        # project and ask `policy` about each thing, never the query layer.
        self._unscoped = unscoped or nullcontext
        # Which collections the caller may read (everything when not given).
        self._scope = scope or (lambda: ReadScope())
        # NoteService: where a pushed note's record is, and whether its text
        # is one a person's note could have.
        self._notes = notes
        # The optional features this authority offers (`Hello.capabilities`):
        # what every authority does, plus what its host adds (`direct_files`
        # when its store hands out presigned URLs).
        self._capabilities = capabilities
        self._authenticator = authenticator
        # What each caller may change; None: every change a rule allows.
        self._policy = policy
        self._applier = applier
        self._files = files
        # What a project must still be after a change, asked of what it touched
        # (a change from elsewhere was checked against what that device held).
        self._rules = rules
        # The things the action being settled has entries for itself.
        self._covered: set[tuple[str, uuid.UUID]] = set()
        # What the push being settled has read (see `RecordService.incoming_cache`),
        # for the changes `_take` settles one at a time; None outside a push.
        self._cache: IncomingCache | None = None
        # Whether runs of new records are written in bulk (`_fast`); off, every
        # change is settled on its own, as the tests compare.
        self._bulk = True
        # The rules a record must satisfy are the record service's, not copied
        # here: a change from a device is held to what a person's edit is.
        self._records = records

    # ------------------------------------------------------------------
    # Who is calling
    # ------------------------------------------------------------------

    def authenticate(self, token: str) -> Principal:
        return self._authenticator.authenticate(token)

    # ------------------------------------------------------------------
    # Joining
    # ------------------------------------------------------------------

    def hello(self, who: Principal, protocol: int) -> Hello:
        scope = self._scope()
        with self._unscoped():
            meta = self._repo.meta()
            head = self._head()
            # Whether it holds anything at all is about the project, not about
            # what this caller may see of it: a caller who sees nothing must
            # not take an authority that holds data for an empty one. Asked of
            # a caller who sees it all by the counts below; of any other by
            # looking for one thing of any kind, never by counting twice.
            holds = None if scope.unrestricted else self._repo.holds_anything()
        # What this caller may see of it (the session is limited to that).
        counts = self._repo.entity_counts()
        empty = (sum(counts.values()) == 0) if holds is None else not holds
        readable = None
        if protocol >= SCOPED_PROTOCOL:
            # Which collections this caller may read, so a device can tell when
            # it has been given one it does not hold. Their creation numbers
            # are found by key (their own history), never by scanning it.
            ids = self._repo.all_ids("dataset")
            with self._unscoped():
                made = self._repo.dataset_created_seqs(ids)
            readable = [{"id": i, "seq": made.get(i, 0)} for i in sorted(ids)]
        return Hello(
            protocol_version=protocol,
            project_id=meta.project_id,
            head_seq=head,
            empty=empty,
            seeded_by=meta.seeded_by,
            device_name=who.name,
            counts=counts,
            feed_floor=meta.feed_floor,
            protocol_min=PROTOCOL_MIN,
            protocol_max=PROTOCOL_MAX,
            server_version=__version__,
            capabilities=list(self._capabilities),
            protocol_retiring=PROTOCOL_RETIRING,
            readable=readable,
        )

    def snapshot(
        self,
        kind: str,
        after: str | None,
        limit: int,
        dataset: uuid.UUID | None = None,
        left_after: int | None = None,
    ) -> SnapshotPage:
        """A page of one kind as it is now, for a device joining, continuing
        after the cursor `after` (None: the first page). `head_seq` is read
        first: what changes while the device reads is in the feed past it.
        What the caller may not read is not in it (the session is limited to
        what they may see), whole pages of it included; `dataset` asks for one
        collection's own things (a collection newly readable), or with
        `left_after` those of its records that have since left it."""
        if kind not in ENTITY_ORDER and kind not in NOT_SYNCED_KINDS:
            raise ValidationError(f"Unknown kind '{kind}'")
        with self._unscoped():
            head = self._head()
        if kind in NOT_SYNCED_KINDS:
            # Asked for by a device on protocol 5 or older, which still lists
            # releases among what it joins with: there are none to give.
            return SnapshotPage(kind, [], False, head, None)
        limit = max(1, min(limit, SNAPSHOT_MAX))
        if left_after is not None:
            # Never before what this authority still holds history of: a request
            # to look back over all of it is not a thing a device needs.
            left_after = max(left_after, self._repo.meta().feed_floor)
        if dataset is not None and not self._scope().sees(dataset):
            # A collection the caller may not read is asked about like one that
            # is not there: an empty page, never what once lived in it.
            return SnapshotPage(kind, [], False, head, None)
        try:
            items = self._repo.snapshots_page(
                kind, after, limit + 1, dataset, left_after
            )
        except ValueError as e:
            raise ValidationError(f"Not a page cursor: {after!r}") from e
        # By count and by bytes, `more` decided with the feed's (sync_page).
        page, more = take(items, [json_size(i) for i in items], limit)
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

    @_whole_project
    def feed(self, after: int, limit: int = 200) -> FeedPage:
        head = self._head()
        limit = max(1, min(limit, FEED_MAX))
        scope = self._scope()
        if scope.unrestricted:
            entries, more = self._repo.entries_after(after, limit)
            return FeedPage(entries, head, more)
        shaper = FeedShaper(
            scope,
            self._records.records_repo.dataset_of,
            lambda record: self._repo.snapshot("record", record),
            self._repo.note_snapshots,
            self._repo.collection_trails,
            self._repo.placed_from(),
        )
        # What the device may not see is looked past, but only so far in one
        # request: a long hidden run is answered with an empty page that says
        # how far was looked (`through`, `more`), and the device asks again
        # from there, so no request scans without end.
        through = after
        scanned = 0
        while scanned < FEED_SCAN_MAX:
            # Always in whole batches, whatever the page asked for: a small
            # `limit` must not turn one request into thousands of lookups.
            raw, more = self._repo.entries_after(through, FEED_MAX)
            if raw:
                through = raw[-1].hub_seq or through
            scanned += len(raw)
            kept: list[SyncEntry] = []
            for i, group in enumerate(shaper.shape_each(raw)):
                if (
                    kept
                    and len(kept) + len(group) > limit
                    and (not raw[i].op or raw[i].op != raw[i - 1].op)
                ):
                    # The page asked for is full: it ends before this change (an
                    # action is never cut), and the device asks again from there.
                    return FeedPage(kept, head, True, raw[i - 1].hub_seq or through)
                kept += group
            if kept or not more:
                return FeedPage(kept, head, more, through)
        return FeedPage([], head, True, through)

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    def missing_files(self, shas: list[str]) -> list[str]:
        """Those not here, a file the device may not read counted as not here:
        it is asked for like any other, and nothing says one is held."""
        readable = self._readable
        wanted = list(dict.fromkeys(shas))
        held = self._files.exists_many(wanted)  # one lookup, not one each
        return [
            s
            for s in wanted
            if s not in held or (readable is not None and not readable(s))
        ]

    # ------------------------------------------------------------------
    # Accepting changes
    # ------------------------------------------------------------------

    @_whole_project
    def push(self, who: Principal, entries: list[SyncEntry]) -> PushResult:
        """Settle each change, in the order sent. Stops at the first that has
        to wait (later ones may depend on it); those are simply not answered.

        One push at a time: each change is merged with what is held and the
        whole thing written back, so two pushes reading the same thing at once
        would each overwrite the other. The feed's counter is taken first and
        held until the answer is saved, which makes every other push wait."""
        self._repo.lock_feed()
        self._head()  # number this instance's own changes first
        results: list[OpResult] = []
        taken = _at_most(entries, PUSH_MAX)
        # What the push will ask about one change at a time (was it sent
        # before; the record it names) is read once, now the feed is locked.
        cache = self._records.incoming_cache()
        # (a caller who sees only some collections has its own view of the
        # records: asked each time, never from what was read at once)
        cache.use_records = self._scope().unrestricted
        self._cache = cache
        position = 0
        try:
            self._settle_push(who, taken, results, cache, position)
        finally:
            self._cache = None
        self._log_push(who, entries, results)
        return PushResult(results, self._repo.head_seq())

    def _settle_push(
        self,
        who: Principal,
        taken: list[SyncEntry],
        results: list[OpResult],
        cache: IncomingCache,
        position: int,
    ) -> None:
        with self._repo.push_scope(taken):
            run: list[_Fast] = []
            for action in _actions(taken):
                if self._bulk and len(action) == 1 and cache.stale:
                    # What the changes to come ask of the records is read
                    # together (again, after something else wrote some).
                    self._records.prefetch_incoming(
                        cache,
                        self._next_creates(taken[position:]),
                    )
                position += len(action)
                fast = (
                    self._fast(who, action[0], run, cache)
                    if self._bulk and len(action) == 1
                    else None
                )
                if fast is not None:
                    run.append(fast)
                    continue
                # Anything else is settled one at a time, after what came
                # before it (it may depend on it) and in the order sent.
                settled = self._flush_run(who, run)
                if not any(r.status == DEFERRED for r in settled):
                    settled += (
                        [self._settle(who, action[0])]
                        if len(action) == 1
                        else self._settle_action(who, action)
                    )
                    if len(action) == 1 and settled[-1].replayed:
                        pass  # answered from before: nothing was written
                    elif len(action) == 1 and action[0].entity_type == "record":
                        cache.clear_records()  # (a record changes no schema)
                    else:
                        cache.clear()  # it may have changed a schema or collection
                    if len(action) > 1 or not _plain_record_write(action[0]):
                        # What it reached beyond the one thing it names (children
                        # deleted, a collection's records) is written in bulk, past
                        # the records this push holds: they are read again.
                        self._repo.forget_held()
                results += settled
                if any(r.status == DEFERRED for r in settled):
                    break
            else:
                results += self._flush_run(who, run)

    def _next_creates(self, rest: list[SyncEntry]) -> list[dict[str, Any]]:
        """The states of the next records the push may make new (a stretch of
        them: what is read for the push is read again after a change settled
        alone), leaving out those already held or answered."""
        out: list[dict[str, Any]] = []
        for e in rest:
            if (
                _makes(e)
                and e.new_data
                and self._repo.record_absent(e.entity_id)
                and self._repo.get_op(e.id) is None
            ):
                out.append(e.new_data)
                if len(out) >= PREFETCH_MAX:
                    break
        return out

    def _fast(
        self,
        who: Principal,
        entry: SyncEntry,
        run: list[_Fast],
        cache: IncomingCache,
    ) -> _Fast | None:
        """A record made new, which goes in with the rest of its run in bulk
        (`_flush_run`): None unless it is certain to be taken as it is, with
        nothing but its own rows written, and nothing to read that an earlier
        entry of the run has yet to write. Whatever is not certain is settled
        by `_settle` as before, so this only looks (it writes nothing) and any
        doubt is answered there."""
        if (
            entry.entity_type != "record"
            or entry.action != "create"
            or entry.delta is not None
            or entry.op
            or entry.batch is not None
            or not entry.new_data
            or not self._repo.record_absent(entry.entity_id)
            or self._repo.get_op(entry.id) is not None
            or any(
                f.entry.id == entry.id or f.entry.entity_id == entry.entity_id
                for f in run
            )
        ):
            return None
        stamp = entry.hlc
        if stamp is not None and hlc.is_ahead(stamp, _now_ms()):
            return None  # the authority issues one: that is for `_settle`
        final = dict(entry.new_data)
        try:
            if problem := self._problem(who, entry):
                # Refused whatever else is held: answered now, in its place in
                # the run (nothing in the run can change that answer).
                return _Fast(
                    entry, None, self._refuse(who, entry, problem[0], code=problem[1])
                )
            if final.get("deleted_at"):
                return None
            shape = self._records.shape_of(final, cache)
            if shape is None:
                return None
            marks = self._records.unique_marks(final, shape)
            if not cache.use_records and (
                final.get("parent_record_id")
                or marks
                or self._records.cites_records(final, shape)
            ):
                return None  # (what it sits under, points at or must differ from
                # is read through the caller's own view)
            if any(m in cache.made for m in marks):
                return None  # a record of this push shares its key: settled alone
            if final.get("parent_record_id"):
                self._check_parent(final, cache)
                if self._records.placed_with_parent(final, cache) is not final:
                    return None  # it follows its parent to another collection
            self._records.check_incoming(final, None, cache)
        except (ValidationError, ValueError, TypeError, KeyError, AttributeError):
            return None
        # Later changes of the push are judged with this one there (it is
        # written, in its place, before any of them is settled).
        self._records.note_made(cache, final, shape)
        return _Fast(entry, final)

    def _flush_run(self, who: Principal, run: list[_Fast]) -> list[OpResult]:
        """Write a run of records `_fast` took, in one go: numbered together,
        their rows (records, history, the answers kept) one statement each. If
        the database refuses any, none of the run is written and each is
        settled on its own, as it would have been."""
        if not run:
            return []
        items, run[:] = list(run), []
        taken = [f for f in items if f.refused is None]
        if not taken:
            return [f.refused for f in items if f.refused]
        try:
            with self._repo.savepoint():
                self._repo.sequence_local_entries()
                first = self._repo.reserve_hub_seqs(len(taken))
                self._seed(who.device_id)
                answered = [
                    OpResult(f.entry.id, APPLIED, None, [], first + k)
                    for k, f in enumerate(taken)
                ]
                self._repo.insert_records(
                    [f.final for f in taken if f.final is not None]
                )
                self._repo.insert_entries(
                    [
                        (self._stored(who, f.entry, f.final), first + k)
                        for k, f in enumerate(taken)
                    ]
                )
                self._repo.save_ops(
                    [(f.entry, r) for f, r in zip(taken, answered)],
                    who.device_id,
                    who.name,
                )
            done = iter(answered)
            return [f.refused or next(done) for f in items]
        except (ValidationError, ValueError, TypeError, KeyError, AttributeError):
            # (the savepoint undid the run, and the records this push held)
            self._repo.forget_held()
            if self._cache is not None:
                self._cache.clear_records()  # (what it noted as made is not)
            for f in taken:
                self._repo.drop_op(f.entry.id)  # (answers kept before it failed)
            settled: list[OpResult] = []
            for f in items:
                settled.append(f.refused or self._settle(who, f.entry))
                if settled[-1].status == DEFERRED:
                    break
            return settled

    def _stored(
        self, who: Principal, entry: SyncEntry, final: dict[str, Any] | None
    ) -> SyncEntry:
        """A change as `_write_entries` keeps it."""
        stored = _as_placed(entry, None, final)
        return SyncEntry(
            id=entry.id,
            action=entry.action,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            old_data=stored.old_data,
            new_data=stored.new_data,
            timestamp=entry.timestamp,
            actor=_author(who, entry),
            device=who.name,
            device_id=who.device_id,
            hlc=entry.hlc,
            batch=entry.batch,
            delta=stored.delta,
        )

    @staticmethod
    def _log_push(
        who: Principal, entries: list[SyncEntry], results: list[OpResult]
    ) -> None:
        """One line per push saying what became of the changes, and one per
        change that was not simply taken, naming the thing."""
        counts: dict[str, int] = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
        summary = ", ".join(f"{n} {s}" for s, n in sorted(counts.items())) or "nothing"
        log.info("sync push from %s: %d sent, %s", who.name, len(entries), summary)
        by_id = {e.id: e for e in entries}
        for r in results:
            if r.status in ("conflict", "rejected", "deferred", "merged"):
                e = by_id.get(r.op_id)
                what = f"{e.entity_type} {e.entity_id}" if e else str(r.op_id)
                log.warning(
                    "sync push from %s: %s %s%s",
                    who.name,
                    what,
                    r.status,
                    f" ({r.message})" if r.message else "",
                )

    def _settle(self, who: Principal, entry: SyncEntry) -> OpResult:
        prior = self._repo.get_op(entry.id)
        if prior is not None:
            # sent before: the same answer, nothing done again
            return dataclasses.replace(prior, replayed=True)
        self._covered = {(entry.entity_type, entry.entity_id)}
        if problem := self._problem(who, entry):
            return self._refuse(who, entry, problem[0], code=problem[1])
        try:
            with self._repo.savepoint():
                result = self._take(who, entry)
                self._rules.check(_changed([entry]))
        except ValidationError as e:
            head = self._applier.head(entry.entity_type, entry.entity_id)
            if isinstance(e, _Denied):
                return self._refuse(who, entry, str(e), code=REFUSAL_PERMISSION)
            if (
                head is not None
                and (entry.entity_type != "record" or _moves(entry, head))
                and not self._unseen(entry)
            ):
                # A record a refused change would have moved is put back too:
                # left where the device put it, it would sit under a parent
                # that is somewhere else.
                return self._put_back(who, entry, str(e))
            return self._refuse(who, entry, str(e), getattr(e, "path", None))
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            # A value inside the snapshots that can't be read (an id or a date
            # that isn't one). Refused by itself, so it can't hold up the rest
            # of the push or be sent again for ever.
            return self._refuse(who, entry, f"A value is not valid: {e}")
        self._repo.save_op(entry, result, who.device_id, who.name)
        return result

    def _problem(
        self, who: Principal, entry: SyncEntry
    ) -> tuple[str, str | None] | None:
        """Why a change can't be taken whatever is held, with the code of the
        refusal (`REFUSAL_INVALID` for its shape, `REFUSAL_PERMISSION` for what
        the caller may change: a person may be given that later)."""
        if entry.entity_type in NOT_SYNCED_KINDS:
            # Whatever the protocol the device speaks: a release is published
            # on a host, so one sent here is never taken (and never sent again).
            return NOT_SYNCED_MESSAGE, REFUSAL_NOT_SYNCED
        if shape := problem_with(entry):
            return shape, REFUSAL_INVALID
        if self._policy and (denied := self._policy.refuses(who, entry)):
            return denied, REFUSAL_PERMISSION
        if self._readable is not None and entry.entity_type == "record":
            # Citing a file makes it the record's, readable by whoever reads
            # the record: only one this device could download may be cited.
            added, _ = file_changes(entry)
            if any(not self._readable(sha) for sha in sorted(added)):
                return FILE_UNAVAILABLE, REFUSAL_PERMISSION
        if (
            entry.entity_type == "record"
            and entry.action in ("update", "restore", "delete", "purge")
            and self._unseen(entry)
        ):
            # Held here, where the device may not look: answered as the same
            # change to a record that is not here at all, in the same words and
            # with the same (absent) code.
            return NOT_HERE, None
        if (
            self._policy
            and entry.entity_type == "dataset"
            and entry.action == "create"
            and self._repo.existing_ids("dataset", {str(entry.entity_id)})
        ):
            # A "create" of a collection that is already here is a change to
            # it: judged as one, so it cannot be used to reach one hidden from
            # the device.
            as_change = dataclasses.replace(entry, action="update")
            if denied := self._policy.refuses(who, as_change):
                return denied, REFUSAL_PERMISSION
        if self._policy and entry.entity_type == "note":
            # A note already held here is judged where it is, not where the
            # device says its record is (or it could move a hidden note onto a
            # record it may read).
            on = self._repo.note_record_id(entry.entity_id)
            where = self._records.records_repo.dataset_of(on) if on else None
            if where is not None:
                held_note = cast(Any, SimpleNamespace)(
                    entity_type="note",
                    action=entry.action,
                    new_data={"dataset_id": str(where)},
                    old_data=None,
                )
                if denied := self._policy.refuses(who, held_note):
                    return denied, REFUSAL_PERMISSION
        if self._policy and entry.entity_type == "record":
            # Where the record is *here* counts as much as where the device
            # says it is: it may not take over or overwrite a record of a
            # collection it is not allowed into by naming another.
            held = (
                None
                if self._repo.record_absent(entry.entity_id)
                else self._records.records_repo.dataset_of(entry.entity_id)
            )
            if held is not None:
                # The same change judged where the record is held: its files
                # and its removal count there, and where the delta says it
                # goes is asked about separately (`refuses` above).
                delta = {
                    k: v for k, v in (entry.delta or {}).items() if k != "dataset_id"
                }
                held_entry = cast(Any, SimpleNamespace)(
                    entity_type="record",
                    action=entry.action,
                    new_data={
                        "dataset_id": str(held),
                        "data": (entry.new_data or {}).get("data"),
                    },
                    old_data=entry.old_data and {"data": entry.old_data.get("data")},
                    delta=delta or None,
                )
                if denied := self._policy.refuses(who, held_entry):
                    return denied, REFUSAL_PERMISSION
        return None

    def _settle_action(self, who: Principal, action: list[SyncEntry]) -> list[OpResult]:
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
            # sent before
            return [dataclasses.replace(p, replayed=True) for p in priors if p]
        self._covered = {(e.entity_type, e.entity_id) for e in action}
        for entry in action:
            if problem := self._problem(who, entry):
                return self._refuse_action(who, action, problem[0], code=problem[1])
        # What one of its entries writes is read by the next: nothing is
        # answered from what the push read before.
        cache, self._cache = self._cache, None
        try:
            with self._repo.savepoint():
                results = [self._take(who, e) for e in action]
                failed = [r for r in results if r.status not in (APPLIED, MERGED)]
                if failed:
                    raise _NotWhole(results)
                self._rules.check(_changed(action))
        except _NotWhole as e:
            if all(_kept_from_delete(e.results, action)):
                return self._keep_instead_of_delete(who, action, e.results)
            why = next((r.message for r in e.results if r.message), None)
            return self._refuse_action(
                who,
                action,
                why or "Something it changes was changed on the server meanwhile",
            )
        except ValidationError as e:
            return self._refuse_action(
                who,
                action,
                str(e),
                code=REFUSAL_PERMISSION if isinstance(e, _Denied) else None,
            )
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            return self._refuse_action(who, action, f"A value is not valid: {e}")
        finally:
            self._cache = cache
        for entry, result in zip(action, results):
            self._repo.save_op(entry, result, who.device_id, who.name)
        return results

    def _refuse_action(
        self,
        who: Principal,
        action: list[SyncEntry],
        why: str,
        code: str | None = None,
    ) -> list[OpResult]:
        message = f"Part of one change that could not go in whole: {why}"
        return [
            self._put_back(who, entry, message)
            if self._applier.head(entry.entity_type, entry.entity_id) is not None
            and not self._unseen(entry)
            else self._refuse(who, entry, message, code=code)
            for entry in action
        ]

    def _unseen(self, entry: SyncEntry) -> bool:
        """Whether the thing an entry is about is held here in a collection the
        device may not see. It is answered as a thing that is not here at all
        (refused, never put back), so that what a refusal does with an entry
        does not tell the device which ids exist."""
        if self._sees is None:
            return False
        kind = entry.entity_type
        if kind == "dataset":
            where: Any = entry.entity_id
        elif kind == "record":
            where = self._records.records_repo.dataset_of(entry.entity_id)
        elif kind == "note":
            on = self._repo.note_record_id(entry.entity_id)
            where = self._records.records_repo.dataset_of(on) if on else None
        else:
            return False
        return where is not None and not self._sees(where)

    def _put_back(self, who: Principal, entry: SyncEntry, why: str) -> OpResult:
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
        seq = self._write_entries(who, entry, head, head, conflicts, None)
        result = OpResult(entry.id, CONFLICT, why, conflicts, seq)
        self._repo.save_op(entry, result, who.device_id, who.name)
        return result

    def _keep_instead_of_delete(
        self,
        who: Principal,
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
            seq = self._write_entries(who, entry, head, head, conflicts, None)
            result = OpResult(entry.id, CONFLICT, message, conflicts, seq)
            self._repo.save_op(entry, result, who.device_id, who.name)
            results.append(result)
        return results

    def _refuse(
        self,
        who: Principal,
        entry: SyncEntry,
        why: str,
        field: str | None = None,
        code: str | None = None,
    ) -> OpResult:
        """Answer that a change can never be taken. The answer is remembered, so
        a repeat gets it again; the device that sent it keeps what it made and
        shows it for review (conflicts are held by the device whose change did
        not go in, not here). `field` is the value it was refused for, when it
        was one (`data.<field id>`), so the device can show that field to fix.
        `code` says what kind of refusal it is (`REFUSAL_PERMISSION` can be
        sent again once the device may; anything else would only fail again). It
        travels inside the refusal's `conflicts` item, which older devices
        ignore, so no protocol version changes."""
        item: dict[str, Any] = {"kind": "rejected", "field": field}
        if code:
            item["code"] = code
        result = OpResult(
            entry.id,
            REJECTED,
            why,
            [item] if (field or code) else [],
        )
        self._repo.save_op(entry, result, who.device_id, who.name)
        return result

    def _check_parent(
        self, state: dict[str, Any], cache: IncomingCache | None = None
    ) -> None:
        """The record a pushed record sits under must be there as the caller
        finds it: one the caller cannot see is refused in the same words as one
        that does not exist (never taken in, never an error at commit)."""
        parent = state.get("parent_record_id")
        if not parent:
            return  # (a deleted record under a parent needs it just the same)
        try:
            wanted = uuid.UUID(str(parent))
        except ValueError:
            raise ValidationError(PARENT_GONE) from None
        found: Any
        if cache is not None and wanted in cache.places:
            found = cache.places[wanted]  # (the caller sees all: use_records)
        else:
            with self._records.as_caller():
                found = self._records.records_repo.get_by_id(
                    wanted, include_deleted=True
                )
        if found is None:
            raise ValidationError(PARENT_GONE)

    def _check_placement(
        self, who: Principal, entry: SyncEntry, placed: dict[str, Any]
    ) -> None:
        """A record sits in its parent's collection, so where it is settled can
        differ from where the device said: that collection is judged as a write
        and a read, as the one the device named was."""
        if not self._policy:
            return
        settled = cast(Any, SimpleNamespace)(
            entity_type="record",
            action=entry.action,
            new_data={"dataset_id": str(placed.get("dataset_id")), "data": None},
            old_data=None,
            delta=None,
        )
        if denied := self._policy.refuses(who, settled):
            raise _Denied(denied)

    def _take(self, who: Principal, entry: SyncEntry) -> OpResult:
        """Merge the change into what is held, write it, and record it."""
        kind, eid = entry.entity_type, entry.entity_id
        head = self._applier.head(kind, eid)
        if (
            kind == "record"
            and head is None
            and entry.action in ("delete", "purge", "restore")
            and self._sees is not None
        ):
            # For a device limited to some collections, a record that is not
            # here is refused as one that is held out of its sight is: the two
            # are told apart by nothing in the answer.
            raise ValidationError(NOT_HERE)
        cascade = self._cascade_before(entry, head)
        conflicts: list[dict[str, Any]] = []
        final: dict[str, Any] | None = None  # the state the thing ends in, if it exists
        incoming: dict[str, Any] | None = None  # what the change made, as a whole
        message: str | None = None

        if entry.action in ("create", "update", "restore"):
            if head is None:
                if entry.action == "update" or entry.delta is not None:
                    raise ValidationError(NOT_HERE)
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
                if head is None or str(head.get("parent_record_id") or "") != str(
                    final.get("parent_record_id") or ""
                ):
                    self._check_parent(final, self._cache)
                placed = self._records.placed_with_parent(final, self._cache)
                if placed is not final:
                    self._check_placement(who, entry, placed)
                final = placed
                self._records.check_incoming(final, head, self._cache)
            elif kind == "note" and self._notes is not None:
                self._check_note(who, final)
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

        if cascade is not None or not _plain_record_write(entry):
            # A delete, restore or move reaches other records in bulk statements
            # the session doesn't see: what this push holds is read again.
            self._repo.forget_held()
        self._seed(who.device_id)
        seq = self._write_entries(who, entry, head, final, conflicts, incoming)
        if cascade is not None:
            self._write_cascade(entry, cascade)
            self._repo.forget_held()
        status = self._status(entry, final, conflicts, incoming)
        if conflicts and any(c["kind"] == "edit_vs_delete" for c in conflicts):
            message = next(
                c.get("message") for c in conflicts if c["kind"] == "edit_vs_delete"
            )
        return OpResult(entry.id, status, message, conflicts, seq)

    def _check_note(self, who: Principal, state: dict[str, Any]) -> None:
        """A note goes in only on a record held here, with text a person's note
        could have, from a caller who may write records in that record's
        collection (`action_for` can't know it from the note alone)."""
        collection = self._notes.collection_of(state)
        if self._policy is not None:
            refusal = self._policy.refuses(
                who,
                cast(Any, SimpleNamespace)(
                    entity_type="note",
                    action="update",
                    new_data={"dataset_id": str(collection)},
                    old_data=None,
                ),
            )
            if refusal:
                raise ValidationError(refusal)

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
        who: Principal,
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
        stored = _as_placed(entry, head, final)
        sent = SyncEntry(
            id=entry.id,
            action=entry.action,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            old_data=stored.old_data,
            new_data=stored.new_data,
            timestamp=entry.timestamp,
            # Which device sent it is what the token says, never what was
            # claimed; who made it is `_author`.
            actor=_author(who, entry),
            device=who.name,
            device_id=who.device_id,
            hlc=self._believable(entry.hlc),
            batch=entry.batch,
            delta=stored.delta,
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


PARENT_GONE = "The record it sits under is not here."
NOT_HERE = "It is not on the server (deleted for good there, or never taken)"


@dataclasses.dataclass
class _Fast:
    """A record `SyncAuthorityService._fast` will take: the change, and the
    state it makes."""

    entry: SyncEntry
    final: dict[str, Any] | None
    refused: OpResult | None = None  # or, if it was refused, the answer


class _Denied(ValidationError):
    """A change refused for what the caller may do (not for its shape)."""


def _as_placed(
    entry: SyncEntry, head: dict[str, Any] | None, final: dict[str, Any] | None
) -> SyncEntry:
    """A record change as it is stored: naming the collections the authority
    actually had the record in before and after it, not the ones the device
    claimed (a stale or forged claim would otherwise be what everything that
    reads the feed, a device limited to some collections included, judges the
    change by)."""
    if entry.entity_type != "record":
        return entry
    before = str(head["dataset_id"]) if head and head.get("dataset_id") else None
    settled = final if final is not None else head
    after = (
        str(settled["dataset_id"]) if settled and settled.get("dataset_id") else None
    )
    if before is None and after is None:
        return entry

    def named(data: dict[str, Any] | None, where: str | None) -> dict[str, Any] | None:
        if data is None or where is None:
            return data
        return {**data, "dataset_id": where}

    delta = entry.delta
    if delta is not None:
        delta = {k: v for k, v in delta.items() if k != "dataset_id"}
        if before is not None and after is not None and before != after:
            delta["dataset_id"] = {"before": before, "after": after}
    return dataclasses.replace(
        entry,
        old_data=named(entry.old_data, before or after),
        new_data=named(entry.new_data, after or before),
        delta=delta,
    )


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


def _makes(entry: SyncEntry) -> bool:
    """A record made new, as `_fast` takes one: what it asks of the records
    is read before the push settles it."""
    return (
        entry.entity_type == "record"
        and entry.action == "create"
        and isinstance(entry.new_data, dict)
        and not entry.new_data.get("deleted_at")
    )


def _plain_record_write(entry: SyncEntry) -> bool:
    """A record made or edited: it reaches no other record by itself."""
    return entry.entity_type == "record" and entry.action in ("create", "update")


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


def _moves(entry: SyncEntry, head: dict[str, Any]) -> bool:
    """Whether the change puts the record elsewhere than it is held: in another
    collection, or under another record."""
    if entry.action not in ("create", "update", "restore"):
        return False
    _, incoming = _sides(entry, head)
    for key in PLACEMENT_KEYS:
        value = incoming.get(key)
        if value is not None:
            try:
                uuid.UUID(str(value))
            except ValueError:
                return False  # not a place at all: refused as a bad value
    return any(
        str(incoming.get(key) or "") != str(head.get(key) or "")
        for key in PLACEMENT_KEYS
    )


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


def _author(who: Principal, entry: SyncEntry) -> str:
    """Who made a change: the person the authenticator proved, else the name
    the device gives (a label: a token proves a device, not a person), else
    the token's name."""
    return who.person or _claimed_author(entry.actor) or who.name


def _claimed_author(name: str | None) -> str | None:
    """The author a device gives for a change, kept as a label: trimmed and
    capped. `sync` is the authority's own mark on what it writes (and what
    conflict descriptions skip), so a device can't take it."""
    if not isinstance(name, str):
        return None
    name = name.strip()[:100]
    return name if name and name != "sync" else None
