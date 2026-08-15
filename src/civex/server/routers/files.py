from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response

from civex.context import AppContext
from civex.server.deps import get_ctx
from civex.server.models import FileRefResponse

router = APIRouter(prefix="/files", tags=["files"])


@router.post("", response_model=FileRefResponse, status_code=201)
async def upload_file(file: UploadFile, ctx: AppContext = Depends(get_ctx)):
    data = await file.read()
    ref = ctx.file_svc.store_bytes(data, file.filename or "upload")
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
        data = ctx.file_svc.retrieve(sha256)
    except Exception:
        raise HTTPException(
            404, detail=f"Object {sha256} not found locally or on remote"
        )
    headers = {}
    if filename:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return Response(
        content=data, media_type="application/octet-stream", headers=headers
    )
