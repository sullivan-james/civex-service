"""Following an authority, from this project's side: connect, see how it is
going, sync now, pause, and settle conflicts. (What an authority offers to devices
is `/sync/v1`; this is for people.)"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from civex.context import AppContext
from civex.domain.sync import SyncError
from civex.server.deps import get_ctx
from civex.services.sync_jobs import sync_jobs

router = APIRouter(prefix="/remote", tags=["sync"])


class RemoteStatusResponse(BaseModel):
    configured: bool = Field(description="Whether this project follows an authority.")
    remote: str | None = Field(description="The authority's address.")
    project_id: str
    paused: bool = Field(description="The schedule is stopped; Sync now still works.")
    interval_seconds: int = Field(description="How often it looks for changes.")
    serving: bool = Field(description="This project is itself an authority.")
    pending: int = Field(description="Changes made here that have not been sent.")
    open_conflicts: int = Field(description="Values that did not go in as made.")
    last_synced_at: str | None
    last_error: str | None = Field(
        description="Why the last attempt failed, if it did."
    )
    last_error_at: str | None
    running: bool = Field(description="A sync is in progress right now.")


class RemoteConnectRequest(BaseModel):
    url: str = Field(description="The authority's address.")
    token: str = Field(description="The device token the authority issued.")


class RemoteConnectResponse(BaseModel):
    mode: str = Field(
        description="joined (became a copy), seeded (filled an empty authority), "
        "empty (both empty) or resumed (already the same project)."
    )


class RemoteUpdateRequest(BaseModel):
    paused: bool | None = Field(default=None, description="Stop or start the schedule.")
    interval_seconds: int | None = Field(
        default=None, ge=5, description="Seconds between looks for changes."
    )


class ConflictResponse(BaseModel):
    id: str
    kind: str = Field(description="conflict, rejected or edit_vs_delete.")
    entity_type: str
    entity_id: str
    field: str | None
    yours: Any = Field(description="The value this device set.")
    theirs: Any = Field(description="The value the authority kept.")
    device_name: str | None
    message: str | None
    status: str = Field(description="open or resolved.")
    created_at: str
    resolved_at: str | None
    resolution: str | None = Field(description="mine or theirs, once resolved.")


class ResolveRequest(BaseModel):
    take: str = Field(
        description="`theirs` keeps the authority's value; `mine` makes yours a new change."
    )


def _status(ctx: AppContext) -> RemoteStatusResponse:
    s = ctx.sync_svc.status()
    return RemoteStatusResponse(
        configured=s.configured,
        remote=s.remote,
        project_id=s.project_id,
        paused=s.paused,
        interval_seconds=s.interval_seconds,
        serving=s.serving,
        pending=s.pending,
        open_conflicts=s.open_conflicts,
        last_synced_at=s.last_synced_at,
        last_error=s.last_error,
        last_error_at=s.last_error_at,
        running=s.running,
    )


def _refuse(e: SyncError) -> HTTPException:
    # Not reachable (try later) is a bad gateway; anything else is the request's.
    return HTTPException(502 if e.retryable else 400, detail=str(e))


@router.get("", response_model=RemoteStatusResponse)
def status(ctx: AppContext = Depends(get_ctx)):
    """How this project stands with its authority."""
    return _status(ctx)


@router.post("/connect", response_model=RemoteConnectResponse)
def connect(body: RemoteConnectRequest, ctx: AppContext = Depends(get_ctx)):
    """Point this project at an authority. An empty project becomes a copy of
    it; a project with data fills an empty authority; two with data are refused."""
    try:
        mode = ctx.sync_svc.connect(body.url, body.token)
    except SyncError as e:
        raise _refuse(e)
    ctx.commit()
    sync_jobs.ensure_worker()
    return RemoteConnectResponse(mode=mode)


@router.post("/disconnect", response_model=RemoteStatusResponse)
def disconnect(ctx: AppContext = Depends(get_ctx)):
    """Stop following the authority. The data here stays."""
    ctx.sync_svc.disconnect()
    ctx.commit()
    return _status(ctx)


@router.post("/sync", status_code=202)
def sync_now(ctx: AppContext = Depends(get_ctx)):
    """Ask for a sync now. It runs in the background; `GET /remote` shows how it went."""
    if not ctx.sync_svc.configured:
        raise HTTPException(400, detail="This project is not following an authority")
    sync_jobs.sync_now()
    return {"requested": True}


@router.patch("", response_model=RemoteStatusResponse)
def update(body: RemoteUpdateRequest, ctx: AppContext = Depends(get_ctx)):
    """Pause or resume the schedule, or change how often it looks."""
    if body.paused is not None:
        ctx.sync_svc.set_paused(body.paused)
    if body.interval_seconds is not None:
        ctx.sync_svc.set_interval(body.interval_seconds)
    return _status(ctx)


@router.get("/conflicts", response_model=list[ConflictResponse])
def conflicts(
    status: str | None = Query(default="open", description="open, resolved, or all."),
    ctx: AppContext = Depends(get_ctx),
):
    """Values that did not go in as made, with both sides."""
    found = ctx.sync_svc.conflicts(None if status in (None, "all") else status)
    return [
        ConflictResponse(
            id=str(c.id),
            kind=c.kind,
            entity_type=c.entity_type,
            entity_id=str(c.entity_id),
            field=c.field,
            yours=c.yours,
            theirs=c.theirs,
            device_name=c.device_name,
            message=c.message,
            status=c.status,
            created_at=c.created_at,
            resolved_at=c.resolved_at,
            resolution=c.resolution,
        )
        for c in found
    ]


@router.post("/conflicts/{conflict_id}/resolve", response_model=RemoteStatusResponse)
def resolve(conflict_id: str, body: ResolveRequest, ctx: AppContext = Depends(get_ctx)):
    """Settle a conflict by keeping theirs or making yours a new change."""
    try:
        cid = uuid.UUID(conflict_id)
    except ValueError:
        raise HTTPException(422, detail="Not a conflict id")
    ctx.sync_svc.resolve_conflict(cid, body.take)
    return _status(ctx)
