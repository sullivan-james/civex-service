from __future__ import annotations

from fastapi import APIRouter, HTTPException

from civex.config import load_config
from civex.domain.exceptions import ConfigError, ValidationError
from civex.server.models import (
    DbStatusResponse,
    DockerStatusResponse,
    MigrationStatusResponse,
    SetDbUrlRequest,
)
from civex.services import db_service

router = APIRouter(prefix="/db", tags=["db"])

# Deliberately does not use Depends(get_ctx): these routes must keep working
# even when the configured database itself is unreachable or misconfigured
# (that's the whole point of exposing status/migrate/set-url/docker
# setup+teardown as their own surface — see civex.services.db_service).


def _load_config():
    try:
        return load_config()
    except ConfigError as e:
        raise HTTPException(500, detail=str(e))


def _to_response(status: db_service.DbStatus) -> DbStatusResponse:
    return DbStatusResponse(
        url=status.url,
        dialect=status.dialect,
        docker_managed=status.docker_managed,
        migration=MigrationStatusResponse(
            current_revision=status.migration.current_revision,
            head_revision=status.migration.head_revision,
            up_to_date=status.migration.up_to_date,
            error=status.migration.error,
        ),
        docker=(
            DockerStatusResponse(
                name=status.docker.name,
                exists=status.docker.exists,
                running=status.docker.running,
                volume_exists=status.docker.volume_exists,
            )
            if status.docker is not None
            else None
        ),
    )


@router.get("/status", response_model=DbStatusResponse)
def get_status() -> DbStatusResponse:
    config = _load_config()
    return _to_response(db_service.get_status(config))


@router.post("/migrate", response_model=DbStatusResponse)
def migrate() -> DbStatusResponse:
    config = _load_config()
    try:
        return _to_response(db_service.migrate(config))
    except Exception as exc:
        raise HTTPException(422, detail=str(exc))


@router.patch("/config", response_model=DbStatusResponse)
def set_url(body: SetDbUrlRequest) -> DbStatusResponse:
    config = _load_config()
    try:
        return _to_response(db_service.set_url(config, body.url))
    except ValidationError as exc:
        raise HTTPException(422, detail=str(exc))


@router.post("/docker/setup", response_model=DbStatusResponse)
def docker_setup() -> DbStatusResponse:
    config = _load_config()
    try:
        return _to_response(db_service.setup_docker(config))
    except ValidationError as exc:
        raise HTTPException(422, detail=str(exc))


@router.post("/docker/teardown", response_model=DbStatusResponse)
def docker_teardown() -> DbStatusResponse:
    """Removes the Docker container and its data volume, but leaves
    config.toml pointed at it — mirrors `civex db teardown`'s own warning
    that a subsequent setup-docker/--sqlite is needed to keep using this
    project. Returns the (now-broken) status so the UI can show what
    happened rather than a bare 204."""
    config = _load_config()
    try:
        db_service.teardown_docker(config)
    except ValidationError as exc:
        raise HTTPException(422, detail=str(exc))
    return _to_response(db_service.get_status(config))
