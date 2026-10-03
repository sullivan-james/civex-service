from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from civex.context import AppContext
from civex.domain.exceptions import NotFoundError
from civex.server.deps import get_ctx
from civex.server.models import AuditLogResponse, PaginatedAuditLogResponse

router = APIRouter(tags=["audit"])


class AuditView:
    """The two things a history table can ask for: one kind of action, and an
    order. Taken as a dependency by every audit endpoint."""

    def __init__(
        self,
        action: str | None = Query(
            default=None,
            description="Only entries of this action (create, update, ...).",
        ),
        sort: str | None = Query(
            default=None,
            description="'timestamp' or 'action', optionally ':asc' / ':desc'. "
            "Newest first by default.",
        ),
    ) -> None:
        self.action = action
        self.sort = sort


def audit_page(
    ctx: AppContext, view: AuditView, offset: int, limit: int, **scope
) -> PaginatedAuditLogResponse:
    """One page of audit entries for `scope` (entity_id / entity_type /
    entity_ids). Every audit endpoint answers through this."""
    items = ctx.audit_svc.list_audit(
        offset=offset, limit=limit, action=view.action, sort=view.sort, **scope
    )
    return PaginatedAuditLogResponse(
        items=[AuditLogResponse.from_dto(a) for a in items],
        total=ctx.audit_svc.count_audit(action=view.action, **scope),
        offset=offset,
        limit=limit,
    )


@router.get("/audit", response_model=PaginatedAuditLogResponse)
def list_audit(
    entity_type: str | None = Query(
        default=None,
        description="Filter to one entity type: record, schema, field, dataset.",
    ),
    entity_id: str | None = Query(
        default=None, description="Filter to a single entity's audit trail."
    ),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=1000),
    view: AuditView = Depends(),
    ctx: AppContext = Depends(get_ctx),
):
    """General-purpose audit search, filterable by entity type and/or id.
    Prefer `/records/{id}/audit` or `/schemas/{name}/audit` when scoping to a
    single known resource — this endpoint is for cross-entity queries."""
    try:
        uid = uuid.UUID(entity_id) if entity_id else None
    except ValueError:
        raise HTTPException(400, detail="Invalid entity ID")
    return audit_page(ctx, view, offset, limit, entity_id=uid, entity_type=entity_type)


@router.get("/records/{record_id}/audit", response_model=PaginatedAuditLogResponse)
def list_record_audit(
    record_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=1000),
    view: AuditView = Depends(),
    ctx: AppContext = Depends(get_ctx),
):
    """Audit entries for a single record — every create/update/delete recorded
    against it, most recent first."""
    try:
        record = ctx.record_svc.get(record_id)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    return audit_page(
        ctx, view, offset, limit, entity_id=record.id, entity_type="record"
    )


@router.get("/schemas/{name}/audit", response_model=PaginatedAuditLogResponse)
def list_schema_audit(
    name: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=1000),
    view: AuditView = Depends(),
    ctx: AppContext = Depends(get_ctx),
):
    """Audit entries for a schema and its own fields (not inherited ones),
    most recent first — schema/field renames, field additions and removals,
    restriction changes, and so on."""
    try:
        schema = ctx.schema_svc.get(name)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    entity_ids = [schema.id] + [f.id for f in schema.fields]
    return audit_page(ctx, view, offset, limit, entity_ids=entity_ids)
