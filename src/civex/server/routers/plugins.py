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
    """Save a plugin from JSON source (used by the AI confirmation UI)."""
    try:
        ctx.plugin_svc.save(body.name, body.code)
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    return {"filename": f"{body.name}.py"}


class ContainerPluginInfo(BaseModel):
    name: str
    files: list[str]


class ContainerPluginDetail(BaseModel):
    name: str
    files: dict[str, str]


class ContainerFileSaveRequest(BaseModel):
    path: str
    content: str


class BuildResult(BaseModel):
    success: bool
    log: str


@router.get("/containers", response_model=list[ContainerPluginInfo])
def list_container_plugins(ctx: AppContext = Depends(get_ctx)):
    """List Tier 2 (container) plugin directories under _civex/plugins/."""
    return [
        ContainerPluginInfo(**p)
        for p in ctx.container_plugin_svc.list_container_plugins()
    ]


@router.get("/containers/{name}", response_model=ContainerPluginDetail)
def get_container_plugin(name: str, ctx: AppContext = Depends(get_ctx)):
    """Full file tree (Dockerfile + source) of a container plugin."""
    try:
        files = ctx.container_plugin_svc.get_files(name)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    return ContainerPluginDetail(name=name, files=files)


@router.put("/containers/{name}", response_model=BuildResult)
def save_container_plugin_file(
    name: str, body: ContainerFileSaveRequest, ctx: AppContext = Depends(get_ctx)
):
    """Save one file in the plugin's directory, then rebuild its Docker
    image immediately -- the multi-file equivalent of Tier 1's save-triggers-
    describe round-trip."""
    try:
        ctx.container_plugin_svc.save_file(name, body.path, body.content)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(400, detail=str(e))
    return BuildResult(**ctx.container_plugin_svc.rebuild(name))
