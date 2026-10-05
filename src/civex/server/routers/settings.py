from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from civex.config import load_config, save_config
from civex import launcher
from civex.identity import local_actor
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


class IdentityResponse(BaseModel):
    name: str | None = Field(description="What changes made here are recorded as.")
    chosen: str | None = Field(
        description="The name chosen for this project, or null when none is."
    )
    default: str | None = Field(
        description="What is used when none is chosen: the operating-system user."
    )


class UpdateIdentityRequest(BaseModel):
    name: str | None = Field(
        default=None,
        max_length=100,
        description="The name to record on changes made in this project; blank or null "
        "goes back to the default (the operating-system user). Saved in the "
        "project's config.toml.",
    )


def _identity(config) -> IdentityResponse:  # noqa: ANN001 - Config
    return IdentityResponse(
        name=local_actor(config.identity.name),
        chosen=config.identity.name,
        default=local_actor(),
    )


@router.get("/identity", response_model=IdentityResponse)
def get_identity():
    """Who changes made in this project are recorded as."""
    return _identity(_load_config())


@router.patch("/identity", response_model=IdentityResponse)
def update_identity(body: UpdateIdentityRequest):
    """Choose the name recorded on changes made in this project, like git's
    `user.name`: it is saved in this project's config.toml."""
    config = _load_config()
    config.identity.name = (body.name or "").strip()[:100] or None
    save_config(config)
    return _identity(config)


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


def _retention_response(config) -> RetentionSettingsResponse:
    r = config.retention
    return RetentionSettingsResponse(
        purge_after_days=r.purge_after_days,
        auto_purge_deleted=r.auto_purge_deleted,
        audit_days=r.audit_days,
        run_days=r.run_days,
    )


@router.get("/retention", response_model=RetentionSettingsResponse)
def get_retention_settings():
    """Return how long this project keeps deleted items, change history and
    workflow runs. Nothing is removed by itself: a clean-up applies these."""
    return _retention_response(_load_config())


@router.patch("/retention", response_model=RetentionSettingsResponse)
def update_retention_settings(body: UpdateRetentionSettingsRequest):
    """Change the retention settings. Only the fields sent change; a null
    `audit_days` or `run_days` means keep that kind forever."""
    config = _load_config()
    sent = body.model_fields_set
    r = config.retention
    if "purge_after_days" in sent and body.purge_after_days is not None:
        r.purge_after_days = body.purge_after_days
    if "auto_purge_deleted" in sent and body.auto_purge_deleted is not None:
        r.auto_purge_deleted = body.auto_purge_deleted
    if "audit_days" in sent:
        r.audit_days = body.audit_days
    if "run_days" in sent:
        r.run_days = body.run_days
    save_config(config)
    return _retention_response(config)
