"""What an authority offers to the devices that follow it (CIVEX-305).

Everything here is for other civex installs, not for people: it is the only part
of the API a remote device may reach, and only on an instance that has been set to
serve (`[sync] serve = true`). The rest of the API stays reachable from this
machine alone, however the server is exposed.

A device joins once with an invite (`civex sync device invite`) and its public
key (`POST /join`), then signs in with that key (`POST /session`) for a
short-lived token, which every other call carries (`Authorization: Bearer`).
Every call says the protocol it speaks (`X-Civex-Protocol`). The protocol is
documented in `docs/guides/sync.md`.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from civex.config import find_project_root, read_sync_flag
from civex.context import AppContext
from civex.domain.exceptions import (
    NotAllowedError,
    NotFoundError,
    ValidationError,
    VolumeUnavailableError,
)
from civex.domain.library import MAX_BUNDLE, MAX_BYTES, LibraryItemDTO
from civex.domain.sync import (
    PROTOCOL_MAX,
    PROTOCOL_MIN,
    Principal,
    SyncEntry,
    SyncError,
    agree,
    protocol_mismatch,
    protocol_range,
)
from civex.server.deps import get_ctx

router = APIRouter(prefix="/sync/v1", tags=["sync"])

_CHUNK = 1024 * 1024


class SyncHelloResponse(BaseModel):
    protocol_version: int = Field(
        description="The sync protocol this server and the calling device agreed on."
    )
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
    feed_floor: int = Field(
        default=0,
        description="The highest number the feed no longer holds (history pruned "
        "here). A device whose cursor is below it copies the project again.",
    )
    counts: dict[str, int] = Field(
        default_factory=dict,
        description="How many of each kind it holds, deleted ones included, so a "
        "device copying it can show how far along it is.",
    )
    protocol_min: int = Field(description="The oldest sync protocol it speaks.")
    protocol_max: int = Field(description="The newest sync protocol it speaks.")
    server_version: str | None = Field(
        default=None, description="The civex release it runs."
    )
    capabilities: list[str] = Field(
        default_factory=list,
        description="Optional features it has, by name. Adding one is not a "
        "protocol change.",
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


class SyncJoinRequest(BaseModel):
    invite: str = Field(description="The invite code the authority's admin gave.")
    device_id: str = Field(description="This device's id (a UUID).")
    public_key: str = Field(
        description="This device's Ed25519 public key, base64 of its 32 bytes."
    )


class SyncJoinResponse(BaseModel):
    project_id: str = Field(description="The project's id, shared by every copy.")
    authority_key: str = Field(
        description="The authority's public key: it signs its answers to sign-ins."
    )
    device_name: str = Field(description="What the device was invited as.")


class SyncSessionRequest(BaseModel):
    device_id: str = Field(description="The device signing in.")
    at: int = Field(description="Now, in unix seconds, as the device's clock says.")
    signature: str = Field(
        description="The device's signature over the session request (the "
        "authority's key, the device id and `at`)."
    )


class SyncSessionResponse(BaseModel):
    token: str = Field(description="Send as `Authorization: Bearer` until it expires.")
    expires_at: int = Field(description="When the token stops working, unix seconds.")
    signature: str = Field(
        description="The authority's signature over its answer to this request."
    )


class _Attempts:
    """Failed joins and sign-ins, per caller: past `LIMIT` a minute, it waits.
    An invite is far too long to guess; this keeps the log quiet. In memory:
    one process serves an authority."""

    LIMIT = 10
    WINDOW = 60.0

    def __init__(self) -> None:
        self._failed: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, host: str) -> deque[float]:
        times = self._failed.setdefault(host, deque())
        while times and times[0] < time.monotonic() - self.WINDOW:
            times.popleft()
        return times

    def check(self, request: Request) -> None:
        host = request.client.host if request.client else ""
        with self._lock:
            if len(self._recent(host)) >= self.LIMIT:
                raise HTTPException(
                    429, detail="Too many failed attempts: wait a minute"
                )
            if not self._failed[host]:
                del self._failed[host]

    def failed(self, request: Request) -> None:
        host = request.client.host if request.client else ""
        with self._lock:
            self._recent(host).append(time.monotonic())


_attempts = _Attempts()


def _serving(request: Request) -> int:
    """The protocol agreed with the caller, on a server set to serve."""
    root = find_project_root()
    if root is None or not read_sync_flag(root / "_civex", "serve"):
        # Indistinguishable from there being nothing here, so a server that
        # is not an authority reveals nothing.
        raise HTTPException(404, detail="Not found")
    theirs = protocol_range(request.headers.get("x-civex-protocol"))
    protocol = agree(theirs) if theirs else None
    if protocol is None:
        # Structured, so the device can say which side to update in its own words.
        raise HTTPException(
            426,
            detail={
                "message": protocol_mismatch(theirs, "the device", "this server"),
                "protocol_min": PROTOCOL_MIN,
                "protocol_max": PROTOCOL_MAX,
            },
        )
    return protocol


@dataclass
class Peer:
    ctx: AppContext
    who: Principal
    protocol: int  # the version agreed for this request


def peer(
    request: Request,
    # scope="function": the work is committed before the answer is sent. With
    # the default, the commit runs after, and a commit that then fails (the
    # database busy, a full disk) would still have told the device "done": it
    # would never send those changes again, and they would be lost.
    ctx: AppContext = Depends(get_ctx, scope="function"),
) -> Peer:
    """Who is calling: a signed-in device, on a server set to serve."""
    protocol = _serving(request)
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer ") or not auth[7:].strip():
        raise HTTPException(401, detail="Sign in first")
    try:
        who = ctx.authority_svc.authenticate(auth[7:].strip())
    except SyncError as e:
        raise HTTPException(e.status, detail=str(e))
    return Peer(ctx, who, protocol)


def _once(request: Request, attempt):
    """A join or sign-in: no token yet, so failures are counted."""
    _attempts.check(request)
    try:
        return attempt()
    except SyncError as e:
        _attempts.failed(request)
        raise HTTPException(e.status, detail=str(e))


@router.post("/join", response_model=SyncJoinResponse)
def join(
    body: SyncJoinRequest,
    request: Request,
    # A dependency, so a server that isn't serving says nothing more than 404,
    # whatever the body.
    _protocol: int = Depends(_serving),
    ctx: AppContext = Depends(get_ctx, scope="function"),
):
    """Join with an invite: the device's public key is kept, the invite is
    used up, and the answer carries the authority's key."""
    joined = _once(
        request,
        lambda: ctx.device_keys.join(body.invite, body.device_id, body.public_key),
    )
    return SyncJoinResponse(**joined.to_dict())


