from __future__ import annotations

from fastapi import APIRouter, HTTPException

from civex.config import load_config, save_config
from civex import launcher
from civex.domain.exceptions import ConfigError
from civex.server.models import (
    MapSettingsResponse,
    ShortcutResponse,
    UpdateMapSettingsRequest,
    RetentionSettingsResponse,
    UISettingsResponse,
    UpdateRetentionSettingsRequest,
    UpdateUISettingsRequest,
)

router = APIRouter(prefix="/settings", tags=["settings"])


def _load_config():
    try:
        return load_config()
    except ConfigError as e:
        raise HTTPException(500, detail=str(e))


@router.get("/ui", response_model=UISettingsResponse)
def get_ui_settings():
    """Return this project's UI preferences."""
    config = _load_config()
    return UISettingsResponse(show_advanced=config.ui.show_advanced)


@router.patch("/ui", response_model=UISettingsResponse)
def update_ui_settings(body: UpdateUISettingsRequest):
    """Update this project's UI preferences."""
    config = _load_config()
    config.ui.show_advanced = body.show_advanced
    save_config(config)
    return UISettingsResponse(show_advanced=config.ui.show_advanced)


def _shortcut_state(root) -> ShortcutResponse:
    try:
        path = launcher.shortcut_path(root)
    except ConfigError:
        return ShortcutResponse(exists=False, path=None)
    return ShortcutResponse(exists=path.exists(), path=str(path))


@router.get("/shortcut", response_model=ShortcutResponse)
def get_shortcut():
    """Whether this project has a Desktop shortcut that starts civex."""
    return _shortcut_state(_load_config().project_root)


@router.post("/shortcut", response_model=ShortcutResponse)
def create_shortcut():
    """Put a Desktop shortcut that starts civex for this project and opens it
    in the browser. Runs on the machine civex runs on."""
    root = _load_config().project_root
    try:
        launcher.create_shortcut(root)
    except ConfigError as e:
        raise HTTPException(409, detail=str(e))
    except OSError as e:
        raise HTTPException(500, detail=f"Could not write the shortcut: {e}")
    return _shortcut_state(root)


@router.get("/map", response_model=MapSettingsResponse)
def get_map_settings():
    """Where the location editor gets street-level map tiles, if anywhere."""
    config = _load_config()
    return MapSettingsResponse(
        tile_url=config.map.tile_url, attribution=config.map.attribution
    )


@router.patch("/map", response_model=MapSettingsResponse)
def update_map_settings(body: UpdateMapSettingsRequest):
    """Set (or clear, with null) the map tile URL. It must be an http(s) XYZ
    URL containing {z}, {x} and {y}. The provider's terms of use apply."""
    url = (body.tile_url or "").strip() or None
    if url is not None:
        if not url.startswith(("http://", "https://")) or not all(
            token in url for token in ("{z}", "{x}", "{y}")
        ):
            raise HTTPException(
                422,
                detail="Tile URL must start with http:// or https:// and "
                "contain {z}, {x} and {y}, e.g. https://tile.example.org/{z}/{x}/{y}.png",
            )
    config = _load_config()
    config.map.tile_url = url
    config.map.attribution = (body.attribution or "").strip() or None if url else None
    save_config(config)
    return MapSettingsResponse(
        tile_url=config.map.tile_url, attribution=config.map.attribution
    )


@router.get("/retention", response_model=RetentionSettingsResponse)
def get_retention_settings():
    """Return this project's soft-delete retention policy."""
    config = _load_config()
    return RetentionSettingsResponse(purge_after_days=config.retention.purge_after_days)


@router.patch("/retention", response_model=RetentionSettingsResponse)
def update_retention_settings(body: UpdateRetentionSettingsRequest):
    """Update how many days a soft-deleted item stays in Recently Deleted
    before it's eligible for permanent deletion."""
    config = _load_config()
    config.retention.purge_after_days = body.purge_after_days
    save_config(config)
    return RetentionSettingsResponse(purge_after_days=config.retention.purge_after_days)
