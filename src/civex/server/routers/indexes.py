"""Field indexes in this computer's database (`IndexService`): which fields
have one, asking for one, and keeping the database in step. Building happens
on the server's own thread (`index_jobs`), never in the request."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from civex.context import AppContext
from civex.server.deps import get_ctx
from civex.server.models import (
    FieldIndexReportResponse,
    FieldIndexResponse,
    IndexProgressResponse,
    SetFieldIndexRequest,
)
from civex.services.index_jobs import index_jobs, upkeep_running

router = APIRouter(tags=["db"])


def _report(ctx: AppContext) -> FieldIndexReportResponse:
    report = ctx.index_svc.status()
    progress = index_jobs.progress
    return FieldIndexReportResponse(
        fields=[FieldIndexResponse.from_state(s) for s in report.fields],
        stale=report.stale,
        in_step=report.in_step,
        building=progress is not None,
        progress=IndexProgressResponse(**vars(progress)) if progress else None,
        elsewhere=progress is None and upkeep_running(ctx),
        error=index_jobs.error,
    )


@router.get("/db/indexes", response_model=FieldIndexReportResponse)
def list_field_indexes(ctx: AppContext = Depends(get_ctx)):
    """Every field that has, or should have, an index in this computer's
    database (because it is part of a uniqueness key, or a person asked for
    it), whether each is built yet, any managed index nothing wants, and how
    far a build running in the background has got (the status bar)."""
    return _report(ctx)


@router.post(
    "/db/indexes/reconcile", response_model=FieldIndexReportResponse, status_code=202
)
def reconcile_field_indexes(ctx: AppContext = Depends(get_ctx)):
    """Build the missing field indexes and drop the unwanted ones, in the
    background (it can take a while on a big table; on SQLite each build
    waits for a moment when nobody is saving and gives way to saves). Answers
    at once with the state before it starts."""
    index_jobs.request()
    return _report(ctx)


@router.get(
    "/schemas/{name}/fields/{field_name}/index", response_model=FieldIndexResponse
)
def get_field_index(name: str, field_name: str, ctx: AppContext = Depends(get_ctx)):
    """Whether a field has an index in this computer's database, and why."""
    return FieldIndexResponse.from_state(ctx.index_svc.field_status(name, field_name))


@router.put(
    "/schemas/{name}/fields/{field_name}/index", response_model=FieldIndexResponse
)
def set_field_index(
    name: str,
    field_name: str,
    body: SetFieldIndexRequest,
    ctx: AppContext = Depends(get_ctx),
):
    """Ask for an index on a field (sorting by it and filtering it get faster
    on this computer; saving records of its kind gets slightly slower), or stop
    asking for one. A setting of this computer's database: never synced. The
    index is built or dropped in the background; `built` says when it is
    there. A field in a uniqueness key keeps its index either way."""
    state = ctx.index_svc.set_indexed(name, field_name, body.indexed)
    ctx.commit()
    index_jobs.request()
    return FieldIndexResponse.from_state(state)
