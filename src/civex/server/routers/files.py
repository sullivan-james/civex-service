from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from civex.context import AppContext
from civex.domain.exceptions import AllVolumesFull, VolumeUnavailableError
from civex.server.deps import get_ctx
from civex.server.models import FileInfoResponse, FileRefResponse

router = APIRouter(prefix="/files", tags=["files"])


_UPLOAD_CHUNK = 1024 * 1024

_COLLECTION_PARAM = Query(
    default=None,
    description=(
        "Id of the collection the file is for. It only steers which volume receives "
        "*new* content (the collection's home volume, if it has one); a file whose "
        "content is already stored is reused where it lives, never copied again."
    ),
)


async def _read_chunks(file: UploadFile) -> AsyncIterator[bytes]:
    while chunk := await file.read(_UPLOAD_CHUNK):
        yield chunk


@router.post("", response_model=FileRefResponse, status_code=201)
async def upload_file(
    file: UploadFile,
    collection: str | None = _COLLECTION_PARAM,
    ctx: AppContext = Depends(get_ctx),
):
    """Upload a multipart file. Starlette has already spooled the body to a
    temp file by the time this runs; it is hashed and copied into the object
    store 1 MiB at a time, so memory use is independent of file size."""
    try:
        ref = await ctx.file_svc.store_stream(
            _read_chunks(file), file.filename or "upload", file.size, collection
        )
    except (AllVolumesFull, VolumeUnavailableError) as e:
        raise HTTPException(507, detail=str(e))
    return FileRefResponse(
        sha256=ref.sha256, filename=ref.filename, size=ref.size, volume=ref.volume
    )


@router.put("/stream", response_model=FileRefResponse, status_code=201)
async def upload_file_stream(
    request: Request,
    filename: str = "upload",
    collection: str | None = _COLLECTION_PARAM,
    ctx: AppContext = Depends(get_ctx),
):
    """Upload a raw (non-multipart) request body, streamed straight to the
    object store instead of buffered in memory first. A multipart body sent
    via POST / has to be fully spooled to a temp file by Starlette's form
    parser before this code ever runs -- reading it back into memory here
    would mean the bytes touch disk twice for no reason. Sending the raw
    body instead lets us read it directly off the wire in chunks, and
    (unlike multipart, where per-part sizes aren't available upfront) a raw
    body carries an accurate Content-Length the object store can use to
    pick a volume with enough room before writing a single byte.
    """
    size_hint = None
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            size_hint = int(content_length)
        except ValueError:
            size_hint = None
    try:
        ref = await ctx.file_svc.store_stream(
            request.stream(), filename, size_hint, collection
        )
    except (AllVolumesFull, VolumeUnavailableError) as e:
        raise HTTPException(507, detail=str(e))
    return FileRefResponse(
        sha256=ref.sha256, filename=ref.filename, size=ref.size, volume=ref.volume
    )


@router.get("/{sha256}")
def download_file(sha256: str, filename: str = "", ctx: AppContext = Depends(get_ctx)):
    """Fetch raw file bytes by content hash.

    This endpoint is content-addressed only — it has no notion of which
    record/field a download is "for", so it can't apply a `filename_template`
    resolution itself. Callers that want a resolved `Content-Disposition`
    filename (e.g. scripted access) should read `resolved_filename` off the
    record via the records API and pass it as `?filename=`; the record-UI
    download link does this implicitly via the `download` attribute.
    """
    try:
        path = ctx.file_svc.local_path(sha256)
    except FileNotFoundError:
        # "Not there" and "on a drive that isn't plugged in" are different
        # problems with different fixes: say which.
        offline = ctx.file_svc.offline_location(sha256)
        if offline is not None:
            volume, status = offline
            raise HTTPException(
                503,
                detail=(
                    f"This file is on volume '{volume}', which isn't available right "
                    f"now ({status.reason}). {status.fix}"
                ),
            )
        raise HTTPException(
            404, detail=f"Object {sha256} not found locally or on remote"
        )
    # Streamed from disk in chunks (with Range/ETag support) rather than read
    # into memory. `filename` sets Content-Disposition: attachment, properly
    # quoted/encoded; without it no disposition header is sent.
    return FileResponse(
        path, media_type="application/octet-stream", filename=filename or None
    )


@router.get("/{sha256}/info", response_model=FileInfoResponse)
def file_info(sha256: str, ctx: AppContext = Depends(get_ctx)):
    """Where a file's content is stored and what uses it.

    Lists every place the content is, or is recorded to be (each volume, its
    state, and the object's path on it, including a volume that is unplugged
    right now), the size, and the records, collections and workflow runs that
    use it. A file used by several records is stored once, so this is how to
    see everything that shares it.
    """
    return asdict(ctx.file_info_svc.info(sha256))