@router.post("/session", response_model=SyncSessionResponse)
def session(
    body: SyncSessionRequest,
    request: Request,
    # A dependency, so a server that isn't serving says nothing more than 404,
    # whatever the body.
    _protocol: int = Depends(_serving),
    ctx: AppContext = Depends(get_ctx, scope="function"),
):
    """Sign in: a request signed with the device's key, for a token that
    expires in minutes."""
    grant = _once(
        request,
        lambda: ctx.device_keys.start_session(body.device_id, body.at, body.signature),
    )
    return SyncSessionResponse(**grant.to_dict())


@router.get("/hello", response_model=SyncHelloResponse)
def hello(call: Peer = Depends(peer)):
    """Say who this server is: its project, its latest number, whether it holds
    data. A device asks first, to decide whether to join, fill it, or stop."""
    hello = call.ctx.authority_svc.hello(call.who, call.protocol)
    return SyncHelloResponse(**hello.to_dict())


@router.post("/push", response_model=SyncPushResponse)
def push(body: SyncPushRequest, call: Peer = Depends(peer)):
    """Settle the changes a device made. Each is merged with what the authority
    holds, numbered, and answered; the answer is remembered, so a repeat (the
    device never heard) is answered the same way and nothing is done twice."""
    try:
        entries = [SyncEntry.from_dict(e) for e in body.entries]
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(422, detail=f"A change is malformed: {e}")
    try:
        result = call.ctx.authority_svc.push(call.who, entries)
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    return SyncPushResponse(**result.to_dict())


@router.get("/feed", response_model=SyncFeedResponse)
def feed(
    after: int = Query(default=0, ge=0, description="The last number the device has."),
    limit: int = Query(default=200, ge=1, le=500),
    call: Peer = Depends(peer),
):
    """Everyone's changes past `after`, in the order the authority numbered them."""
    return SyncFeedResponse(**call.ctx.authority_svc.feed(after, limit).to_dict())


@router.get("/snapshot/{kind}", response_model=SyncSnapshotResponse)
def snapshot(
    kind: str,
    after: str | None = Query(
        default=None, description="The previous page's `next`; omit for the first."
    ),
    limit: int = Query(default=200, ge=1, le=500),
    call: Peer = Depends(peer),
):
    """One kind of thing as it is now, a page at a time, for a device joining
    the project: schema, field, dataset, view, record (in that order)."""
    try:
        return SyncSnapshotResponse(
            **call.ctx.authority_svc.snapshot(kind, after, limit).to_dict()
        )
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))


@router.post("/files/missing", response_model=SyncFilesResponse)
def files_missing(body: SyncFilesRequest, call: Peer = Depends(peer)):
    """Which of these files the authority does not have: what a device uploads
    before the changes that cite them."""
    return SyncFilesResponse(missing=call.ctx.authority_svc.missing_files(body.sha256))


