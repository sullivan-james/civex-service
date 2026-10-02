from __future__ import annotations

import uuid

from dataclasses import asdict

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
    CreateFolderRequest,
    CreateFolderResponse,
    DirectoryListingResponse,
    GCReportResponse,
    GCRequest,
    PathInspectionResponse,
    PlacementResponse,
    SetPlacementRequest,
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
        ctx.store_svc.add_volume(
            body.name, body.path, body.allocated_gb, body.add_to_queue
        )
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


@router.post("/volumes/{name}/adopt", response_model=VolumeStatsResponse)
def adopt_volume(name: str, ctx: AppContext = Depends(get_ctx)):
    """Declare that the drive at the volume's path is that volume.

    Volumes are recognised by an identity marker in their root, so civex can
    tell an unplugged drive from a different drive mounted at the same path.
    Use this when a volume is reported as `wrong_drive` but the drive is in fact
    the right one (the marker was deleted, or the drive was re-formatted): it
    rewrites the marker. Nothing else on the drive is changed.
    """
    try:
        ctx.store_svc.adopt_volume(name)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    stats = ctx.store_svc.volume_stats()
    return next((v for v in stats if v["name"] == name), None)


@router.delete("/volumes/{name}", status_code=204)
def remove_volume(name: str, force: bool = False, ctx: AppContext = Depends(get_ctx)):
    # ValidationError (e.g. volume still has objects, force=False) isn't
    # caught here -- the registered CivexError handler maps it to 422,
    # same as every other ValidationError, rather than a locally-chosen 409
    # that would disagree with the global mapping for the same exception type.
    try:
        ctx.store_svc.remove_volume(name, force=force)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))


@router.put("/queue", response_model=list[str])
def set_queue(body: SetQueueRequest, ctx: AppContext = Depends(get_ctx)):
    try:
        ctx.store_svc.set_queue(body.queue)
    except (NotFoundError, ValidationError) as e:
        raise HTTPException(422, detail=str(e))
    return ctx.store_svc._config.store_config.volume_queue


@router.post("/gc", response_model=GCReportResponse)
def run_gc(body: GCRequest = GCRequest(), ctx: AppContext = Depends(get_ctx)):
    """Reclaim object-store blobs no longer referenced by any live record or
    workflow job. Defaults to a dry run (`apply=false`) that only reports
    what's collectible; pass `apply=true` to actually delete. Objects
    referenced only by audit history or job step logs are not protected --
    both retain FileRef snapshots indefinitely, so an old audit diff may
    reference a hash GC has since removed."""
    if body.rebuild_refs:
        ctx.gc_svc.rebuild_references()
    report = ctx.gc_svc.run(dry_run=not body.apply, grace_days=body.grace_days)
    return report.to_dict()


def _placement_response(
    ctx: AppContext, collection_id: str, volume: str, on_unavailable: str
) -> PlacementResponse:
    names = {str(d.id): d.name for d in ctx.dataset_svc.list_all(with_count=False)}
    return PlacementResponse(
        collection_id=collection_id,
        collection_name=names.get(collection_id),
        volume=volume,
        on_unavailable=on_unavailable,
    )


@router.get("/placement", response_model=list[PlacementResponse])
def list_placements(ctx: AppContext = Depends(get_ctx)):
    """Every collection that has a home volume.

    A placement only steers where a collection's *new* files are written. A file
    whose content already exists on any volume is reused where it lives and is
    never copied again.
    """
    names = {str(d.id): d.name for d in ctx.dataset_svc.list_all(with_count=False)}
    return [
        PlacementResponse(
            collection_id=cid,
            collection_name=names.get(cid),
            volume=place.volume,
            on_unavailable=place.on_unavailable,
        )
        for cid, place in ctx.store_svc.placements().items()
    ]


@router.put("/placement/{collection_id}", response_model=PlacementResponse)
def set_placement(
    collection_id: str, body: SetPlacementRequest, ctx: AppContext = Depends(get_ctx)
):
    """Make a volume the home of a collection's new files.

    The collection is identified by id, so renaming it changes nothing here. The
    home need not be in the general write queue.
    """
    try:
        ctx.dataset_svc.get_by_id(uuid.UUID(collection_id))
    except ValueError:
        raise HTTPException(422, detail=f"'{collection_id}' is not a collection id")
    place = ctx.store_svc.set_placement(collection_id, body.volume, body.on_unavailable)
    return _placement_response(
        ctx, str(uuid.UUID(collection_id)), place.volume, place.on_unavailable
    )


@router.delete("/placement/{collection_id}", status_code=204)
def clear_placement(collection_id: str, ctx: AppContext = Depends(get_ctx)):
    """Send a collection's new files back to the general write queue."""
    ctx.store_svc.clear_placement(collection_id)


@router.get("/browse", response_model=DirectoryListingResponse)
def browse_directory(
    path: str | None = None,
    show_hidden: bool = False,
    ctx: AppContext = Depends(get_ctx),
):
    """List the folders inside a directory on the machine running Civex, for
    choosing where a volume lives.

    Folders only, never files. Starts at the home folder when `path` is omitted,
    and also returns places to start from: the project, home and mounted drives
    (network drives marked as such). A location that doesn't answer in a few
    seconds is reported as not responding rather than waited on.
    """
    return asdict(ctx.store_svc.browse_directory(path, show_hidden=show_hidden))


@router.post("/browse/folder", response_model=CreateFolderResponse, status_code=201)
def create_folder(body: CreateFolderRequest, ctx: AppContext = Depends(get_ctx)):
    """Create a folder while choosing a volume location."""
    return CreateFolderResponse(
        path=ctx.store_svc.create_folder(body.parent, body.name)
    )


@router.get("/inspect", response_model=PathInspectionResponse)
def inspect_path(path: str, ctx: AppContext = Depends(get_ctx)):
    """What adding a folder as a volume would involve, before doing it.

    Reports whether it exists or would be created, whether Civex can write to
    it, free space, whether it is on a network drive or on the same disk as the
    project, and whether it is already a volume or carries another volume's
    identity. `problems` are reasons adding it would be refused; `warnings` are
    things worth knowing. Adding a volume enforces exactly these rules.
    """
    return asdict(ctx.store_svc.inspect_path(path))
