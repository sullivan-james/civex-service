"""What an authority offers to the devices that follow it (CIVEX-305).

Everything here is for other civex installs, not for people: it is the only part
of the API a remote device may reach, and only on an instance that has been set to
serve (`[sync] serve = true`) and has issued the device a token
(`civex sync device add`). The rest of the API stays reachable from this machine
alone, however the server is exposed.

Every call carries the device's token (`Authorization: Bearer`), its id
(`X-Civex-Device`) and the protocol it speaks (`X-Civex-Protocol`). The protocol is
documented in `docs/guides/sync.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from civex.config import find_project_root, read_sync_flag
from civex.context import AppContext
from civex.domain.exceptions import ValidationError, VolumeUnavailableError
from civex.domain.sync import PROTOCOL_VERSION, SyncDeviceDTO, SyncEntry, SyncError
from civex.server.deps import get_ctx

router = APIRouter(prefix="/sync/v1", tags=["sync"])

_CHUNK = 1024 * 1024


class SyncHelloResponse(BaseModel):
    protocol_version: int = Field(description="The sync protocol this server speaks.")
    project_id: str = Field(description="The project's id, shared by every copy.")
    head_seq: int = Field(description="The latest number the authority has handed out.")
    empty: bool = Field(
        description="True when it holds none of the project's things yet (an empty "
        "authority can be filled from a project that has data)."
    )
    seeded_by: str | None = Field(
        default=None, description="The device that put the first data in, if any."
    )
    device_name: str = Field(description="What the token used is called here.")
    counts: dict[str, int] = Field(
        default_factory=dict,
        description="How many of each kind it holds, deleted ones included, so a "
        "device copying it can show how far along it is.",
    )


class SyncPushRequest(BaseModel):
    entries: list[dict[str, Any]] = Field(
        description="Changes made on the device, oldest first: history entries with "
        "their snapshots. Each is identified by its id, so sending one twice is "
        "harmless.",
        max_length=500,
    )


class SyncOpResponse(BaseModel):
    op_id: str
    status: str = Field(
        description="applied, merged, conflict, duplicate, rejected or deferred "
        "(deferred: not taken yet; send it again)."
    )
    message: str | None = None
    conflicts: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Values that did not go in as made: field, yours, theirs, kind.",
    )
    hub_seq: int | None = Field(
        default=None, description="Where the authority numbered it, once taken."
    )


class SyncPushResponse(BaseModel):
    results: list[SyncOpResponse] = Field(
        description="One answer per change, in order. Fewer than were sent means "
        "the rest were held back behind one that has to wait."
    )
    head_seq: int


class SyncFeedResponse(BaseModel):
    entries: list[dict[str, Any]] = Field(
        description="Changes past `after`, in the authority's order, each with its "
        "`hub_seq` and whether it was `superseded` by a later settled state."
    )
    head_seq: int
    more: bool = Field(description="There are more past this page.")


class SyncSnapshotResponse(BaseModel):
    kind: str
    items: list[dict[str, Any]] = Field(
        description="Things of this kind as they are now, in the shape a history "
        "entry stores them."
    )
    more: bool
    head_seq: int = Field(
        description="Taken before reading: what changes meanwhile is in the feed past it."
    )
    next: str | None = Field(
        default=None,
        description="Pass as `after` for the next page; null on the last page.",
    )


class SyncFilesRequest(BaseModel):
    sha256: list[str] = Field(
        description="Content hashes of files the device holds.", max_length=5000
    )


class SyncFilesResponse(BaseModel):
    missing: list[str] = Field(description="Those the authority does not have yet.")


@dataclass
class Peer:
    ctx: AppContext
    device: SyncDeviceDTO
    device_id: str | None


def peer(
    request: Request,
    # scope="function": the work is committed before the answer is sent. With
    # the default, the commit runs after, and a commit that then fails (the
    # database busy, a full disk) would still have told the device "done": it
    # would never send those changes again, and they would be lost.
    ctx: AppContext = Depends(get_ctx, scope="function"),
) -> Peer:
    """Who is calling: a device with a valid token, on a server set to serve."""
    root = find_project_root()
    if root is None or not read_sync_flag(root / "_civex", "serve"):
        # Indistinguishable from there being nothing here, so a server that
        # is not an authority reveals nothing.
        raise HTTPException(404, detail="Not found")
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer ") or not auth[7:].strip():
        raise HTTPException(401, detail="A device token is required")
    device_id = request.headers.get("x-civex-device")
    try:
        device = ctx.authority_svc.authenticate(auth[7:].strip(), device_id)
    except SyncError as e:
        raise HTTPException(e.status, detail=str(e))
    claimed = request.headers.get("x-civex-protocol", "")
    if claimed != str(PROTOCOL_VERSION):
        raise HTTPException(
            426,
            detail=f"This server speaks sync protocol {PROTOCOL_VERSION}; "
            f"the device sent {claimed or 'none'}. Update the older one.",
        )
    return Peer(ctx, device, device_id)


@router.get("/hello", response_model=SyncHelloResponse)
def hello(who: Peer = Depends(peer)):
    """Say who this server is: its project, its latest number, whether it holds
    data. A device asks first, to decide whether to join, fill it, or stop."""
    return SyncHelloResponse(**who.ctx.authority_svc.hello(who.device).to_dict())


@router.post("/push", response_model=SyncPushResponse)
def push(body: SyncPushRequest, who: Peer = Depends(peer)):
    """Settle the changes a device made. Each is merged with what the authority
    holds, numbered, and answered; the answer is remembered, so a repeat (the
    device never heard) is answered the same way and nothing is done twice."""
    try:
        entries = [SyncEntry.from_dict(e) for e in body.entries]
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(422, detail=f"A change is malformed: {e}")
    try:
        result = who.ctx.authority_svc.push(who.device, who.device_id, entries)
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    return SyncPushResponse(**result.to_dict())


@router.get("/feed", response_model=SyncFeedResponse)
def feed(
    after: int = Query(default=0, ge=0, description="The last number the device has."),
    limit: int = Query(default=200, ge=1, le=500),
    who: Peer = Depends(peer),
):
    """Everyone's changes past `after`, in the order the authority numbered them."""
    return SyncFeedResponse(**who.ctx.authority_svc.feed(after, limit).to_dict())


