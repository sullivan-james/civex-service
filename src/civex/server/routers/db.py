from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from civex.domain.exceptions import ValidationError
from civex.project import Project
from civex.server.deps import current_project
from civex.server.models import (
    ConnectionCheckResponse,
    DatabaseSummaryResponse,
    DbStatusResponse,
    DockerStatusResponse,
    MigrationStatusResponse,
    MoveJobResponse,
    MovePreflightResponse,
    MoveProgressResponse,
    MoveRecordResponse,
    MoveTargetRequest,
    SetDbUrlRequest,
)
from civex.services import db_move_service as moves
from civex.services import db_service
from civex.services.db_move_jobs import MoveJob, jobs

router = APIRouter(prefix="/db", tags=["db"])

# Deliberately does not use Depends(get_ctx): these routes must keep working
# even when the configured database itself is unreachable or misconfigured
# (that's the whole point of exposing status/migrate/set-url/docker
# setup+teardown as their own surface — see civex.services.db_service). They
# take only the project's settings (`current_project`), which needs no database.


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
def get_status(project: Project = Depends(current_project)) -> DbStatusResponse:
    config = project.config
    return _to_response(db_service.get_status(config))


@router.post("/migrate", response_model=DbStatusResponse)
def migrate(project: Project = Depends(current_project)) -> DbStatusResponse:
    config = project.config
    try:
        return _to_response(db_service.migrate(config))
    except Exception as exc:
        raise HTTPException(422, detail=str(exc))


@router.patch("/config", response_model=DbStatusResponse)
def set_url(
    body: SetDbUrlRequest, project: Project = Depends(current_project)
) -> DbStatusResponse:
    config = project.config
    try:
        return _to_response(db_service.set_url(config, body.url))
    except ValidationError as exc:
        raise HTTPException(422, detail=str(exc))


@router.post("/docker/setup", response_model=DbStatusResponse)
def docker_setup(project: Project = Depends(current_project)) -> DbStatusResponse:
    config = project.config
    try:
        return _to_response(db_service.setup_docker(config))
    except ValidationError as exc:
        raise HTTPException(422, detail=str(exc))


@router.post("/docker/teardown", response_model=DbStatusResponse)
def docker_teardown(project: Project = Depends(current_project)) -> DbStatusResponse:
    """Removes the Docker container and its data volume, but leaves
    config.toml pointed at it — mirrors `civex db teardown`'s own warning
    that a subsequent setup-docker/--sqlite is needed to keep using this
    project. Returns the (now-broken) status so the UI can show what
    happened rather than a bare 204."""
    config = project.config
    try:
        db_service.teardown_docker(config)
    except ValidationError as exc:
        raise HTTPException(422, detail=str(exc))
    return _to_response(db_service.get_status(config))


# --- Moving the project's data to another database ---------------------------


def _spec(body: MoveTargetRequest) -> moves.TargetSpec:
    return moves.TargetSpec(**body.model_dump())


def _summary(s: moves.DatabaseSummary) -> DatabaseSummaryResponse:
    return DatabaseSummaryResponse(
        label=s.label,
        dialect=s.dialect,
        location=s.location,
        reachable=s.reachable,
        error=s.error,
        records=s.records,
        rows=s.rows,
        size_bytes=s.size_bytes,
    )


def _record(r: moves.MoveRecord) -> MoveRecordResponse:
    return MoveRecordResponse(**moves.public(r))


def _job(job: MoveJob) -> MoveJobResponse:
    return MoveJobResponse(
        id=job.id,
        status=job.status,  # type: ignore[arg-type]
        progress=MoveProgressResponse(**job.progress.__dict__),
        error=job.error,
        record=_record(job.record) if job.record else None,
    )


@router.get("/summary", response_model=DatabaseSummaryResponse)
def get_summary(project: Project = Depends(current_project)) -> DatabaseSummaryResponse:
    """What is in the database now in use: its kind, location, size and
    record count."""
    config = project.config
    return _summary(moves.summarize(config.db.url, config.db.docker_managed))


@router.post("/test-connection", response_model=ConnectionCheckResponse)
def test_connection(body: MoveTargetRequest) -> ConnectionCheckResponse:
    """Check a PostgreSQL server's details connect, and say in plain words
    what is wrong if they don't."""
    try:
        url = moves.postgres_url(_spec(body))
    except ValidationError as exc:
        return ConnectionCheckResponse(ok=False, error=str(exc))
    err = db_service.test_connection(url)
    return ConnectionCheckResponse(
        ok=err is None, error=moves.explain_connection_error(err) if err else None
    )


@router.post("/move/preflight", response_model=MovePreflightResponse)
def move_preflight(
    body: MoveTargetRequest, project: Project = Depends(current_project)
) -> MovePreflightResponse:
    """What moving to this destination would do, and whether it can -- with
    no side effects: nothing is created, started or written."""
    config = project.config
    check = moves.preflight(config, _spec(body))
    return MovePreflightResponse(
        source=_summary(check.source),
        target=_summary(check.target),
        target_label=check.target_label,
        can_proceed=check.can_proceed,
        problems=check.problems,
        warnings=check.warnings,
        estimate_seconds=check.estimate_seconds,
    )


@router.post("/move", response_model=MoveJobResponse, status_code=202)
def start_move(
    body: MoveTargetRequest, project: Project = Depends(current_project)
) -> MoveJobResponse:
    """Start copying the project's data into the destination, in the
    background; poll `GET /db/move/{id}`. Only when the copy has been verified
    does the project switch to the new database, and the old one is never
    modified, so a move can always be undone."""
    config = project.config
    try:
        return _job(jobs.start(config, _spec(body)))
    except ValidationError as exc:
        raise HTTPException(
            409 if "already running" in str(exc) else 422, detail=str(exc)
        )


@router.get("/move/{job_id}", response_model=MoveJobResponse)
def get_move(job_id: str) -> MoveJobResponse:
    """Progress and outcome of a move started with `POST /db/move`."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, detail="No such move.")
    return _job(job)


@router.post("/move/{job_id}/cancel", response_model=MoveJobResponse)
def cancel_move(job_id: str) -> MoveJobResponse:
    """Ask a running move to stop. Nothing is changed: the copy is one
    transaction, and the project keeps using its current database."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, detail="No such move.")
    jobs.cancel(job_id)
    return _job(job)


@router.get("/moves", response_model=list[MoveRecordResponse])
def list_moves(project: Project = Depends(current_project)) -> list[MoveRecordResponse]:
    """Past database moves, newest first."""
    return [_record(r) for r in moves.list_moves(project.config)]


@router.post("/moves/{move_id}/revert", response_model=DbStatusResponse)
def revert_move(
    move_id: str, project: Project = Depends(current_project)
) -> DbStatusResponse:
    """Point the project back at the database a move came from. Nothing is
    copied: anything written to the new database since stays there."""
    config = project.config
    try:
        moves.revert(config, move_id)
    except ValidationError as exc:
        raise HTTPException(422, detail=str(exc))
    return _to_response(db_service.get_status(config))
