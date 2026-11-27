"""Small readers shared by the delete-race tests."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from civex.db.models import AuditLog, Record


def live_ids(ctx) -> set[uuid.UUID]:
    ctx._session.expire_all()
    return set(
        ctx._session.scalars(select(Record.id).where(Record.deleted_at.is_(None)))
    )


def deletes(ctx, rid) -> list[uuid.UUID]:
    q = select(AuditLog.id).where(AuditLog.action == "delete")
    if rid is not None:
        q = q.where(AuditLog.entity_id == rid)
    return list(ctx._session.scalars(q))
