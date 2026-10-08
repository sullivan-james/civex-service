"""The authority's library of shared workflows and plugins (`library_items`)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from civex.db.models import LibraryItem
from civex.domain.library import LibraryItemDTO


class LocalLibraryRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def all(self) -> list[LibraryItemDTO]:
        rows = self._s.query(LibraryItem).order_by(LibraryItem.kind, LibraryItem.name)
        return [_dto(r, with_content=False) for r in rows]

    def get(self, kind: str, name: str) -> LibraryItemDTO | None:
        row = self._s.query(LibraryItem).filter_by(kind=kind, name=name).first()
        return _dto(row, with_content=True) if row else None

    def count(self) -> int:
        return self._s.query(func.count(LibraryItem.id)).scalar() or 0

    def provider_of(self, plugin_id: str) -> str | None:
        """The name of the shared plugin that provides `plugin_id`, if any."""
        row = (
            self._s.query(LibraryItem.name)
            .filter_by(kind="plugin", provides=plugin_id)
            .first()
        )
        return row[0] if row else None

    def put(self, item: LibraryItemDTO) -> LibraryItemDTO:
        """Store a published item. The same text again changes nothing; new
        text is the next version."""
        row = (
            self._s.query(LibraryItem).filter_by(kind=item.kind, name=item.name).first()
        )
        if row is not None and row.sha256 == item.sha256:
            return _dto(row, with_content=False)
        if row is None:
            row = LibraryItem(kind=item.kind, name=item.name, version=1)
            self._s.add(row)
        else:
            row.version = (row.version or 0) + 1
        row.content = item.content or ""
        row.sha256 = item.sha256
        row.size = item.size
        row.title = item.title
        row.description = item.description
        row.provides = item.provides
        row.needs = list(item.needs)
        row.triggers = list(item.triggers)
        row.published_by = item.published_by
        row.published_at = datetime.now(timezone.utc)
        self._s.flush()
        return _dto(row, with_content=False)

    def remove(self, kind: str, name: str) -> bool:
        removed = self._s.query(LibraryItem).filter_by(kind=kind, name=name).delete()
        self._s.flush()
        return bool(removed)


def _dto(row: LibraryItem, with_content: bool) -> LibraryItemDTO:
    return LibraryItemDTO(
        kind=row.kind,
        name=row.name,
        sha256=row.sha256,
        size=row.size,
        version=row.version,
        title=row.title,
        description=row.description,
        provides=row.provides,
        needs=list(row.needs or []),
        triggers=list(row.triggers or []),
        published_by=row.published_by,
        published_at=row.published_at.isoformat() if row.published_at else None,
        content=row.content if with_content else None,
    )