@router.get("/snapshot/{kind}", response_model=SyncSnapshotResponse)
def snapshot(
    kind: str,
    after: str | None = Query(
        default=None, description="The previous page's `next`; omit for the first."
    ),
    limit: int = Query(default=200, ge=1, le=500),
    who: Peer = Depends(peer),
):
    """One kind of thing as it is now, a page at a time, for a device joining
    the project: schema, field, dataset, view, record (in that order)."""
    try:
        return SyncSnapshotResponse(
            **who.ctx.authority_svc.snapshot(kind, after, limit).to_dict()
        )
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))


@router.post("/files/missing", response_model=SyncFilesResponse)
def files_missing(body: SyncFilesRequest, who: Peer = Depends(peer)):
    """Which of these files the authority does not have: what a device uploads
    before the changes that cite them."""
    return SyncFilesResponse(missing=who.ctx.authority_svc.missing_files(body.sha256))


@router.put("/files/{sha256}", status_code=204)
async def upload_file(sha256: str, request: Request, who: Peer = Depends(peer)):
    """Store a file under its content hash. The bytes are hashed as they arrive;
    ones that don't match `sha256` are refused."""
    if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
        raise HTTPException(422, detail="Not a sha256")
    size = request.headers.get("content-length")
    try:
        ref = await who.ctx.file_svc.store_stream(
            request.stream(), sha256, int(size) if size and size.isdigit() else None
        )
    except VolumeUnavailableError as e:
        raise HTTPException(507, detail=str(e))
    if ref.sha256 != sha256:
        raise HTTPException(422, detail="The content does not match that hash")


@router.get("/files/{sha256}")
def download_file(sha256: str, who: Peer = Depends(peer)):
    """The bytes of a file the authority holds, for a device that was sent only
    the record that cites it."""
    try:
        path = who.ctx.file_svc.local_path(sha256)
    except (FileNotFoundError, VolumeUnavailableError):
        raise HTTPException(404, detail="That file is not here")
    return FileResponse(path, media_type="application/octet-stream")


__all__ = ["router"]
