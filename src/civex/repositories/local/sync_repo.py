"""Sync's storage: the project's identity and cursor, who may sync, what an
authority has been sent, the conflicts to review, and the history entries sync
moves. Also the one place a *snapshot* of a schema, field, collection, view or
record is read back out of the database or written into it with its own id, which
is how a change made on one machine is reproduced on another."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import (
    BigInteger,
    String,
    Uuid,
    and_,
    cast,
    delete,
    func,
    or_,
    select,
    update,
)
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from civex.db.models import (
    IgnoredMissingFile,
    StoredObject,
    SyncLoginRequest,
    AuditBatch,
    AuditLog,
    Dashboard,
    Dataset,
    RecordNote,
    Release,
    Field,
    FileReference,
    Record,
    RecordReference,
    Schema,
    ServerFile,
    ServerLack,
    SyncConflict,
    SyncDevice,
    SyncInvite,
    SyncMeta,
    SyncOp,
    View,
    _UTCDateTime,
)
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.domain.audit_diff import entry_snapshots
from civex.domain.merge import value_at
from civex.domain.sync import (
    LoginRequestDTO,
    OpResult,
    SyncBatchInfo,
    SyncConflictDTO,
    SyncDeviceDTO,
    SyncEntry,
    SyncInviteDTO,
    SyncMetaDTO,
    parse_snapshot_cursor,
    wire_state,
)
from civex.repositories.local.inventory import stored_files
from civex.repositories.local.dataset_repo import _to_dtos as _dataset_dtos
from civex.repositories.local.record_repo import _to_dto as _record_dto
from civex.repositories.local.schema_repo import _field_to_dto, _schema_to_dto
from civex.repositories.local.dashboard_repo import _to_dto as _dashboard_dto
from civex.repositories.local.note_repo import _to_dto as _note_dto
from civex.repositories.local.release_repo import _to_dto as _release_dto
from civex.repositories.local.view_repo import _to_dto as _view_dto

_MODELS: dict[str, Any] = {
    "schema": Schema,
    "field": Field,
    "dataset": Dataset,
    "view": View,
    "dashboard": Dashboard,
    "record": Record,
    "note": RecordNote,
    "release": Release,
}
# A column PostgreSQL maintains itself (a trigger), or one that is this copy's
# own (a release's place in this copy's history); never written from a snapshot.
_NOT_WRITTEN = frozenset({"search_vector", "local_seq", "indexed"})


# The order changes were made in here: the number the database gave each entry
# as it was written (`AuditLog.local_seq`), not its time, since a clock can step
# back and send a child before its parent (refused for good). Entries from
# before the number existed have none and come first, by time.
_WRITE_ORDER = (
    func.coalesce(AuditLog.local_seq, 0),
    AuditLog.timestamp,
    AuditLog.id,
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _kept_owner():  # type: ignore[no-untyped-def]
    """A file_references row whose owner keeps the file on the authority: a
    live record or a release (with `Record` outer-joined)."""
    return (
        FileReference.record_id.is_not(None) & Record.deleted_at.is_(None)
    ) | FileReference.release_id.is_not(None)


LACK_RETRY_FIRST = timedelta(minutes=10)
LACK_RETRY_MAX = timedelta(days=1)


def lack_wait(misses: int) -> timedelta:
    """How long after the `misses`th time the authority said it hasn't got a
    file before it is asked for it again."""
    return min(LACK_RETRY_FIRST * 2 ** min(max(misses, 1) - 1, 12), LACK_RETRY_MAX)


class LocalSyncRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def rollback(self) -> None:
        """Drop what the session holds that was not committed."""
        self._s.rollback()

    @contextmanager
    def savepoint(self) -> Iterator[None]:
        """Everything written inside is kept or dropped together. A rule the
        database enforces (a name already taken, a parent that is not there)
        undoes it and comes out as a ValidationError saying so; the writes
        outside, earlier in the same transaction, are untouched."""
        nested = self._s.begin_nested()
        try:
            yield
            self._s.flush()
            nested.commit()
        except (IntegrityError, DataError) as e:
            # Even when the failed flush has already ended it: until it is rolled
            # back the session refuses further work.
            nested.rollback()
            raise ValidationError(_brief(e)) from e
        except BaseException:
            nested.rollback()
            raise

    # ------------------------------------------------------------------
    # The project's sync row
    # ------------------------------------------------------------------

    def _meta_row(self) -> SyncMeta:
        row = self._s.get(SyncMeta, 1)
        if row is None:  # a database that predates the migration's insert
            row = SyncMeta(id=1, project_id=uuid.uuid4(), head_seq=0, cursor=0)
            self._s.add(row)
            self._s.flush()
        return row

    def meta(self) -> SyncMetaDTO:
        row = self._meta_row()
        return SyncMetaDTO(
            project_id=row.project_id,
            head_seq=row.head_seq,
            cursor=row.cursor,
            seeded_by=row.seeded_by,
            last_synced_at=_iso(row.last_synced_at),
            last_error=row.last_error,
            last_error_at=_iso(row.last_error_at),
            history_from=row.history_from,
            feed_floor=row.feed_floor or 0,
        )

    def set_history_from(self, seq: int | None) -> None:
        self._meta_row().history_from = seq
        self._s.flush()

    def placed_from(self) -> int:
        """The feed number up to which entries were stored before they carried
        where the authority really had the record (see `SyncMeta.placed_from`)."""
        return int(self._meta_row().placed_from or 0)

    def history_scan(self) -> int | None:
        """Where fetching the earlier history carries on from, when it has
        looked past what it holds (None: from the last entry held)."""
        found = self._meta_row().history_scan
        return None if found is None else int(found)

    def set_history_scan(self, seq: int | None) -> None:
        self._meta_row().history_scan = seq
        self._s.flush()

    def history_fetched_upto(self, upto: int) -> int:
        """The last number up to `upto` whose entry is held here: where
        fetching the history from before joining carries on from."""
        return (
            self._s.query(func.max(AuditLog.hub_seq))
            .filter(AuditLog.hub_seq <= upto)
            .scalar()
            or 0
        )

    def referenced_shas(
        self, after: str, limit: int, unconfirmed: bool = False
    ) -> list[str]:
        """Hashes of the files live records cite (a deleted record's are sent if
        it is restored) and of releases' bundles, in hash order, `limit` of them
        after `after`; `unconfirmed`: only those the authority hasn't said it
        holds. The catalog is kept up to date as records are written, so
        what a device still owes its authority is worked out from it each time
        rather than remembered."""
        return list(self._s.scalars(self._referenced_page(after, limit, unconfirmed)))

    def _referenced_page(self, after: str, limit: int, unconfirmed: bool):  # type: ignore[no-untyped-def]
        """`limit` hashes after `after`, in order. The bound is applied to the
        index on `sha256` before anything is grouped, so a page reads only its
        own stretch of the index (an ordered scan that stops at the limit),
        not every reference each time: with tens of thousands of files, a
        `DISTINCT` over all of them per page was minutes of work and tens of
        megabytes of shared memory for PostgreSQL's parallel workers."""
        sha = FileReference.sha256
        # An EXISTS per candidate row, not a join: the planner can then walk
        # the index in order and stop at the limit.
        live_owner = (
            select(Record.id)
            .where(Record.id == FileReference.record_id, Record.deleted_at.is_(None))
            .exists()
        )
        query = select(sha).where(
            sha > after,
            (FileReference.record_id.is_not(None) & live_owner)
            | FileReference.release_id.is_not(None),
        )
        if unconfirmed:
            query = query.where(
                ~select(ServerFile.sha256).where(ServerFile.sha256 == sha).exists()
            )
        return query.group_by(sha).order_by(sha).limit(limit)

    def _referenced(self):  # type: ignore[no-untyped-def]
        """The column of every file this project needs the authority to hold:
        those its live records and its releases own."""
        return (
            select(FileReference.sha256.label("sha256"))
            .outerjoin(Record, Record.id == FileReference.record_id)
            .where(_kept_owner())
            .distinct()
            .subquery()
            .c.sha256
        )

    def count_unconfirmed(self) -> int:
        """How many files live records cite (or releases keep) that the
        authority hasn't said it holds: not on the server yet, as far as this
        device knows."""
        sha = self._referenced()
        return int(
            self._s.execute(
                select(func.count()).where(sha.not_in(select(ServerFile.sha256)))
            ).scalar_one()
        )

    def unconfirmed_copies(self, limit: int) -> dict[str, list[str]]:
        """Up to `limit` files live records cite that the authority hasn't said
        it holds, each with the volumes holding a copy here (none: not on this
        computer), for saying why they haven't gone."""
        shas = list(self._s.scalars(self._referenced_page("", limit, True)))
        where: dict[str, list[str]] = {s: [] for s in shas}
        for at in range(0, len(shas), 500):
            for s, volume in self._s.execute(
                select(StoredObject.sha256, StoredObject.volume).where(
                    StoredObject.sha256.in_(shas[at : at + 500])
                )
            ):
                where[s].append(volume)
        return where

    def unconfirmed_of(self, shas: set[str]) -> set[str]:
        """Of these files, those the authority hasn't said it holds."""
        confirmed: set[str] = set()
        listed = sorted(shas)
        for at in range(0, len(listed), 500):
            confirmed.update(
                self._s.scalars(
                    select(ServerFile.sha256).where(
                        ServerFile.sha256.in_(listed[at : at + 500])
                    )
                )
            )
        return shas - confirmed

    def confirm_on_server(self, shas: Iterable[str]) -> None:
        """The authority has said it holds these files."""
        wanted = set(shas)
        new = self.unconfirmed_of(wanted)
        if new:
            self._s.add_all(ServerFile(sha256=sha) for sha in sorted(new))
        self._clear_lacks(wanted)
        self._s.flush()

    def note_server_lacks(self, shas: Iterable[str], backoff: bool = True) -> None:
        """The authority has just said it hasn't got these files: noted, and
        not asked about again until later (`LACK_RETRY_FIRST`, doubling each
        time a download is refused again, up to `LACK_RETRY_MAX`). With
        `backoff` false (a look at what it holds, not a download that failed)
        a file already noted keeps its schedule."""
        listed = sorted(set(shas))
        now = datetime.now(timezone.utc)
        for at in range(0, len(listed), 500):
            page = listed[at : at + 500]
            rows = {
                r.sha256: r
                for r in self._s.scalars(
                    select(ServerLack).where(ServerLack.sha256.in_(page))
                )
            }
            for sha in page:
                row = rows.get(sha)
                if row is None:
                    row = ServerLack(sha256=sha, misses=0)
                    self._s.add(row)
                row.asked_at = now
                if backoff or row.misses == 0:
                    row.misses += 1
                    row.retry_at = now + lack_wait(row.misses)
        self._s.flush()

    def forget_lacks(self, shas: Iterable[str]) -> None:
        """Ask the authority about these files again at the next pass (they may
        have reached it): still noted as missing until one is fetched, and the
        next wait keeps growing if it hasn't got them."""
        listed = sorted(set(shas))
        now = datetime.now(timezone.utc)
        for at in range(0, len(listed), 500):
            self._s.execute(
                update(ServerLack)
                .where(ServerLack.sha256.in_(listed[at : at + 500]))
                .values(retry_at=now)
                .execution_options(synchronize_session=False)
            )
        self._s.flush()

    def forget_record_lacks(self, record_id: uuid.UUID) -> None:
        """`forget_lacks` for the files a record cites."""
        self.forget_lacks(
            self._s.scalars(
                select(FileReference.sha256).where(FileReference.record_id == record_id)
            ).all()
        )

    def ignored_missing(self) -> set[str]:
        """The files a person chose to stop being told are missing."""
        return set(self._s.scalars(select(IgnoredMissingFile.sha256)))

    def ignore_missing(self, shas: Iterable[str]) -> None:
        listed = sorted(set(shas) - self.ignored_missing())
        now = datetime.now(timezone.utc)
        self._s.add_all(IgnoredMissingFile(sha256=s, ignored_at=now) for s in listed)
        self._s.flush()

    def unignore_missing(self, shas: Iterable[str]) -> int:
        listed = sorted(set(shas))
        n = 0
        for at in range(0, len(listed), 500):
            n += (
                self._s.query(IgnoredMissingFile)
                .filter(IgnoredMissingFile.sha256.in_(listed[at : at + 500]))
                .delete(synchronize_session=False)
            )
        return n

    def citing_records(self, shas: Iterable[str]) -> dict[uuid.UUID, set[str]]:
        """The live records citing any of these files, each with which."""
        listed = sorted(set(shas))
        out: dict[uuid.UUID, set[str]] = {}
        for at in range(0, len(listed), 500):
            for record_id, sha in self._s.execute(
                select(FileReference.record_id, FileReference.sha256)
                .join(Record, Record.id == FileReference.record_id)
                .where(
                    FileReference.sha256.in_(listed[at : at + 500]),
                    Record.deleted_at.is_(None),
                )
            ):
                if record_id is not None:
                    out.setdefault(record_id, set()).add(sha)
        return out

    def never_stored(self, shas: Iterable[str]) -> set[str]:
        """Of these files, those this project has no inventory row for on any
        drive: never stored here (as against stored once and since gone)."""
        listed = sorted(set(shas))
        had: set[str] = set()
        for at in range(0, len(listed), 500):
            had.update(
                self._s.scalars(
                    select(StoredObject.sha256)
                    .where(StoredObject.sha256.in_(listed[at : at + 500]))
                    .distinct()
                )
            )
        return set(listed) - had

    def collections_citing(self, shas: Iterable[str]) -> dict[uuid.UUID, int]:
        """The live records citing any of these files, counted by collection."""
        listed = sorted(set(shas))
        ids: dict[uuid.UUID, uuid.UUID] = {}
        for at in range(0, len(listed), 500):
            for record_id, dataset_id in self._s.execute(
                select(Record.id, Record.dataset_id)
                .join(FileReference, FileReference.record_id == Record.id)
                .where(
                    FileReference.sha256.in_(listed[at : at + 500]),
                    Record.deleted_at.is_(None),
                )
                .distinct()
            ):
                ids[record_id] = dataset_id
        counts: dict[uuid.UUID, int] = {}
        for dataset_id in ids.values():
            counts[dataset_id] = counts.get(dataset_id, 0) + 1
        return counts

    def server_lacks_of(self, shas: set[str]) -> set[str]:
        """Of these files, those the authority said it hasn't got, when asked."""
        listed = sorted(shas)
        out: set[str] = set()
        for at in range(0, len(listed), 500):
            out.update(
                self._s.scalars(
                    select(ServerLack.sha256).where(
                        ServerLack.sha256.in_(listed[at : at + 500])
                    )
                )
            )
        return out

    def _clear_lacks(self, shas: set[str]) -> None:
        listed = sorted(shas)
        for at in range(0, len(listed), 500):
            self._s.execute(
                delete(ServerLack)
                .where(ServerLack.sha256.in_(listed[at : at + 500]))
                .execution_options(synchronize_session=False)
            )

    def _not_here(  # type: ignore[no-untyped-def]
        self, collections: set[uuid.UUID] | None = None, lacks: str = "hide"
    ):
        """Files live records or releases here own that no drive here is
        recorded to hold (a deleted record's files are fetched if it comes back
        and is opened, not in the background), each with a collection that
        uses it (none for a release's); with `collections`, only files records
        in those use, and releases'. A release that came from another device
        owns only its bundle here, so that is what it brings.

        `lacks` says what to do with files the authority said it hasn't got:
        `hide` leaves out every one (and those a person ignored): what is
        downloading; `wait` leaves out those not yet due to be asked again:
        what a download pass may request; `only` is just the ones missing
        everywhere (less the ignored); `all` leaves out nothing."""
        stored = stored_files()
        record = Record.deleted_at.is_(None) & FileReference.record_id.is_not(None)
        if collections is not None:
            record = record & Record.dataset_id.in_(collections)
        query = (
            select(
                FileReference.sha256.label("sha"),
                # PostgreSQL has no min(uuid): pick one as text, cast back.
                cast(func.min(cast(Record.dataset_id, String)), Uuid).label("cid"),
            )
            .outerjoin(Record, Record.id == FileReference.record_id)
            .outerjoin(stored, stored.c.sha == FileReference.sha256)
            .outerjoin(ServerLack, ServerLack.sha256 == FileReference.sha256)
            .where(
                stored.c.sha.is_(None), record | FileReference.release_id.is_not(None)
            )
        )
        if lacks == "wait":
            query = query.where(
                ServerLack.sha256.is_(None)
                | (ServerLack.retry_at <= datetime.now(timezone.utc))
            )
        elif lacks != "all":
            ignored = select(IgnoredMissingFile.sha256)
            query = query.where(FileReference.sha256.not_in(ignored))
            query = query.where(
                ServerLack.sha256.is_not(None)
                if lacks == "only"
                else ServerLack.sha256.is_(None)
            )
        return query.group_by(FileReference.sha256).subquery()

    def files_not_here(
        self,
        after: str,
        limit: int,
        shas: list[str] | None = None,
        collections: set[uuid.UUID] | None = None,
    ) -> list[tuple[str, uuid.UUID | None]]:
        """Files the records here cite (or releases keep) that no drive here
        holds (another device added them), in hash order after `after`, each
        with a collection that uses it (to choose the drive it is written to).
        With `shas`, only those (asked for by name, so whatever the authority
        said before); with `collections`, only files records in those
        collections use. Left out: files the authority said it hasn't got,
        until it is time to ask again."""
        q = self._not_here(collections, "all" if shas is not None else "wait")
        query = select(q.c.sha, q.c.cid).where(q.c.sha > after)
        if shas is not None:
            query = query.where(q.c.sha.in_(shas))
        rows = self._s.execute(query.order_by(q.c.sha).limit(limit))
        return [(sha, collection) for sha, collection in rows]

    def count_files_not_here(
        self, collections: set[uuid.UUID] | None = None, lacks: str = "hide"
    ) -> int:
        q = self._not_here(collections, lacks)
        return int(self._s.execute(select(func.count()).select_from(q)).scalar_one())

    def added_by(self, shas: list[str]) -> dict[str, str | None]:
        """Which device added each of these files (its name, as the authority
        stamped it; None when unknown, since a person's name is not a
        computer): the earliest history entry of a record citing it whose new
        side has it and old side hasn't. A few lookups per file, for the
        handful a person is told about (files nobody can fetch), never a list."""
        out: dict[str, str | None] = {}
        for sha in dict.fromkeys(shas):
            holders = [
                r
                for (r,) in self._s.execute(
                    select(FileReference.record_id).where(
                        FileReference.sha256 == sha,
                        FileReference.record_id.is_not(None),
                    )
                )
            ]
            out[sha] = None
            if not holders:
                continue
            for row in (
                self._s.query(AuditLog)
                .filter(AuditLog.entity_id.in_(holders))
                .order_by(*_WRITE_ORDER)
            ):
                old, new = entry_snapshots(row.old_data, row.new_data, row.delta)
                if sha in json.dumps(new or {}) and sha not in json.dumps(old or {}):
                    out[sha] = row.device
                    break
        return out

    def files_by_collection(self) -> dict[uuid.UUID, tuple[int, int, int]]:
        """Per live collection: the distinct files its records use that a drive
        here holds, their bytes, and the files that are only on the server (no
        drive here holds them). One grouped query over the catalog."""
        pairs = (
            select(Record.dataset_id.label("cid"), FileReference.sha256.label("sha"))
            .join(Record, Record.id == FileReference.record_id)
            .join(Dataset, Dataset.id == Record.dataset_id)
            .where(Dataset.deleted_at.is_(None), Record.deleted_at.is_(None))
            .distinct()
            .subquery()
        )
        stored = stored_files()
        here = stored.c.sha.is_not(None)
        rows = self._s.execute(
            select(
                pairs.c.cid,
                func.count().filter(here),
                func.coalesce(func.sum(stored.c.size).filter(here), 0),
                func.count().filter(stored.c.sha.is_(None)),
            )
            .select_from(pairs)
            .outerjoin(stored, stored.c.sha == pairs.c.sha)
            .group_by(pairs.c.cid)
        )
        return {cid: (int(n), int(b), int(r)) for cid, n, b, r in rows}

    def live_collections(self) -> dict[uuid.UUID, str]:
        """Every live collection, id to name."""
        return {
            i: n
            for i, n in self._s.execute(
                select(Dataset.id, Dataset.name).where(Dataset.deleted_at.is_(None))
            )
        }

    def files_here_of(self, collection: uuid.UUID) -> dict[str, int]:
        """The files a collection's records use that a drive here holds, with
        their size."""
        stored = stored_files()
        rows = self._s.execute(
            select(FileReference.sha256, stored.c.size)
            .join(Record, Record.id == FileReference.record_id)
            .join(stored, stored.c.sha == FileReference.sha256)
            .where(Record.dataset_id == collection)
            .distinct()
        )
        return {sha: int(size) for sha, size in rows}

    def used_by(self, shas: list[str], collections: set[uuid.UUID]) -> set[str]:
        """Of these files, those that records in these collections use."""
        out: set[str] = set()
        if not shas or not collections:
            return out
        for i in range(0, len(shas), 500):
            out |= {
                sha
                for (sha,) in self._s.execute(
                    select(FileReference.sha256)
                    .join(Record, Record.id == FileReference.record_id)
                    .where(
                        FileReference.sha256.in_(shas[i : i + 500]),
                        Record.dataset_id.in_(collections),
                    )
                    .distinct()
                )
            }
        return out

    def set_project_id(self, project_id: uuid.UUID) -> None:
        self._meta_row().project_id = project_id
        self._s.flush()

    def dataset_created_seqs(self, ids: set[str]) -> dict[str, int]:
        """The feed number each of these collections' creation was given (those
        never numbered, seeded as they were, are left out). Looked up by the
        collections' own ids, which history is indexed by, never by scanning
        its kinds and actions."""
        found: dict[str, int] = {}
        wanted = sorted(ids)
        for at in range(0, len(wanted), 500):
            rows = (
                self._s.query(AuditLog.entity_id, func.min(AuditLog.hub_seq))
                .filter(
                    AuditLog.entity_id.in_(
                        [uuid.UUID(i) for i in wanted[at : at + 500]]
                    ),
                    AuditLog.entity_type == "dataset",
                    AuditLog.action == "create",
                    AuditLog.hub_seq.isnot(None),
                )
                .group_by(AuditLog.entity_id)
            )
            found.update({str(i): int(seq or 0) for i, seq in rows})
        return found

    def holds_anything(self) -> bool:
        """Whether there is at least one thing of any kind here, deleted ones
        included (one probe each, not a count)."""
        return any(
            self._s.query(model.id).limit(1).first() is not None
            for model in _MODELS.values()
        )

    def collection_trails(
        self, record_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, list[tuple[int, uuid.UUID | None, uuid.UUID | None]]]:
        """For each record, the numbered changes to it in order, each as `(its
        feed number, the collection it was in before it when the change says,
        the collection it was in after it)`, led by `(0, None, where its first
        change found it)`: where a note
        was judged to be at a given number. One lookup for all the records,
        reading only the collection fields (what `entry_collections` reads of an
        entry) and not the changes themselves."""
        trails: dict[
            uuid.UUID, list[tuple[int, uuid.UUID | None, uuid.UUID | None]]
        ] = {}
        wanted = sorted(record_ids)
        for at in range(0, len(wanted), 500):
            rows = (
                self._s.query(
                    AuditLog.entity_id,
                    AuditLog.hub_seq,
                    AuditLog.new_data["dataset_id"].as_string(),
                    AuditLog.old_data["dataset_id"].as_string(),
                    AuditLog.delta[("dataset_id", "before")].as_string(),
                    AuditLog.delta[("dataset_id", "after")].as_string(),
                )
                .filter(
                    AuditLog.entity_id.in_(wanted[at : at + 500]),
                    AuditLog.entity_type == "record",
                    AuditLog.hub_seq.isnot(None),
                    AuditLog.apply_state != "superseded",
                )
                .order_by(AuditLog.entity_id, AuditLog.hub_seq)
            )
            for rid, seq, new, old, moved_from, moved_to in rows:
                after = new or old
                if moved_from or moved_to:
                    after = moved_to or after
                elif old and new:
                    after = new
                trail = trails.setdefault(rid, [])
                if not trail:
                    # Before its first numbered change a record was where that
                    # change found it: a note made then is judged by that, not
                    # by where the record ended up.
                    before = (
                        (moved_from or old) if (moved_from or (old and new)) else after
                    )
                    trail.append((0, None, _uuid_or_none(before)))
                said = (moved_from or old) if (moved_from or (old and new)) else None
                trail.append((int(seq), _uuid_or_none(said), _uuid_or_none(after)))
        return trails

    def readable(self) -> set[str] | None:
        """The collections this device was last told it may read (None: not
        known yet)."""
        found = self._meta_row().readable
        return None if found is None else {str(c) for c in found}

    def set_readable(self, collections: set[str]) -> None:
        self._meta_row().readable = sorted(collections)
        self._s.flush()

    def record_ids_in(self, dataset: uuid.UUID) -> set[str]:
        """Every record held here in this collection, deleted ones included."""
        return {
            str(i)
            for (i,) in self._s.query(Record.id).filter(Record.dataset_id == dataset)
        }

    def note_record_id(self, note_id: uuid.UUID) -> uuid.UUID | None:
        """The record a note is on, whatever the session may see; None when
        there is no such note."""
        return (
            self._s.query(RecordNote.record_id)
            .filter(RecordNote.id == note_id)
            .scalar()
        )

    def note_snapshots(self, record_id: uuid.UUID) -> list[dict[str, Any]]:
        """Every note on this record (deleted ones too), as sync carries them."""
        rows = (
            self._s.query(RecordNote)
            .filter(RecordNote.record_id == record_id)
            .order_by(RecordNote.created_at, RecordNote.id)
            .all()
        )
        return self._dicts("note", rows)

    def set_cursor(self, seq: int) -> None:
        self._meta_row().cursor = seq
        self._s.flush()

    def set_seeded_by(self, device_id: str) -> None:
        self._meta_row().seeded_by = device_id
        self._s.flush()

    def next_hub_seq(self) -> int:
        """The next number, taken atomically: the counter is incremented in the
        database, never read and written back, so two writers can't hand out the
        same one."""
        self._meta_row()
        self._s.execute(
            update(SyncMeta)
            .where(SyncMeta.id == 1)
            .values(head_seq=SyncMeta.head_seq + 1)
        )
        self._s.expire_all()
        return self._meta_row().head_seq

    def head_seq(self) -> int:
        return self._meta_row().head_seq

    def lock_feed(self) -> None:
        """Hold the feed's counter until this transaction ends, so whoever
        takes it next waits: a row lock on PostgreSQL, the write lock on
        SQLite (a write that changes nothing still takes it)."""
        self._meta_row()
        self._s.execute(
            update(SyncMeta).where(SyncMeta.id == 1).values(head_seq=SyncMeta.head_seq)
        )

    def record_outcome(self, error: str | None) -> None:
        row = self._meta_row()
        now = datetime.now(timezone.utc)
        if error is None:
            row.last_synced_at = now
            row.last_error = None
            row.last_error_at = None
        else:
            row.last_error = error[:2000]
            row.last_error_at = now
        self._s.flush()

    # ------------------------------------------------------------------
    # Devices (authority)
    # ------------------------------------------------------------------

    def add_device(self, name: str, device_id: str, public_key: str) -> SyncDeviceDTO:
        row = SyncDevice(name=name, device_id=device_id, public_key=public_key)
        self._s.add(row)
        self._s.flush()
        return _device_dto(row)

    def list_devices(self) -> list[SyncDeviceDTO]:
        rows = self._s.query(SyncDevice).order_by(SyncDevice.created_at).all()
        return [_device_dto(r) for r in rows]

    def _live_devices(self):
        return self._s.query(SyncDevice).filter(SyncDevice.revoked_at.is_(None))

    def device_named(self, name: str) -> SyncDeviceDTO | None:
        row = self._live_devices().filter_by(name=name).first()
        return _device_dto(row) if row else None

    def live_device(self, device_id: str) -> SyncDeviceDTO | None:
        row = self._live_devices().filter_by(device_id=device_id).first()
        return _device_dto(row) if row else None

    def get_device(self, id: uuid.UUID) -> SyncDeviceDTO | None:
        row = self._s.get(SyncDevice, id)
        return _device_dto(row) if row else None

    def revoke_device(self, name: str) -> bool:
        row = self._live_devices().filter_by(name=name).first()
        if row is None:
            return False
        row.revoked_at = datetime.now(timezone.utc)
        self._s.flush()
        return True

    def set_may_publish(self, name: str, allowed: bool) -> bool:
        row = self._live_devices().filter_by(name=name).first()
        if row is None:
            return False
        row.may_publish = allowed
        self._s.flush()
        return True

    def touch_device(self, id: uuid.UUID) -> None:
        row = self._s.get(SyncDevice, id)
        if row is not None:
            row.last_seen_at = datetime.now(timezone.utc)
            self._s.flush()

    def add_invite(
        self, name: str, code_hash: str, expires_at: datetime
    ) -> SyncInviteDTO:
        row = SyncInvite(name=name, code_hash=code_hash, expires_at=expires_at)
        self._s.add(row)
        self._s.flush()
        return _invite_dto(row)

    # -- devices asking to join, for a person to approve -----------------------

    def add_login_request(
        self,
        user_code: str,
        device_hash: str,
        device_id: str,
        public_key: str,
        expires_at: datetime,
    ) -> LoginRequestDTO:
        row = SyncLoginRequest(
            user_code=user_code,
            device_hash=device_hash,
            device_id=device_id,
            public_key=public_key,
            expires_at=expires_at,
        )
        self._s.add(row)
        self._s.flush()
        return _login_dto(row)

    def login_by_device_hash(self, device_hash: str) -> LoginRequestDTO | None:
        row = self._s.query(SyncLoginRequest).filter_by(device_hash=device_hash).first()
        return _login_dto(row) if row else None

    def _waiting_logins(self):
        return self._s.query(SyncLoginRequest).filter(
            SyncLoginRequest.approved_at.is_(None),
            SyncLoginRequest.denied_at.is_(None),
            SyncLoginRequest.expires_at > datetime.now(timezone.utc),
        )

    def login_waiting(self, user_code: str) -> LoginRequestDTO | None:
        """The request showing this code that is still waiting (the newest, if
        a code was ever reused)."""
        row = (
            self._waiting_logins()
            .filter_by(user_code=user_code)
            .order_by(SyncLoginRequest.created_at.desc())
            .first()
        )
        return _login_dto(row) if row else None

    def pending_logins(self) -> list[LoginRequestDTO]:
        rows = self._waiting_logins().order_by(SyncLoginRequest.created_at).all()
        return [_login_dto(r) for r in rows]

    def settle_login(self, id: uuid.UUID, name: str | None, approved: bool) -> None:
        row = self._s.get(SyncLoginRequest, id)
        if row is None:
            return
        now = datetime.now(timezone.utc)
        if approved:
            row.approved_at, row.name = now, name
        else:
            row.denied_at = now
        self._s.flush()

    def invite_by_hash(self, code_hash: str) -> SyncInviteDTO | None:
        row = self._s.query(SyncInvite).filter_by(code_hash=code_hash).first()
        return _invite_dto(row) if row else None

    def _pending_invites(self):
        return self._s.query(SyncInvite).filter(
            SyncInvite.used_at.is_(None),
            SyncInvite.revoked_at.is_(None),
            SyncInvite.expires_at > datetime.now(timezone.utc),
        )

    def pending_invites(self) -> list[SyncInviteDTO]:
        rows = self._pending_invites().order_by(SyncInvite.created_at).all()
        return [_invite_dto(r) for r in rows]

    def use_invite(self, id: uuid.UUID) -> bool:
        """Mark it used, if nobody has: one conditional write, so of two joins
        at once only one takes it."""
        taken = self._s.execute(
            update(SyncInvite)
            .where(SyncInvite.id == id, SyncInvite.used_at.is_(None))
            .values(used_at=datetime.now(timezone.utc))
        )
        return taken.rowcount == 1  # type: ignore[attr-defined]

    def cancel_invite(self, name: str) -> bool:
        rows = self._pending_invites().filter_by(name=name).all()
        for row in rows:
            row.revoked_at = datetime.now(timezone.utc)
        self._s.flush()
        return bool(rows)

    def authority_key(self) -> str | None:
        return self._meta_row().authority_key

    def set_authority_key(self, key: str) -> None:
        self._meta_row().authority_key = key
        self._s.flush()

    # ------------------------------------------------------------------
    # What an authority has been sent
    # ------------------------------------------------------------------

    def get_op(self, op_id: uuid.UUID) -> OpResult | None:
        row = self._s.get(SyncOp, op_id)
        if row is None:
            return None
        return OpResult(
            op_id=row.op_id,
            status=row.status,
            message=row.message,
            conflicts=list(row.conflicts or []),
            hub_seq=row.hub_seq,
        )

    def save_op(
        self,
        entry: SyncEntry,
        result: OpResult,
        device_id: str | None,
        device_name: str | None,
    ) -> None:
        self._s.add(
            SyncOp(
                op_id=entry.id,
                device_id=device_id,
                device_name=device_name,
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
                status=result.status,
                message=result.message,
                conflicts=result.conflicts,
                hub_seq=result.hub_seq,
            )
        )
        self._s.flush()

    def drop_op(self, op_id: uuid.UUID) -> None:
        """Forget an op that is to be tried again (it was deferred)."""
        row = self._s.get(SyncOp, op_id)
        if row is not None:
            self._s.delete(row)
            self._s.flush()

    # ------------------------------------------------------------------
    # Conflicts
    # ------------------------------------------------------------------

    def add_conflict(
        self,
        *,
        kind: str,
        entity_type: str,
        entity_id: uuid.UUID,
        field: str | None,
        yours: Any,
        theirs: Any,
        op_id: uuid.UUID | None,
        device_name: str | None,
        message: str | None,
        base: Any = None,
        theirs_actor: str | None = None,
        theirs_at: str | None = None,
        theirs_device: str | None = None,
        code: str | None = None,
    ) -> SyncConflictDTO:
        row = SyncConflict(
            code=code,
            kind=kind,
            entity_type=entity_type,
            entity_id=entity_id,
            field=field,
            yours=yours,
            theirs=theirs,
            base=base,
            theirs_actor=theirs_actor,
            theirs_device=theirs_device,
            theirs_at=_parse(theirs_at),
            op_id=op_id,
            device_name=device_name,
            message=message,
        )
        self._s.add(row)
        self._s.flush()
        return _conflict_dto(row)

    def has_conflict(self, op_id: uuid.UUID, field: str | None, kind: str) -> bool:
        return (
            self._s.query(SyncConflict.id)
            .filter_by(op_id=op_id, field=field, kind=kind)
            .first()
            is not None
        )

    def list_conflicts(
        self,
        status: str | None = "open",
        limit: int = 200,
        offset: int = 0,
        entity_id: uuid.UUID | None = None,
    ) -> list[SyncConflictDTO]:
        q = self._s.query(SyncConflict)
        if status:
            q = q.filter_by(status=status)
        if entity_id:
            q = q.filter(SyncConflict.entity_id == entity_id)
        rows = q.order_by(SyncConflict.created_at.desc()).offset(offset).limit(limit)
        return [_conflict_dto(r) for r in rows]

    def count_conflicts(self, status: str | None = "open") -> int:
        q = self._s.query(func.count(SyncConflict.id))
        if status:
            q = q.filter(SyncConflict.status == status)
        return q.scalar() or 0

    def get_conflict(self, id: uuid.UUID) -> SyncConflictDTO | None:
        row = self._s.get(SyncConflict, id)
        return _conflict_dto(row) if row else None

    def last_change(
        self, kind: str, entity_id: uuid.UUID, path: str | None
    ) -> tuple[str | None, str | None, str | None]:
        """Who last changed a value of a thing, through which device, and when
        (actor, device, ISO time): the
        latest numbered entry whose before and after differ at `path`, or the
        latest entry of any kind when `path` is None. What a conflict says about
        the value that stayed."""
        rows = (
            self._s.query(AuditLog)
            .filter(
                AuditLog.entity_type == kind,
                AuditLog.entity_id == entity_id,
                # The state the authority settles on is written under this name:
                # it is nobody's edit.
                or_(AuditLog.actor.is_(None), AuditLog.actor != "sync"),
            )
            .order_by(*(c.desc() for c in _WRITE_ORDER))
            .limit(50)
            .all()
        )
        for row in rows:
            old, new = entry_snapshots(row.old_data, row.new_data, row.delta)
            if path is None or value_at(old, path) != value_at(new, path):
                return row.actor, row.device, _iso(row.timestamp)
        return None, None, None

    def resolve_conflict(self, id: uuid.UUID, resolution: str) -> None:
        row = self._s.get(SyncConflict, id)
        if row is None:
            raise NotFoundError(f"Conflict '{id}' not found")
        row.status = "resolved"
        row.resolution = resolution
        row.resolved_at = datetime.now(timezone.utc)
        self._s.flush()

    def mark_retrying(self, id: uuid.UUID) -> None:
        """An open refusal whose change has been sent again: still open (it
        isn't settled until the authority answers), saying it is on its way."""
        row = self._s.get(SyncConflict, id)
        if row is None:
            raise NotFoundError(f"Conflict '{id}' not found")
        row.resolution = "retrying"
        self._s.flush()

    def note_auto_retry(self, id: uuid.UUID) -> None:
        """A refusal has been sent again by the device itself: counted, and
        timed, so the next try waits longer."""
        row = self._s.get(SyncConflict, id)
        if row is None:
            return
        row.retries = (row.retries or 0) + 1
        row.retried_at = datetime.now(timezone.utc)
        self._s.flush()

    def renew_refusal(
        self,
        id: uuid.UUID,
        op_id: uuid.UUID,
        message: str | None,
        yours: Any,
        field: str | None = None,
        code: str | None = None,
    ) -> None:
        """The same thing refused again: the open item says so (the latest
        change and why), rather than another item beside it."""
        row = self._s.get(SyncConflict, id)
        if row is None:
            return
        row.code = code
        row.op_id = op_id
        row.message = message
        row.yours = yours
        row.field = field
        row.resolution = None
        row.created_at = datetime.now(timezone.utc)
        self._s.flush()

    def conflicts_of_ops(self, op_ids: list[uuid.UUID]) -> list[SyncConflictDTO]:
        """Every conflict, open or settled, that came from one of these changes."""
        if not op_ids:
            return []
        rows = (
            self._s.query(SyncConflict)
            .filter(SyncConflict.op_id.in_(op_ids))
            .order_by(SyncConflict.created_at)
        )
        return [_conflict_dto(r) for r in rows]

    def find_open_conflicts(
        self,
        *,
        ids: list[uuid.UUID] | None = None,
        kind: str | None = None,
        entity_id: uuid.UUID | None = None,
    ) -> list[SyncConflictDTO]:
        """Every open conflict matching all that is given, oldest first and with no
        page limit (a bulk settle must reach them all, not the first screenful)."""
        q = self._s.query(SyncConflict).filter_by(status="open")
        if ids is not None:
            q = q.filter(SyncConflict.id.in_(ids))
        if kind:
            q = q.filter(SyncConflict.kind == kind)
        if entity_id:
            q = q.filter(SyncConflict.entity_id == entity_id)
        return [_conflict_dto(r) for r in q.order_by(SyncConflict.created_at)]

    def resolve_conflicts(self, ids: list[uuid.UUID], resolution: str) -> int:
        """Mark open conflicts settled, in one statement. Returns how many were."""
        if not ids:
            return 0
        n = (
            self._s.query(SyncConflict)
            .filter(SyncConflict.id.in_(ids), SyncConflict.status == "open")
            .update(
                {
                    "status": "resolved",
                    "resolution": resolution,
                    "resolved_at": datetime.now(timezone.utc),
                },
                synchronize_session=False,
            )
        )
        self._s.flush()
        return n

    def reopen_conflicts(self, ids: list[uuid.UUID], resolution: str) -> int:
        """Open conflicts that were settled with `resolution` again. Returns how
        many were."""
        if not ids:
            return 0
        n = (
            self._s.query(SyncConflict)
            .filter(
                SyncConflict.id.in_(ids),
                SyncConflict.status == "resolved",
                SyncConflict.resolution == resolution,
            )
            .update(
                {"status": "open", "resolution": None, "resolved_at": None},
                synchronize_session=False,
            )
        )
        self._s.flush()
        return n

    # ------------------------------------------------------------------
    # Things, by snapshot
    # ------------------------------------------------------------------

    def entity_count(self) -> int:
        """How many schemas, fields, collections, views and records there are,
        deleted ones included: zero is an empty project."""
        return sum(self.entity_counts().values())

    def entity_counts(self) -> dict[str, int]:
        """How many of each kind there are, deleted ones included."""
        return {
            kind: self._s.query(func.count(model.id)).scalar() or 0
            for kind, model in _MODELS.items()
        }

    def snapshot(self, kind: str, id: uuid.UUID) -> dict[str, Any] | None:
        """One thing as it is now, in the shape a history entry stores."""
        row = self._s.get(_MODELS[kind], id)
        if row is None:
            return None
        return self._dicts(kind, [row])[0]

    def snapshots_page(
        self,
        kind: str,
        after: str | None,
        limit: int,
        dataset: uuid.UUID | None = None,
        left_after: int | None = None,
    ) -> list[dict[str, Any]]:
        """Up to `limit` things of `kind` in the order they were made, starting
        after the `snapshot_cursor` `after` (None: from the first). With
        `dataset`, only what belongs to that collection: the collection, its
        records and their notes (nothing of any other kind belongs to one). With
        `left_after` as well, instead the records that left that collection
        after that feed number (and are elsewhere now), and their notes."""
        model = _MODELS[kind]
        query = self._s.query(model)
        if dataset is not None and left_after is not None:
            left = self._left(dataset, left_after)
            if kind == "record":
                # The records that left, and what each sits under (one made
                # since the device's cursor is not held yet, and the record
                # cannot be written without it).
                rec = Record.__table__
                chain = (
                    select(rec.c.id, rec.c.parent_record_id)
                    .where(rec.c.id.in_(left))
                    .cte("left_chain", recursive=True)
                )
                chain = chain.union(
                    select(rec.c.id, rec.c.parent_record_id).where(
                        rec.c.id == chain.c.parent_record_id
                    )
                )
                query = query.filter(
                    Record.id.in_(select(chain.c.id)), Record.dataset_id != dataset
                )
            elif kind == "note":
                query = query.filter(
                    RecordNote.record_id.in_(
                        select(Record.id).where(
                            Record.id.in_(left), Record.dataset_id != dataset
                        )
                    )
                )
            else:
                return []
        elif dataset is not None:
            if kind == "dataset":
                query = query.filter(Dataset.id == dataset)
            elif kind == "record":
                query = query.filter(Record.dataset_id == dataset)
            elif kind == "note":
                query = query.filter(
                    RecordNote.record_id.in_(
                        select(Record.id).where(Record.dataset_id == dataset)
                    )
                )
            else:
                return []
        if after:
            created, id_ = parse_snapshot_cursor(after)
            at, rid = _parse(created), uuid.UUID(id_)
            query = query.filter(
                or_(
                    model.created_at > at,
                    and_(model.created_at == at, model.id > rid),
                )
            )
        rows = query.order_by(model.created_at, model.id).limit(limit).all()
        return self._dicts(kind, rows)

    @staticmethod
    def _left(dataset: uuid.UUID, after: int) -> Any:
        """The records some numbered change after `after` took, or may have
        taken, out of `dataset`: those whose change names it as where the
        record was. Superset-safe: the caller keeps only what is elsewhere now."""
        where = str(dataset)
        return select(AuditLog.entity_id).where(
            AuditLog.entity_type == "record",
            AuditLog.hub_seq > after,
            or_(
                AuditLog.delta[("dataset_id", "before")].as_string() == where,
                AuditLog.old_data["dataset_id"].as_string() == where,
            ),
        )

    def record_seed_order(self) -> list[str]:
        """Every record's id, each after the records it needs to exist first: the
        one it sits under and the ones it refers to. Ties (and any records that
        refer to each other in a circle, which nothing can put first) keep
        creation order. A record that is deleted needs only its parent: nothing
        checks what it points at."""
        rows = (
            self._s.query(Record.id, Record.parent_record_id, Record.deleted_at)
            .order_by(Record.created_at, Record.id)
            .yield_per(2000)
        )
        position: dict[uuid.UUID, int] = {}
        parent: dict[uuid.UUID, uuid.UUID | None] = {}
        deleted: set[uuid.UUID] = set()
        for rid, parent_id, deleted_at in rows:
            position[rid] = len(position)
            parent[rid] = parent_id
            if deleted_at is not None:
                deleted.add(rid)

        needs: dict[uuid.UUID, set[uuid.UUID]] = {rid: set() for rid in position}
        for rid, parent_id in parent.items():
            if parent_id in position:
                needs[rid].add(parent_id)
        for rid, target in self._s.query(
            RecordReference.record_id, RecordReference.target_id
        ).yield_per(5000):
            if rid in position and rid not in deleted and target in position:
                needs[rid].add(target)
            # (a reference to itself, or to nothing here, needs nothing)
        for rid in position:
            needs[rid].discard(rid)

        waiting_on: dict[uuid.UUID, int] = {r: len(n) for r, n in needs.items()}
        needed_by: dict[uuid.UUID, list[uuid.UUID]] = {}
        for rid, n in needs.items():
            for dep in n:
                needed_by.setdefault(dep, []).append(rid)

        import heapq

        ready = [position[r] for r, w in waiting_on.items() if w == 0]
        heapq.heapify(ready)
        by_position = {i: r for r, i in position.items()}
        order: list[uuid.UUID] = []
        placed: set[uuid.UUID] = set()
        while ready:
            rid = by_position[heapq.heappop(ready)]
            order.append(rid)
            placed.add(rid)
            for dependant in needed_by.get(rid, ()):
                waiting_on[dependant] -= 1
                if waiting_on[dependant] == 0:
                    heapq.heappush(ready, position[dependant])
        # A circle of references: nothing can go first, so send them as made.
        order.extend(r for r in sorted(position, key=position.get) if r not in placed)  # type: ignore[arg-type]
        return [str(r) for r in order]

    def record_snapshots(self, ids: list[str]) -> list[dict[str, Any]]:
        """The records with these ids, as snapshots, in the order given."""
        wanted = [uuid.UUID(i) for i in ids]
        found = {
            r.id: r for r in self._s.query(Record).filter(Record.id.in_(wanted)).all()
        }
        return self._dicts("record", [found[i] for i in wanted if i in found])

    def _dicts(self, kind: str, rows: list[Any]) -> list[dict[str, Any]]:
        """Things as they travel: their DTOs cut to `WIRE_FIELDS`."""
        if kind == "schema":
            dicts = [_schema_to_dto(r).to_dict() for r in rows]
        elif kind == "field":
            dicts = [_field_to_dto(r).to_dict() for r in rows]
        elif kind == "dataset":
            dtos = _dataset_dtos(self._s, rows, with_count=False)
            dicts = [d.to_dict() for d in dtos]
        elif kind == "view":
            dicts = [_view_dto(r).to_dict() for r in rows]
        elif kind == "dashboard":
            dicts = [_dashboard_dto(r).to_dict() for r in rows]
        elif kind == "note":
            dicts = [_note_dto(r).to_dict() for r in rows]
        elif kind == "release":
            dicts = [_release_dto(r).to_dict() for r in rows]
        else:
            dicts = [_record_dto(r).to_dict() for r in rows]
        return [wire_state(kind, d) or {} for d in dicts]

    def apply_snapshot(self, kind: str, snap: dict[str, Any]) -> None:
        """Make the thing in `snap` exist as it describes, with its own id."""
        model = _MODELS[kind]
        columns = {
            c.name: c for c in model.__table__.columns if c.name not in _NOT_WRITTEN
        }
        values = {
            name: _coerce(columns[name], value)
            for name, value in snap.items()
            if name in columns
        }
        row = self._s.get(model, values["id"])
        if row is None:
            row = model(**values)
            self._s.add(row)
        else:
            for name, value in values.items():
                setattr(row, name, value)
            if "updated_at" in values:
                # Written even when it equals what is there: otherwise a change
                # to the other columns lets the column's on-update default stamp
                # it with this machine's clock, and the copies drift apart.
                flag_modified(row, "updated_at")
        self._s.flush()
        if kind == "release":
            self._own_release(row)

    def _own_release(self, row: Release) -> None:
        """A release from the feed owns its bundle here (so it is fetched and
        kept), until it is yanked: then it owns nothing. The files it cites are
        owned once its bundle is read (`ReleaseService.index_waiting`), on the
        copy that keeps everyone's files."""
        from civex.repositories.local.release_repo import LocalReleaseRepository

        releases = LocalReleaseRepository(self._s)
        if row.yanked_at is not None:
            releases.disown(row.id)
        else:
            releases.own(row.id, [row.bundle_sha256])

    def soft_delete(self, kind: str, id: uuid.UUID, stamp: datetime) -> None:
        """Delete as a person's delete does, but stamped `stamp`: a schema or
        collection takes its live records with it, stamped the same."""
        row = self._s.get(_MODELS[kind], id)
        if row is None:
            return
        if getattr(row, "deleted_at", None) is not None:
            # Already deleted here (by a cascade worked out from what this copy
            # held): take the stamp it was deleted with where the entry is
            # from, so every copy ends with the same one. What went with it
            # stays as it is: its own entries say where it stands.
            if kind == "record" and _parse(row.deleted_at.isoformat()) != stamp:
                row.deleted_at = stamp
                flag_modified(row, "updated_at")
                self._s.flush()
            return
        row.deleted_at = stamp
        if kind == "record":
            # A delete is not an edit: written explicitly, or the column's
            # on-update default would stamp it with this machine's clock.
            flag_modified(row, "updated_at")
        if kind == "schema":
            self._s.query(Record).filter(
                Record.schema_id == id, Record.deleted_at.is_(None)
            ).update(
                {"deleted_at": stamp, "updated_at": Record.updated_at},
                synchronize_session=False,
            )
        elif kind == "dataset":
            self._s.query(Record).filter(
                Record.dataset_id == id, Record.deleted_at.is_(None)
            ).update(
                {"deleted_at": stamp, "updated_at": Record.updated_at},
                synchronize_session=False,
            )
        self._s.flush()
        self._s.expire_all()

    def restore(self, kind: str, id: uuid.UUID) -> None:
        """Undo a delete as a person's restore does: a schema or collection
        brings back what its own restore brings back (the other repositories
        own those rules, so they are used rather than repeated)."""
        from civex.repositories.local.dataset_repo import LocalDatasetRepository
        from civex.repositories.local.schema_repo import LocalSchemaRepository

        row = self._s.get(_MODELS[kind], id)
        if row is None:
            return
        if kind == "schema":
            LocalSchemaRepository(self._s).restore(id)
        elif kind == "dataset":
            LocalDatasetRepository(self._s).restore(id)
        else:
            row.deleted_at = None
            if kind == "record":
                flag_modified(row, "updated_at")
        self._s.flush()
        self._s.expire_all()

    def delete_view(self, id: uuid.UUID, kind: str = "view") -> None:
        """Remove a thing that has no deleted state (a view, the page)."""
        row = self._s.get(_MODELS[kind], id)
        if row is not None:
            self._s.delete(row)
            self._s.flush()

    def purge(self, kind: str, id: uuid.UUID) -> None:
        """Remove a thing for good, with what goes with it, exactly as a
        person's permanent delete does (the other repositories own those
        cascades, so they are used rather than repeated)."""
        from civex.repositories.local.dataset_repo import LocalDatasetRepository
        from civex.repositories.local.record_repo import LocalRecordRepository
        from civex.repositories.local.schema_repo import LocalSchemaRepository

        if kind == "schema":
            LocalSchemaRepository(self._s).purge(id)
        elif kind == "dataset":
            LocalDatasetRepository(self._s).purge(id)
        elif kind == "record":
            LocalRecordRepository(
                self._s, is_postgres=self._s.get_bind().dialect.name == "postgresql"
            ).purge_many([id])
        elif kind in ("view", "dashboard"):
            self.delete_view(id, kind)
        elif kind in ("field", "note"):
            row = self._s.get(_MODELS[kind], id)
            if row is not None:
                self._s.delete(row)
        self._s.flush()
        self._s.expire_all()

    # ------------------------------------------------------------------
    # History entries, as sync moves them
    # ------------------------------------------------------------------

    def get_entry(self, id: uuid.UUID) -> SyncEntry | None:
        row = self._s.get(AuditLog, id)
        return self._entries([row])[0] if row is not None else None

    def has_entry(self, id: uuid.UUID) -> bool:
        return self._s.get(AuditLog, id) is not None

    def pending_entries(self, limit: int) -> list[SyncEntry]:
        """Changes made here that the authority has not been sent, oldest first:
        `limit` of them, and the rest of the action the last one belongs to, so
        an action is never split across two pushes (it is taken whole or not)."""
        pending = self._s.query(AuditLog).filter(
            AuditLog.sync_state == "pending", AuditLog.hub_seq.is_(None)
        )
        rows = pending.order_by(*_WRITE_ORDER).limit(limit).all()
        if len(rows) == limit and rows[-1].op_id is not None:
            seen = {r.id for r in rows}
            rows += [
                r
                for r in pending.filter(AuditLog.op_id == rows[-1].op_id)
                .order_by(*_WRITE_ORDER)
                .all()
                if r.id not in seen
            ]
        return self._entries(rows)

    def count_pending(self) -> int:
        return (
            self._s.query(func.count(AuditLog.id))
            .filter(AuditLog.sync_state == "pending", AuditLog.hub_seq.is_(None))
            .scalar()
            or 0
        )

    def count_seeding(self) -> int:
        """Changes a first upload set aside and has not finished sending."""
        return (
            self._s.query(func.count(AuditLog.id))
            .filter(AuditLog.sync_state == "seeding")
            .scalar()
            or 0
        )

    def seeding_entities(self) -> set[tuple[str, str]]:
        """The things a first upload set aside changes for (kind, id)."""
        rows = (
            self._s.query(AuditLog.entity_type, AuditLog.entity_id)
            .filter(AuditLog.sync_state == "seeding")
            .distinct()
        )
        return {(t, str(i)) for t, i in rows}

    def unseed(self) -> None:
        """Changes set aside by a first upload that is not this project's to
        finish go back to waiting to be sent like any other."""
        self._s.execute(
            update(AuditLog)
            .where(AuditLog.sync_state == "seeding")
            .values(sync_state="pending")
            .execution_options(synchronize_session=False)
        )
        self._s.expire_all()

    def dirty_entities(self) -> set[tuple[str, uuid.UUID]]:
        """Things with a change here still waiting to be sent: what a pull must
        not overwrite."""
        rows = (
            self._s.query(AuditLog.entity_type, AuditLog.entity_id)
            .filter(AuditLog.sync_state == "pending", AuditLog.hub_seq.is_(None))
            .distinct()
        )
        return {(t, i) for t, i in rows}

    def mark_sent(self, results: list[OpResult]) -> None:
        for result in results:
            row = self._s.get(AuditLog, result.op_id)
            if row is None:
                continue
            if result.status == "rejected":
                row.sync_state = "rejected"
            elif result.status != "deferred":
                row.sync_state = "synced"
                if result.hub_seq is not None:
                    row.hub_seq = result.hub_seq
                if result.status in ("merged", "conflict"):
                    row.apply_state = "superseded"
        self._s.flush()

    def forget_numbers(self) -> None:
        """Clear the numbers another authority gave this project's history (it
        now follows a different one, whose numbers mean other changes), and the
        files it said it holds."""
        self._s.execute(
            update(AuditLog)
            .where(AuditLog.hub_seq.is_not(None))
            .values(hub_seq=None)
            .execution_options(synchronize_session=False)
        )
        # And which files it said it holds or lacks: the new one is asked afresh.
        self._s.execute(delete(ServerFile))
        self._s.execute(delete(ServerLack))
        self._s.expire_all()

    def never_taken(self, things: set[tuple[str, uuid.UUID]]) -> set[uuid.UUID]:
        """Of these things, the ids of those the authority has never taken: its
        create was refused (made here, or sent when the authority was filled:
        a refusal whose change isn't held here), and nothing carrying the thing
        has been numbered since (a delete of something it never had is numbered
        but takes nothing). An edit to one can't go as an edit."""
        if not things:
            return set()
        ids = {i for _, i in things}
        refused = {
            i
            for (i,) in self._s.query(AuditLog.entity_id).filter(
                AuditLog.entity_id.in_(ids),
                AuditLog.action == "create",
                AuditLog.sync_state == "rejected",
            )
        }
        held = {
            i for (i,) in self._s.query(AuditLog.id).filter(AuditLog.entity_id.in_(ids))
        }
        refused |= {
            c.entity_id
            for c in self._s.query(SyncConflict).filter(
                SyncConflict.entity_id.in_(ids), SyncConflict.kind == "rejected"
            )
            if c.op_id is not None and c.op_id not in held  # a seed's refusal
        }
        taken = {
            i
            for (i,) in self._s.query(AuditLog.entity_id).filter(
                AuditLog.entity_id.in_(refused),
                AuditLog.hub_seq.is_not(None),
                AuditLog.action.in_(("create", "update", "restore")),
            )
        }
        return refused - taken

    def mark_folded(self, entry_ids: list[uuid.UUID], state: str) -> None:
        """Entries sent as part of one create of the thing as it was (see
        `SyncService._send_whole`): settled with it (`state`), and never applied
        as steps of their own, since the create stands for all of them."""
        if entry_ids:
            self._s.execute(
                update(AuditLog)
                .where(AuditLog.id.in_(entry_ids))
                .values(sync_state=state, apply_state="superseded")
                .execution_options(synchronize_session=False)
            )
            self._s.expire_all()

    def mark_seq(
        self, entry_id: uuid.UUID, seq: int, device: str | None = None
    ) -> None:
        """The authority has numbered a change made here: it is theirs now too,
        and says which device it came through (this one, by its token's name)."""
        row = self._s.get(AuditLog, entry_id)
        if row is not None:
            row.hub_seq = seq
            if device:
                row.device = device
            if row.sync_state == "pending":
                row.sync_state = "synced"
            self._s.flush()

    def latest_hlc(self) -> str | None:
        return self._s.query(func.max(AuditLog.hlc)).scalar()

    def all_ids(self, kind: str) -> set[str]:
        """Every id of `kind` held here, deleted ones included."""
        model = _MODELS[kind]
        return {str(i) for (i,) in self._s.query(model.id)}

    def existing_ids(self, kind: str, ids: set[str]) -> set[str]:
        """Which of these ids are things of `kind` here, deleted or not."""
        if not ids:
            return set()
        model = _MODELS[kind]
        wanted = [uuid.UUID(i) for i in ids]
        return {str(i) for (i,) in self._s.query(model.id).filter(model.id.in_(wanted))}

    def begin_seed(self) -> None:
        """Set aside the changes a seed covers: those not yet sent when the
        first attempt began. A seed run again after an interruption keeps the
        first attempt's set (any left are still `seeding`), so a change made in
        between is still sent on its own."""
        started = (
            self._s.query(AuditLog.id).filter(AuditLog.sync_state == "seeding").first()
        )
        if started is None:
            self._s.execute(
                update(AuditLog)
                .where(AuditLog.sync_state == "pending", AuditLog.hub_seq.is_(None))
                .values(sync_state="seeding")
                .execution_options(synchronize_session=False)
            )
            self._s.expire_all()

    def finish_seed(self) -> None:
        """The seed went in: what it covered counts as sent."""
        self._s.execute(
            update(AuditLog)
            .where(AuditLog.sync_state == "seeding")
            .values(sync_state="synced")
            .execution_options(synchronize_session=False)
        )
        self._s.expire_all()

    def mark_all_synced(self) -> None:
        """Everything so far is covered by a snapshot the authority holds."""
        self._s.execute(
            update(AuditLog)
            .where(AuditLog.sync_state == "pending")
            .values(sync_state="synced")
            .execution_options(synchronize_session=False)
        )
        self._s.expire_all()

    def insert_entry(
        self,
        entry: SyncEntry,
        *,
        hub_seq: int | None,
        state: str = "synced",
        apply_state: str = "applied",
    ) -> None:
        """Keep an entry made elsewhere in this project's history, as it was."""
        batch_id = None
        if entry.batch is not None:
            batch_id = entry.batch.id
            if self._s.get(AuditBatch, batch_id) is None:
                self._s.add(
                    AuditBatch(
                        id=batch_id,
                        kind=entry.batch.kind,
                        label=entry.batch.label,
                        ref=entry.batch.ref,
                        created_at=_parse(entry.batch.created_at),
                    )
                )
                self._s.flush()
        self._s.add(
            AuditLog(
                id=entry.id,
                action=entry.action,
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
                old_data=entry.old_data,
                new_data=entry.new_data,
                delta=entry.delta,
                format=2 if entry.delta is not None else 1,
                op_id=uuid.UUID(entry.op) if entry.op else None,
                timestamp=_parse(entry.timestamp),
                batch_id=batch_id,
                actor=entry.actor,
                device=entry.device,
                device_id=uuid.UUID(entry.device_id) if entry.device_id else None,
                hlc=entry.hlc,
                hub_seq=hub_seq,
                sync_state=state,
                apply_state=apply_state,
            )
        )
        self._s.flush()

    def held_entries(self) -> list[SyncEntry]:
        """Changes from the authority kept but not applied yet, oldest first."""
        rows = (
            self._s.query(AuditLog)
            .filter(AuditLog.apply_state == "held")
            .order_by(AuditLog.hub_seq)
            .all()
        )
        return self._entries(rows)

    def mark_applied(self, entry_ids: list[uuid.UUID]) -> None:
        if entry_ids:
            self._s.execute(
                update(AuditLog)
                .where(AuditLog.id.in_(entry_ids))
                .values(apply_state="applied")
                .execution_options(synchronize_session=False)
            )
            self._s.expire_all()

    def entries_of_action(self, op: str) -> list[SyncEntry]:
        """The entries one action wrote here, in the order written."""
        rows = (
            self._s.query(AuditLog)
            .filter(AuditLog.op_id == uuid.UUID(op))
            .order_by(*_WRITE_ORDER)
            .all()
        )
        return self._entries(rows)

    def numbered_entries(
        self, kind: str, entity_id: uuid.UUID, from_seq: int
    ) -> list[SyncEntry]:
        """A thing's numbered entries from `from_seq` on that the authority did
        not supersede, in its order: the steps that take the thing to where the
        authority has it."""
        rows = (
            self._s.query(AuditLog)
            .filter(
                AuditLog.entity_type == kind,
                AuditLog.entity_id == entity_id,
                AuditLog.hub_seq >= from_seq,
                AuditLog.apply_state != "superseded",
            )
            .order_by(AuditLog.hub_seq)
            .all()
        )
        return self._entries(rows)

    def sequence_local_entries(self) -> int:
        """Authority: number the changes made on this instance itself, in the
        order they were made, so they join the feed. Returns how many."""
        rows = (
            self._s.query(AuditLog)
            .filter(AuditLog.hub_seq.is_(None), AuditLog.sync_state == "pending")
            .order_by(*_WRITE_ORDER)
            .all()
        )
        for row in rows:
            row.hub_seq = self.next_hub_seq()
            row.sync_state = "synced"
        self._s.flush()
        return len(rows)

    def entries_after(self, seq: int, limit: int) -> tuple[list[SyncEntry], bool]:
        """Numbered entries past `seq`, in order, and whether more follow. A
        page ends with the action its last entry belongs to, never inside
        one: a device takes an action whole (a tree moved to another
        collection is one), so a page that cut one in two would leave it
        half done at the device's commit."""
        rows = (
            self._s.query(AuditLog)
            .filter(AuditLog.hub_seq > seq)
            .order_by(AuditLog.hub_seq)
            .limit(limit + 1)
            .all()
        )
        more = len(rows) > limit
        rows = rows[:limit]
        if more and rows and rows[-1].op_id is not None:
            rest = (
                self._s.query(AuditLog)
                .filter(AuditLog.hub_seq > rows[-1].hub_seq)
                .order_by(AuditLog.hub_seq)
                .limit(limit + 1)
                .all()
            )
            same = 0
            while same < len(rest) and rest[same].op_id == rows[-1].op_id:
                same += 1
            rows += rest[:same]
            more = len(rest) > same
        return self._entries(rows), more

    def _entries(self, rows: list[AuditLog]) -> list[SyncEntry]:
        batch_ids = {r.batch_id for r in rows if r.batch_id}
        batches = (
            {
                b.id: SyncBatchInfo(
                    id=b.id,
                    kind=b.kind,
                    label=b.label,
                    ref=b.ref,
                    created_at=_iso(b.created_at) or "",
                )
                for b in self._s.query(AuditBatch).filter(AuditBatch.id.in_(batch_ids))
            }
            if batch_ids
            else {}
        )
        ids = [r.id for r in rows]
        superseded = (
            {
                op_id
                for (op_id,) in self._s.query(SyncOp.op_id).filter(
                    SyncOp.op_id.in_(ids), SyncOp.status.in_(("merged", "conflict"))
                )
            }
            if ids
            else set()
        )
        return [
            SyncEntry(
                id=r.id,
                action=r.action,
                entity_type=r.entity_type,
                entity_id=r.entity_id,
                old_data=r.old_data,
                new_data=r.new_data,
                timestamp=_iso(r.timestamp) or "",
                actor=r.actor,
                device=r.device,
                device_id=str(r.device_id) if r.device_id else None,
                hlc=r.hlc,
                batch=batches.get(r.batch_id) if r.batch_id else None,
                hub_seq=r.hub_seq,
                superseded=r.id in superseded,
                delta=r.delta,
                op=str(r.op_id) if r.op_id else None,
            ).on_the_wire()
            for r in rows
        ]


