from __future__ import annotations

from fastapi import APIRouter, HTTPException

from civex.config import load_config, save_config
from civex.domain.exceptions import ConfigError
from civex.server.models import (
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
