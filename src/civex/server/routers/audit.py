from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from civex.context import AppContext
from civex.domain.exceptions import NotFoundError
from civex.server.deps import get_ctx
from civex.domain.query import TableQuery
from civex.server.models import AuditLogResponse, PaginatedAuditLogResponse
from civex.server.query_params import table_query

router = APIRouter(tags=["audit"])


def audit_page(
    ctx: AppContext, table: TableQuery, offset: int, limit: int, **scope
) -> PaginatedAuditLogResponse:
    """One page of audit entries for `scope` (entity_id / entity_type /
    entity_ids), narrowed and ordered by the shared table query. Every audit
    endpoint answers through this, so they filter and sort identically."""
    items = ctx.audit_svc.list_audit(offset=offset, limit=limit, table=table, **scope)
    return PaginatedAuditLogResponse(
        items=[AuditLogResponse.from_dto(a) for a in items],
        total=ctx.audit_svc.count_audit(table=table, **scope),
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
    table: TableQuery = Depends(table_query),
    ctx: AppContext = Depends(get_ctx),
):
    """General-purpose audit search, filterable by entity type and/or id.
    Prefer `/records/{id}/audit` or `/schemas/{name}/audit` when scoping to a
    single known resource — this endpoint is for cross-entity queries."""
    try:
        uid = uuid.UUID(entity_id) if entity_id else None
    except ValueError:
        raise HTTPException(400, detail="Invalid entity ID")
    return audit_page(ctx, table, offset, limit, entity_id=uid, entity_type=entity_type)


@router.get("/records/{record_id}/audit", response_model=PaginatedAuditLogResponse)
def list_record_audit(
    record_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=1000),
    table: TableQuery = Depends(table_query),
    ctx: AppContext = Depends(get_ctx),
):
    """Audit entries for a single record — every create/update/delete recorded
    against it, most recent first."""
    try:
        record = ctx.record_svc.get(record_id)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    return audit_page(
        ctx, table, offset, limit, entity_id=record.id, entity_type="record"
    )


@router.get("/schemas/{name}/audit", response_model=PaginatedAuditLogResponse)
def list_schema_audit(
    name: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=1000),
    table: TableQuery = Depends(table_query),
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
    return audit_page(ctx, table, offset, limit, entity_ids=entity_ids)