def _coerce(column: Any, value: Any) -> Any:
    """A snapshot's JSON value in the type its column holds."""
    if value is None:
        return None
    kind = column.type
    if isinstance(kind, _UTCDateTime) and isinstance(value, str):
        return _parse(value)
    if getattr(kind, "python_type", None) is uuid.UUID and isinstance(value, str):
        return uuid.UUID(value)
    if isinstance(kind, BigInteger) and isinstance(value, str):
        return int(value)
    return value


def _brief(error: Exception) -> str:
    """The first line of what the database said, without the SQL."""
    text_ = str(getattr(error, "orig", error)).strip().splitlines()
    return text_[0] if text_ else "A rule of the database was broken"


def _device_dto(row: SyncDevice) -> SyncDeviceDTO:
    return SyncDeviceDTO(
        id=row.id,
        name=row.name,
        device_id=row.device_id,
        public_key=row.public_key,
        created_at=_iso(row.created_at) or "",
        last_seen_at=_iso(row.last_seen_at),
        revoked_at=_iso(row.revoked_at),
        may_publish=bool(row.may_publish),
    )


def _login_dto(row: SyncLoginRequest) -> LoginRequestDTO:
    return LoginRequestDTO(
        id=row.id,
        user_code=row.user_code,
        device_id=row.device_id,
        public_key=row.public_key,
        created_at=_iso(row.created_at) or "",
        expires_at=_iso(row.expires_at) or "",
        name=row.name,
        approved_at=_iso(row.approved_at),
        denied_at=_iso(row.denied_at),
    )


def _invite_dto(row: SyncInvite) -> SyncInviteDTO:
    return SyncInviteDTO(
        id=row.id,
        name=row.name,
        created_at=_iso(row.created_at) or "",
        expires_at=_iso(row.expires_at) or "",
        used_at=_iso(row.used_at),
        revoked_at=_iso(row.revoked_at),
    )


def _conflict_dto(row: SyncConflict) -> SyncConflictDTO:
    return SyncConflictDTO(
        id=row.id,
        kind=row.kind,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        field=row.field,
        yours=row.yours,
        theirs=row.theirs,
        op_id=row.op_id,
        device_name=row.device_name,
        message=row.message,
        base=row.base,
        theirs_actor=row.theirs_actor,
        theirs_device=row.theirs_device,
        theirs_at=_iso(row.theirs_at),
        status=row.status,
        created_at=_iso(row.created_at) or "",
        resolved_at=_iso(row.resolved_at),
        resolution=row.resolution,
        code=row.code,
        retries=row.retries or 0,
        retried_at=_iso(row.retried_at),
    )
