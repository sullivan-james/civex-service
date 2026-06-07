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
    return FileRefResponse(sha256=ref.sha256, filename=ref.filename, size=ref.size)


@router.get("/{sha256}")
def download_file(sha256: str, ctx: AppContext = Depends(get_ctx)):
    if not ctx.file_svc.exists(sha256):
        raise HTTPException(404, detail=f"Object {sha256} not found")
    data = ctx.file_svc.retrieve(sha256)
    return Response(content=data, media_type="application/octet-stream")
