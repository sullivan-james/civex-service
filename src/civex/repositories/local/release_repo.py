from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    delete,
    func,
    insert,
    literal,
    select,
    update,
)
from sqlalchemy.orm import Session, aliased

from civex.db.models import AuditLog, FileReference, Record, Release, StoredObject
from civex.domain.dtos import ReleaseDTO
from civex.repositories.local._ids import prefix_span

_WRITABLE = frozenset(c.name for c in Release.__table__.columns) - {"id"}
_CHUNK = 500


class LocalReleaseRepository:
    """Releases (`civex.domain.release`). Plain storage plus the two history
    questions a release asks (where history is now, and what changed since);
    the rules, permissions and history entries are `ReleaseService`'s."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, id: uuid.UUID) -> ReleaseDTO | None:
        row = self._s.get(Release, id)
        return _to_dto(row) if row is not None else None

    def get_by_name(self, name: str) -> ReleaseDTO | None:
        row = self._s.query(Release).filter(Release.name == name).one_or_none()
        return _to_dto(row) if row is not None else None

    def get_by_prefix(self, prefix: str) -> ReleaseDTO | None:
        """A release by id or the start of it (4 hex digits at least), when
        exactly one matches."""
        try:
            return self.get(uuid.UUID(prefix))
        except ValueError:
            pass
        span = prefix_span(prefix)
        if span is None or len(prefix.replace("-", "")) < 4:
            return None
        rows = self._s.query(Release).filter(Release.id.between(*span)).limit(2).all()
        return _to_dto(rows[0]) if len(rows) == 1 else None

    def list_all(self) -> list[ReleaseDTO]:
        """Every release, newest first."""
        rows = self._s.query(Release).order_by(Release.created_at.desc(), Release.name)
        return [_to_dto(r) for r in rows]

    # -- the files a release owns (file_references.release_id) ---------------

    def own_cited(
        self,
        release_id: uuid.UUID,
        collections: list[uuid.UUID] | None,
        record_ids: list[uuid.UUID] | None,
    ) -> int:
        """Make the release own every file the live records of these
        collections (all, when None), or exactly these records, cite: one
        INSERT ... SELECT from their own file_references rows (per 500 ids
        for records), each pointing at the copy its records point at. No
        record or file is read. Returns how many files it owns."""
        if record_ids is not None:
            for i in range(0, len(record_ids), _CHUNK):
                self._own_from(
                    release_id, FileReference.record_id.in_(record_ids[i : i + _CHUNK])
                )
        else:
            cond: Any = Record.deleted_at.is_(None)
            if collections is not None:
                cond = cond & Record.dataset_id.in_(collections)
            self._own_from(release_id, cond)
        self._s.execute(
            update(Release).where(Release.id == release_id).values(indexed=True)
        )
        return self.owned(release_id)

    def _own_from(self, release_id: uuid.UUID, cond: Any) -> None:
        mine_t = aliased(FileReference)
        mine = (
            select(mine_t.id)
            .where(
                mine_t.release_id == release_id,
                mine_t.sha256 == FileReference.sha256,
            )
            .exists()
        )
        rows = (
            select(
                self._new_id(),
                FileReference.sha256,
                literal(release_id, FileReference.release_id.type),
                func.max(FileReference.volume),
            )
            .join(Record, Record.id == FileReference.record_id)
            .where(cond, ~mine)
            .group_by(FileReference.sha256)
        )
        self._s.execute(
            insert(FileReference).from_select(
                ["id", "sha256", "release_id", "volume"], rows
            )
        )

    def _new_id(self) -> Any:
        """A fresh uuid made by the database, for INSERT ... SELECT."""
        if self._s.get_bind().dialect.name == "postgresql":
            return func.gen_random_uuid()
        return func.lower(func.hex(func.randomblob(16)))

    def own(self, release_id: uuid.UUID, shas: list[str]) -> None:
        """Make the release own these files (its bundle, or what its bundle
        cites once it is here), each pointing at its newest copy here (None
        until one is: recording a copy then points at it)."""
        have = set(
            self._s.scalars(
                select(FileReference.sha256).where(
                    FileReference.release_id == release_id
                )
            )
        )
        wanted = sorted(set(shas) - have)
        for i in range(0, len(wanted), _CHUNK):
            chunk = wanted[i : i + _CHUNK]
            newest: dict[str, str] = {}
            for sha, volume in self._s.execute(
                select(StoredObject.sha256, StoredObject.volume)
                .where(StoredObject.sha256.in_(chunk))
                .order_by(StoredObject.created_at, StoredObject.volume)
            ):
                newest[sha] = volume
            self._s.execute(
                insert(FileReference),
                [
                    {
                        "id": uuid.uuid4(),
                        "sha256": sha,
                        "release_id": release_id,
                        "volume": newest.get(sha),
                    }
                    for sha in chunk
                ],
            )
        self._s.flush()

    def owned_pointers(self, release_id: uuid.UUID) -> dict[str, str | None]:
        """Each file a release owns and the copy it points at (None: no copy
        here yet)."""
        return {
            sha: volume
            for sha, volume in self._s.execute(
                select(FileReference.sha256, FileReference.volume).where(
                    FileReference.release_id == release_id
                )
            )
        }

    def owned(self, release_id: uuid.UUID) -> int:
        return int(
            self._s.scalar(
                select(func.count()).where(FileReference.release_id == release_id)
            )
            or 0
        )

    def owned_shas(
        self, release_id: uuid.UUID, after: str = "", limit: int = 1000
    ) -> list[str]:
        """The files a release owns (its bundle included), in hash order after
        `after`, `limit` at a time."""
        return list(
            self._s.scalars(
                select(FileReference.sha256)
                .where(
                    FileReference.release_id == release_id,
                    FileReference.sha256 > after,
                )
                .order_by(FileReference.sha256)
                .limit(limit)
            )
        )

    def owned_summary(self, release_id: uuid.UUID) -> dict[str, Any]:
        """Where a release's files are, from the catalog: per drive (None: no
        copy here) how many and their bytes, and how many have no copy here
        whose bytes were checked (`unverified`). One grouped query."""
        rows = self._s.execute(
            select(
                FileReference.volume,
                func.count(),
                func.coalesce(func.sum(StoredObject.size), 0),
                func.count().filter(
                    StoredObject.sha256.is_not(None)
                    & StoredObject.verified_at.is_(None)
                ),
            )
            .select_from(FileReference)
            .outerjoin(
                StoredObject,
                (StoredObject.sha256 == FileReference.sha256)
                & (StoredObject.volume == FileReference.volume),
            )
            .where(FileReference.release_id == release_id)
            .group_by(FileReference.volume)
        ).all()
        return {
            "by_volume": [
                {"volume": v, "files": int(n), "bytes": int(b), "unverified": int(u)}
                for v, n, b, u in rows
            ],
        }

    def cited_by_drive(
        self,
        collections: list[uuid.UUID] | None,
        record_ids: list[uuid.UUID] | None,
    ) -> list[tuple[str | None, int, int]]:
        """Where the files records of a scope cite are (the copy each record
        points at): per drive (None: no copy here), distinct files and bytes.
        One grouped query (per 500 ids for records)."""
        found: dict[str | None, dict[str, int]] = {}

        def add(cond: Any) -> None:
            rows = self._s.execute(
                select(
                    FileReference.volume,
                    FileReference.sha256,
                    func.max(StoredObject.size),
                )
                .join(Record, Record.id == FileReference.record_id)
                .outerjoin(
                    StoredObject,
                    (StoredObject.sha256 == FileReference.sha256)
                    & (StoredObject.volume == FileReference.volume),
                )
                .where(cond)
                .group_by(FileReference.volume, FileReference.sha256)
            )
            for volume, sha, size in rows:
                found.setdefault(volume, {})[sha] = int(size or 0)

        if record_ids is not None:
            for i in range(0, len(record_ids), _CHUNK):
                add(FileReference.record_id.in_(record_ids[i : i + _CHUNK]))
        else:
            cond: Any = Record.deleted_at.is_(None)
            if collections is not None:
                cond = cond & Record.dataset_id.in_(collections)
            add(cond)
        return sorted(
            ((v, len(f), sum(f.values())) for v, f in found.items()),
            key=lambda row: (row[0] is None, -row[2]),
        )

    def records_per_collection(
        self,
        collections: list[uuid.UUID] | None,
        record_ids: list[uuid.UUID] | None,
    ) -> dict[uuid.UUID, int]:
        """How many live records of a scope each collection has."""
        out: dict[uuid.UUID, int] = {}

        def add(cond: Any) -> None:
            for cid, n in self._s.execute(
                select(Record.dataset_id, func.count())
                .where(Record.deleted_at.is_(None), cond)
                .group_by(Record.dataset_id)
            ):
                out[cid] = out.get(cid, 0) + int(n)

        if record_ids is not None:
            for i in range(0, len(record_ids), _CHUNK):
                add(Record.id.in_(record_ids[i : i + _CHUNK]))
        elif collections is not None:
            add(Record.dataset_id.in_(collections))
        else:
            add(literal(True))
        return out

    def inventory_state(self, shas: list[str]) -> tuple[set[str], set[str]]:
        """Of these files: those with no copy recorded here, and those whose
        every copy here is unchecked (`verified_at` empty). Per 500 files."""
        recorded: set[str] = set()
        checked: set[str] = set()
        for i in range(0, len(shas), _CHUNK):
            for sha, verified in self._s.execute(
                select(StoredObject.sha256, StoredObject.verified_at).where(
                    StoredObject.sha256.in_(shas[i : i + _CHUNK])
                )
            ):
                recorded.add(sha)
                if verified is not None:
                    checked.add(sha)
        return set(shas) - recorded, recorded - checked

    def disown(self, release_id: uuid.UUID) -> int:
        """Give up every file a release owns (a yank); returns how many."""
        n = self.owned(release_id)
        self._s.execute(
            delete(FileReference).where(FileReference.release_id == release_id)
        )
        self._s.flush()
        return n

    def lock(self, id: uuid.UUID) -> ReleaseDTO | None:
        """The release as it is now, its row locked until the transaction ends
        (so a publish and a discard of it take turns); None if it is gone."""
        row = self._s.scalars(
            select(Release)
            .where(Release.id == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one_or_none()
        return _to_dto(row) if row is not None else None

    def delete(self, id: uuid.UUID) -> None:
        """Remove the release's row (its owned files go with `disown`)."""
        self._s.execute(delete(Release).where(Release.id == id))
        self._s.flush()

    def create(self, **values: Any) -> ReleaseDTO:
        row = Release(id=values.pop("id", None) or uuid.uuid4(), **values)
        self._s.add(row)
        self._s.flush()
        return _to_dto(row)

    def update(self, id: uuid.UUID, **values: Any) -> ReleaseDTO:
        row = self._s.get(Release, id)
        if row is None:
            raise KeyError(id)
        for name, value in values.items():
            if name not in _WRITABLE:
                raise KeyError(name)
            setattr(row, name, value)
        self._s.flush()
        return _to_dto(row)

    # -- history ---------------------------------------------------------------

    def history_position(self) -> int:
        """The newest history entry's write order here (0 when there is none)."""
        return int(self._s.scalar(select(func.max(AuditLog.local_seq))) or 0)

    # -- the records a release is compared with -------------------------------

    def database_key(self) -> str:
        """Which database this is (a comparison is remembered per database)."""
        bind = self._s.get_bind()
        return str(getattr(bind, "url", id(bind)))

    def stored_rows(self, ids: list[str]) -> list[StoredRow]:
        """The live records among `ids`, as stored: (id, collection id, schema
        id, parent id, data keyed by field id). One query."""
        if not ids:
            return []
        wanted = [uuid.UUID(i) for i in ids]
        return [
            (str(r[0]), str(r[1]), str(r[2]), str(r[3]) if r[3] else None, r[4] or {})
            for r in self._s.execute(
                select(*_ROW).where(Record.id.in_(wanted), Record.deleted_at.is_(None))
            )
        ]

    def live_rows(
        self, collections: list[uuid.UUID] | None, after: str | None, limit: int
    ) -> list[StoredRow]:
        """A page of the live records (in `collections`, else all) in id
        order, after `after`, as stored. One query."""
        q = select(*_ROW).where(Record.deleted_at.is_(None))
        if collections is not None:
            q = q.where(Record.dataset_id.in_(collections))
        if after is not None:
            q = q.where(Record.id > uuid.UUID(after))
        return [
            (str(r[0]), str(r[1]), str(r[2]), str(r[3]) if r[3] else None, r[4] or {})
            for r in self._s.execute(q.order_by(Record.id).limit(limit))
        ]


