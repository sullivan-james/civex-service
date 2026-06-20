from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from civex.config import load_config
from civex.context import AppContext
from civex.domain.exceptions import ConfigError
from civex.server.deps import get_ctx
from civex.services.sync_service import SyncService
from civex.sync.transport import SyncError

router = APIRouter(prefix="/remote", tags=["remote"])


class RemoteStatus(BaseModel):
    url: str
    last_pushed_at: datetime | None
    last_pulled_at: datetime | None


class SyncResponse(BaseModel):
    schemas: int
    datasets: int
    records: int
    objects: int


def _load_cfg():
    try:
        return load_config()
    except ConfigError as e:
        raise HTTPException(500, detail=str(e))


@router.get("", response_model=RemoteStatus)
def remote_status():
    """Return the configured remote URL and last sync timestamps."""
    config = _load_cfg()
    if config.remote is None:
        raise HTTPException(404, detail="No remote configured")
    return RemoteStatus(
        url=config.remote.url,
        last_pushed_at=config.remote.last_pushed_at,
        last_pulled_at=config.remote.last_pulled_at,
    )


@router.post("/push", response_model=SyncResponse)
def remote_push(ctx: AppContext = Depends(get_ctx)):
    """Push local changes (including any uncommitted edits) to the remote."""
    config = _load_cfg()
    if config.remote is None:
        raise HTTPException(400, detail="No remote configured. Run `civex remote set <url>` first.")
    svc = SyncService(config, ctx._session, ctx.audit_svc, ctx.file_svc._store)
    try:
        result = svc.push()
    except SyncError as e:
        raise HTTPException(502, detail=str(e))
    return SyncResponse(schemas=result.schemas, datasets=result.datasets,
                        records=result.records, objects=result.objects)


@router.post("/pull", response_model=SyncResponse)
def remote_pull(ctx: AppContext = Depends(get_ctx)):
    """Pull remote changes into the local project."""
    config = _load_cfg()
    if config.remote is None:
        raise HTTPException(400, detail="No remote configured. Run `civex remote set <url>` first.")
    svc = SyncService(config, ctx._session, ctx.audit_svc, ctx.file_svc._store)
    try:
        result = svc.pull()
    except SyncError as e:
        raise HTTPException(502, detail=str(e))
    return SyncResponse(schemas=result.schemas, datasets=result.datasets,
                        records=result.records, objects=result.objects)
