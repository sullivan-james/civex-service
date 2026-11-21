from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from civex.db.models import AuditLog, Record, Release
from civex.domain.dtos import ReleaseDTO
from civex.repositories.local._ids import prefix_span

_WRITABLE = frozenset(c.name for c in Release.__table__.columns) - {"id"}


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

    def bundle_shas(self) -> list[str]:
        return list(self._s.scalars(select(Release.bundle_sha256).distinct()))

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

    def changes_since(
        self, local_seq: int | None, feed_seq: int | None
    ) -> tuple[list[tuple[uuid.UUID | None, int, int, int]], dict[str, int]]:
        """What happened after a history position: per collection a record is
        in now (None: deleted for good), how many records were added, changed
        (edited, moved, deleted and brought back) and deleted (and still are);
        and how many entries were about each other kind. After `feed_seq`: the
        authority's numbers above it, plus changes not numbered yet; else after
        `local_seq` in this copy's own order. Two queries however much changed."""
        if feed_seq is not None:
            since = or_(AuditLog.hub_seq > feed_seq, AuditLog.hub_seq.is_(None))
        else:
            since = AuditLog.local_seq > (local_seq or 0)

        def flag(*actions: str):
            return func.max(case((AuditLog.action.in_(actions), 1), else_=0))

        per = (
            select(
                AuditLog.entity_id.label("id"),
                flag("create").label("made"),
                flag("delete", "purge").label("gone"),
                flag("update", "restore").label("edited"),
            )
            .where(AuditLog.entity_type == "record", since)
            .group_by(AuditLog.entity_id)
            .subquery()
        )
        live = Record.deleted_at.is_(None)
        old = per.c.made == 0
        rows = self._s.execute(
            select(
                Record.dataset_id,
                func.sum(case(((per.c.made == 1) & live, 1), else_=0)),
                func.sum(
                    case(
                        (old & live & ((per.c.edited == 1) | (per.c.gone == 1)), 1),
                        else_=0,
                    )
                ),
                func.sum(
                    case(
                        (old & (per.c.gone == 1) & (Record.id.is_(None) | ~live), 1),
                        else_=0,
                    )
                ),
            )
            .select_from(per)
            .outerjoin(Record, Record.id == per.c.id)
            .group_by(Record.dataset_id)
        ).all()
        others = dict(
            self._s.execute(
                select(AuditLog.entity_type, func.count())
                .where(AuditLog.entity_type != "record", since)
                .group_by(AuditLog.entity_type)
            ).all()
        )
        return (
            [(cid, int(a or 0), int(c or 0), int(d or 0)) for cid, a, c, d in rows],
            {str(k): int(v) for k, v in others.items()},
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
        scope=dict(row.scope or {}),
        include_files=bool(row.include_files),
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
    )