@router.put("/files/{sha256}", status_code=204)
async def upload_file(sha256: str, request: Request, call: Peer = Depends(peer)):
    """Store a file under its content hash. The bytes are hashed as they arrive;
    ones that don't match `sha256` are refused."""
    if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
        raise HTTPException(422, detail="Not a sha256")
    size = request.headers.get("content-length")
    try:
        ref = await call.ctx.file_svc.store_stream(
            request.stream(), sha256, int(size) if size and size.isdigit() else None
        )
    except VolumeUnavailableError as e:
        raise HTTPException(507, detail=str(e))
    if ref.sha256 != sha256:
        raise HTTPException(422, detail="The content does not match that hash")


@router.get("/files/{sha256}")
def download_file(sha256: str, call: Peer = Depends(peer)):
    """The bytes of a file the authority holds, for a device that was sent only
    the record that cites it."""
    try:
        path = call.ctx.file_svc.local_path(sha256)
    except (FileNotFoundError, VolumeUnavailableError):
        raise HTTPException(404, detail="That file is not here")
    return FileResponse(path, media_type="application/octet-stream")


# -- the library: workflows and plugins shared through this authority ----------
# Kept as text and never loaded here (`domain/library.py`): a device publishes,
# a person on another computer installs. Reading needs only being a device;
# publishing needs the admin's leave and the `[sync] library` setting.


class LibraryItemBody(BaseModel):
    kind: str = Field(description="workflow or plugin.")
    name: str = Field(description="The file's name without its extension.")
    sha256: str = Field(description="The hash of `content`, as UTF-8.")
    size: int = Field(default=0, description="Its size in bytes.")
    content: str = Field(description="The file's text.", max_length=MAX_BYTES)
    provides: str | None = Field(
        default=None, description="A plugin: the plugin id it registers as."
    )
    contract: dict[str, Any] | None = Field(
        default=None,
        description="A plugin: its contract (inputs, outputs, config schema) as "
        "the publisher's computer described it.",
    )


class LibraryPublishRequest(BaseModel):
    items: list[LibraryItemBody] = Field(
        description="A workflow and the plugins it uses, or a plugin. Taken whole "
        "or not at all; new text becomes the next version.",
        max_length=MAX_BUNDLE,
    )


class LibraryListResponse(BaseModel):
    items: list[dict[str, Any]] = Field(
        description="The newest version of each item, without its text: kind, "
        "name, sha256, size, version, title, description, provides, needs, "
        "triggers, pins, contract, published_by, published_at, and its history "
        "(every version)."
    )


class LibraryPublishResponse(LibraryListResponse):
    warnings: list[str] = Field(
        default_factory=list,
        description="What to know: shared workflows still on an older version of "
        "a plugin that the new version would break.",
    )


def _library_call(call):
    try:
        return call()
    except NotAllowedError as e:
        raise HTTPException(403, detail=str(e))
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))


@router.get("/library", response_model=LibraryListResponse)
def library(call: Peer = Depends(peer)):
    """The workflows and plugins shared through this server: the newest version
    of each, with its history, without its text."""
    items = call.ctx.library_svc.listing()
    return LibraryListResponse(items=[i.to_dict(with_content=False) for i in items])


@router.get("/library/{kind}/{name}")
def library_item(
    kind: str,
    name: str,
    version: int | None = Query(default=None, description="Omit for the newest."),
    call: Peer = Depends(peer),
) -> dict[str, Any]:
    """One version of a shared workflow or plugin, with its text."""
    return _library_call(
        lambda: call.ctx.library_svc.item(kind, name, version)
    ).to_dict()


@router.post("/library", response_model=LibraryPublishResponse)
def publish(body: LibraryPublishRequest, call: Peer = Depends(peer)):
    """Publish to the library. Refused (403) unless the admin allowed this
    device, and for plugins unless the server takes them; checked without being
    run, and taken whole or not at all. A workflow is pinned to the plugin
    versions it is published with."""
    items = [
        LibraryItemDTO(
            kind=i.kind,
            name=i.name,
            sha256=i.sha256,
            size=i.size,
            provides=i.provides,
            content=i.content,
            contract=i.contract,
        )
        for i in body.items
    ]
    result = _library_call(lambda: call.ctx.library_svc.accept(call.who, items))
    return LibraryPublishResponse(**result.to_dict())


@router.delete("/library/{kind}/{name}", status_code=204)
def unpublish(
    kind: str,
    name: str,
    version: int | None = Query(
        default=None, description="One version; omit to remove every version."
    ),
    force: bool = Query(
        default=False,
        description="Remove a plugin version even if shared workflows are pinned to it.",
    ),
    call: Peer = Depends(peer),
):
    """Take something out of the library. Copies already installed stay."""
    _library_call(
        lambda: call.ctx.library_svc.withdraw(call.who, kind, name, version, force)
    )


__all__ = ["router"]
