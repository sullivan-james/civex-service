from __future__ import annotations

from fastapi import APIRouter, HTTPException

from civex.config import load_config, save_config
from civex.domain.exceptions import ConfigError
from civex.server.models import UISettingsResponse, UpdateUISettingsRequest

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
