"""The authority's library of shared workflows and plugins (`library_items`):
every version of each, one row per version."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session, defer

from civex.db.models import LibraryItem
from civex.domain.library import PLUGIN, WORKFLOW, LibraryItemDTO


class LocalLibraryRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def _rows(self, **where: Any):
        return (
            self._s.query(LibraryItem)
            .options(defer(LibraryItem.content))
            .filter_by(**where)
            .order_by(LibraryItem.kind, LibraryItem.name, LibraryItem.version.desc())
        )

    def latest(self) -> list[LibraryItemDTO]:
        """The newest version of everything, each with its history."""
        by_item: dict[tuple[str, str], list[LibraryItem]] = defaultdict(list)
        for row in self._rows():
            by_item[(row.kind, row.name)].append(row)
        return [_dto(rows[0], history=rows) for rows in by_item.values()]

    def get(
        self, kind: str, name: str, version: int | None = None
    ) -> LibraryItemDTO | None:
        """One version with its text (the newest if `version` is None), with
        the item's history."""
        rows = self._rows(kind=kind, name=name).all()
        if not rows:
            return None
        wanted = (
            rows[0]
            if version is None
            else next((r for r in rows if r.version == version), None)
        )
        if wanted is None:
            return None
        out = _dto(wanted, history=rows)
        out.content = (
            self._s.query(LibraryItem.content).filter_by(id=wanted.id).scalar() or ""
        )
        return out

    def version_of(self, kind: str, name: str, sha256: str) -> int | None:
        row = (
            self._s.query(LibraryItem.version)
            .filter_by(kind=kind, name=name, sha256=sha256)
            .first()
        )
        return row[0] if row else None

    def count(self) -> int:
        return self._s.query(func.count(LibraryItem.id)).scalar() or 0

    def provider_of(self, plugin_id: str) -> str | None:
        """The name of the shared plugin that provides `plugin_id`, if any (a
        plugin's id is the same in every version of it)."""
        row = (
            self._s.query(LibraryItem.name)
            .filter_by(kind=PLUGIN, provides=plugin_id)
            .first()
        )
        return row[0] if row else None

    def pinned_by(self, plugin_id: str, version: int | None = None) -> list[str]:
        """'workflow vN' for every workflow version that pins this plugin (to
        `version`, or to any version)."""
        out = []
        for row in self._rows(kind=WORKFLOW):
            pinned = (row.pins or {}).get(plugin_id)
            if pinned is not None and (version is None or pinned == version):
                out.append(f"{row.name} v{row.version}")
        return out

    def add(self, item: LibraryItemDTO) -> tuple[LibraryItemDTO, bool]:
        """Store a published version. Text that is already one of its versions
        is answered with that version (False: nothing new); new text is the
        next version (True)."""
        same = self.version_of(item.kind, item.name, item.sha256)
        version = same
        if version is None:
            newest = (
                self._s.query(func.max(LibraryItem.version))
                .filter_by(kind=item.kind, name=item.name)
                .scalar()
            )
            version = (newest or 0) + 1
            self._s.add(
                LibraryItem(
                    kind=item.kind,
                    name=item.name,
                    version=version,
                    content=item.content or "",
                    sha256=item.sha256,
                    size=item.size,
                    title=item.title,
                    description=item.description,
                    provides=item.provides,
                    needs=list(item.needs),
                    triggers=list(item.triggers),
                    pins=dict(item.pins),
                    contract=item.contract,
                    published_by=item.published_by,
                    published_at=datetime.now(timezone.utc),
                )
            )
            self._s.flush()
        found = self.get(item.kind, item.name, version)
        assert found is not None
        found.content = None
        return found, same is None

    def remove(self, kind: str, name: str, version: int | None = None) -> int:
        """Remove one version, or every version. How many went."""
        q = self._s.query(LibraryItem).filter_by(kind=kind, name=name)
        if version is not None:
            q = q.filter_by(version=version)
        removed = q.delete()
        self._s.flush()
        return removed


def _when(row: LibraryItem) -> str | None:
    return row.published_at.isoformat() if row.published_at else None


def _dto(row: LibraryItem, history: list[LibraryItem]) -> LibraryItemDTO:
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
        published_at=_when(row),
        pins=dict(row.pins or {}),
        contract=row.contract,
        history=[
            {
                "version": h.version,
                "sha256": h.sha256,
                "published_by": h.published_by,
                "published_at": _when(h),
                "pins": dict(h.pins or {}),
            }
            for h in history
        ],
    )
