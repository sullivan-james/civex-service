from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from civex.context import AppContext
from civex.domain.exceptions import (
    AlreadyExistsError,
    NotFoundError,
    ValidationError,
    VolumeUnavailableError,
)
from civex.server.deps import get_ctx
from civex.server.models import (
    AddVolumeRequest,
    SetQueueRequest,
    UpdateVolumeRequest,
    VolumeStatsResponse,
)
from civex.services.store_service import _UNSET

router = APIRouter(prefix="/store", tags=["store"])


@router.get("/volumes", response_model=list[VolumeStatsResponse])
def list_volumes(ctx: AppContext = Depends(get_ctx)):
    return ctx.store_svc.volume_stats()


@router.post("/volumes", response_model=VolumeStatsResponse, status_code=201)
def add_volume(body: AddVolumeRequest, ctx: AppContext = Depends(get_ctx)):
    try:
        ctx.store_svc.add_volume(body.name, body.path, body.allocated_gb)
    except AlreadyExistsError as e:
        raise HTTPException(409, detail=str(e))
    except (ValidationError, VolumeUnavailableError) as e:
        raise HTTPException(422, detail=str(e))
    stats = ctx.store_svc.volume_stats()
    vol = next((v for v in stats if v["name"] == body.name), None)
    if vol is None:
        raise HTTPException(500, "Volume created but not found in stats")
    return vol


@router.patch("/volumes/{name}", response_model=VolumeStatsResponse)
def update_volume(
    name: str, body: UpdateVolumeRequest, ctx: AppContext = Depends(get_ctx)
):
    alloc = _UNSET
    if body.allocated_gb is not None:
        alloc = body.allocated_gb
    elif body.clear_allocation:
        alloc = None
    try:
        ctx.store_svc.update_volume(name, path=body.path, allocated_gb=alloc)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    stats = ctx.store_svc.volume_stats()
    vol = next((v for v in stats if v["name"] == name), None)
    return vol


@router.delete("/volumes/{name}", status_code=204)
def remove_volume(name: str, force: bool = False, ctx: AppContext = Depends(get_ctx)):
    try:
        ctx.store_svc.remove_volume(name, force=force)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(409, detail=str(e))


@router.put("/queue", response_model=list[str])
def set_queue(body: SetQueueRequest, ctx: AppContext = Depends(get_ctx)):
    try:
        ctx.store_svc.set_queue(body.queue)
    except (NotFoundError, ValidationError) as e:
        raise HTTPException(422, detail=str(e))
    return ctx.store_svc._config.store_config.volume_queue