#: A record as stored: id, collection id, schema id, parent id, data by field id.
StoredRow = tuple[str, str, str, str | None, dict[str, Any]]
_ROW = (
    Record.id,
    Record.dataset_id,
    Record.schema_id,
    Record.parent_record_id,
    Record.data,
)


def _to_dto(row: Release) -> ReleaseDTO:
    return ReleaseDTO(
        id=row.id,
        name=row.name,
        title=row.title,
        description=row.description,
        authors=list(row.authors or []),
        licence=row.licence,
        doi=row.doi,
        keywords=list(row.keywords or []),
        scope=dict(row.scope or {}),
        content_hash=row.content_hash,
        bundle_sha256=row.bundle_sha256,
        bundle_size=int(row.bundle_size or 0),
        counts=dict(row.counts or {}),
        local_seq=row.local_seq,
        feed_seq=row.feed_seq,
        civex_version=row.civex_version or "",
        created_at=row.created_at,
        created_by=row.created_by,
        updated_at=row.updated_at,
        withdrawn_at=row.withdrawn_at,
        withdrawn_by=row.withdrawn_by,
        withdrawn_reason=row.withdrawn_reason,
        yanked_at=row.yanked_at,
        yanked_by=row.yanked_by,
        yanked_reason=row.yanked_reason,
        published_at=row.published_at,
    )
