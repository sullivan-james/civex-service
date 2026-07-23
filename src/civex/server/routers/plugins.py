from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from civex.context import AppContext
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.server.deps import get_ctx

router = APIRouter(prefix="/plugins", tags=["plugins"])


class PluginInfo(BaseModel):
    id: str
    description: str
    builtin: bool
    filename: str | None = None


class UploadResult(BaseModel):
    filename: str
    plugin_id: str


@router.get("", response_model=list[PluginInfo])
def list_plugins(ctx: AppContext = Depends(get_ctx)):
    """List all registered plugins (built-ins + user plugins from _civex/plugins/)."""
    return [PluginInfo(**p) for p in ctx.plugin_svc.list_registered()]


@router.post("/upload", response_model=UploadResult)
async def upload_plugin(
    file: UploadFile = File(...), ctx: AppContext = Depends(get_ctx)
):
    """Upload a .py plugin file into _civex/plugins/ and register it immediately."""
    if not (file.filename or "").endswith(".py"):
        raise HTTPException(status_code=400, detail="File must be a .py Python file")

    filename = file.filename or "plugin.py"
    # Prevent path traversal
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")

    content = await file.read()
    plugin_id = ctx.plugin_svc.save_uploaded(filename, content)
    return UploadResult(filename=filename, plugin_id=plugin_id)


class PluginSaveRequest(BaseModel):
    name: str
    code: str


@router.post("", status_code=201)
def save_plugin_json(body: PluginSaveRequest, ctx: AppContext = Depends(get_ctx)):
    """Save a plugin from JSON source (used by the AI confirmation UI and the
    Tier 1 plugin editor). Writes the file, then re-registers it -- which
    describes it in the same request, so a broken contract surfaces
    immediately as an error response rather than only on next use."""
    try:
        ctx.plugin_svc.save(body.name, body.code)
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    return {"filename": f"{body.name}.py"}


class PluginSource(BaseModel):
    filename: str
    code: str


@router.get("/{filename}/source", response_model=PluginSource)
def get_plugin_source(filename: str, ctx: AppContext = Depends(get_ctx)):
    """Read a single user plugin's raw source, e.g. to populate the editor."""
    if not filename.endswith(".py") or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    try:
        code = ctx.plugin_svc.get_source(filename)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    return PluginSource(filename=filename, code=code)
