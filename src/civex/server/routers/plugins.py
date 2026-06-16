from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

router = APIRouter(prefix="/plugins", tags=["plugins"])


class PluginInfo(BaseModel):
    id: str
    description: str
    builtin: bool


class UploadResult(BaseModel):
    filename: str
    plugin_id: str


@router.get("", response_model=list[PluginInfo])
def list_plugins():
    """List all registered plugins (built-ins + user plugins from .civex/plugins/)."""
    from civex.plugins.registry import all_plugins, discover_user_plugins
    from civex.config import load_config, ConfigError

    try:
        config = load_config()
        discover_user_plugins(config.civex_dir / "plugins")
    except ConfigError:
        pass

    builtin_prefix = "civex."
    return [
        PluginInfo(
            id=plugin_id,
            description=getattr(cls, "description", "") or "",
            builtin=plugin_id.startswith(builtin_prefix),
        )
        for plugin_id, cls in sorted(all_plugins().items())
    ]


@router.post("/upload", response_model=UploadResult)
async def upload_plugin(file: UploadFile = File(...)):
    """Upload a .py plugin file into .civex/plugins/ and register it immediately."""
    if not (file.filename or "").endswith(".py"):
        raise HTTPException(status_code=400, detail="File must be a .py Python file")

    filename = file.filename or "plugin.py"
    # Prevent path traversal
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")

    from civex.config import load_config, ConfigError
    try:
        config = load_config()
    except ConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))

    plugins_dir = config.civex_dir / "plugins"
    plugins_dir.mkdir(exist_ok=True)

    content = await file.read()
    dest = plugins_dir / filename
    dest.write_bytes(content)

    # Register immediately in the running process so it's available without restart.
    from civex.plugins.registry import discover_user_plugins, all_plugins
    discover_user_plugins(plugins_dir)

    # Find the plugin ID that was just registered (the one from this file's stem).
    stem = filename[:-3]
    plugin_id = next(
        (pid for pid in all_plugins() if pid == stem or all_plugins()[pid].__module__ == stem),
        stem,
    )

    return UploadResult(filename=filename, plugin_id=plugin_id)
