from __future__ import annotations

import uuid
from collections.abc import Generator

from fastapi import Depends, Request
from sqlalchemy.exc import OperationalError

from civex.config import load_config
from civex.context import AppContext, build_context
from civex.domain.exceptions import (
    ConfigError,
    DatabaseUnavailableError,
    FeatureUnavailableError,
)
from civex.project import Project


def _recovery_failure_message(result) -> str:  # noqa: ANN001 — ContainerRecoveryResult
    from civex.docker_manager import ContainerRecoveryOutcome

    if result.outcome == ContainerRecoveryOutcome.DOCKER_UNAVAILABLE:
        return (
            "Database container is unreachable and Docker itself isn't "
            "available on this host right now."
        )
    if result.outcome == ContainerRecoveryOutcome.START_FAILED:
        return (
            f"Database container '{result.container_name}' exists but failed "
            f"to start: {result.detail}"
        )
    if result.outcome == ContainerRecoveryOutcome.MISSING_VOLUME_PRESENT:
        return (
            f"Database container '{result.container_name}' is missing, but its "
            "data volume is still present. Run `civex db setup-docker` to "
            "recreate the container — your data will be reattached."
        )
    return (
        f"Database container '{result.container_name}' and its data volume "
        "are both gone — any prior data is likely unrecoverable. Restore "
        "from a backup if you have one, or run `civex db setup-docker` to "
        "create a brand-new, empty database."
    )


def _build_context_with_recovery(project: Project) -> AppContext:
    """
    build_context(), but for docker-managed projects: on a connection
    failure, try to auto-start a stopped container and retry once before
    giving up. Safe to retry here — nothing has run yet.
    """
    from civex.docker_manager import ContainerRecoveryOutcome, ensure_container_running

    config = project.config
    try:
        return build_context(project)
    except OperationalError:
        if not config.db.docker_managed:
            raise
        result = ensure_container_running(config.project_root.name)
        if result.outcome == ContainerRecoveryOutcome.READY:
            return build_context(project)
        raise DatabaseUnavailableError(_recovery_failure_message(result)) from None


def _recover_after_query_failure(project: Project) -> None:
    """
    A query failed mid-request. This is the common case in practice: the
    connection was fine when get_ctx() built the context (ensure_schema_current
    only connects once per engine per process — see db/migrate.py), but the
    container has since gone down. Too late to safely retry this request's
    already-partially-applied logic, so this always raises — but for a
    docker-managed project it first tries to fix the container so the
    client's retry succeeds.
    """
    config = project.config
    if not config.db.docker_managed:
        return

    from civex.docker_manager import ContainerRecoveryOutcome, ensure_container_running

    result = ensure_container_running(config.project_root.name)
    if result.outcome == ContainerRecoveryOutcome.READY:
        raise DatabaseUnavailableError(
            f"Database connection to container '{result.container_name}' was "
            "lost and has been restarted — please retry your request."
        ) from None
    raise DatabaseUnavailableError(_recovery_failure_message(result)) from None


BATCH_HEADER = "X-Civex-Batch"


def _join_request_batch(ctx: AppContext, request: Request) -> None:
    """Put a request's changes in the batch its client named, so work done over
    many requests (an import) is one event in history. A missing or unknown
    batch is ignored: the changes are then simply recorded on their own."""
    raw = request.headers.get(BATCH_HEADER)
    if not raw:
        return
    try:
        ctx.audit_svc.join_batch(uuid.UUID(raw))
    except ValueError:
        pass


def _local_project(request: Request) -> Project:
    """The project in the directory the server was started in: what
    `civex serve` hosts. ConfigError propagates to the registered CivexError
    handler (400), rather than being turned into a bare 500 here -- the same
    exception type must map to the same status regardless of where it's raised."""
    return Project.local(load_config())


def current_project(request: Request) -> Project:
    """The project this request is about. `civex serve` hosts the one in its
    directory; a host serving many installs its own `app.state.project_resolver`
    (a `Request -> Project`) and every route and context follows it. Resolved
    once per request, so the routes that need only the settings (the database
    and settings routers) read the same project the context is built for."""
    project = getattr(request.state, "project", None)
    if project is None:
        resolve = getattr(request.app.state, "project_resolver", None) or _local_project
        project = resolve(request)
        request.state.project = project
    return project


def requires(feature: str):  # noqa: ANN201 - a FastAPI dependency marker
    """`dependencies=[requires(VOLUMES)]` on a route or router: 501 with a
    plain-words detail when the project's host doesn't offer the feature
    (`domain.features`). The one way a route says what it needs; the host's
    router list (`app.api_routers`) is the same answer at include time."""

    def check(request: Request) -> None:
        try:
            project = current_project(request)
        except ConfigError:
            # No project here: the route says so in its own way, as it did
            # before anything asked about features.
            return
        if feature not in project.features:
            raise FeatureUnavailableError(feature)

    return Depends(check)


def get_ctx(request: Request) -> Generator[AppContext, None, None]:
    project = current_project(request)
    ctx = _build_context_with_recovery(project)
    _join_request_batch(ctx, request)
    try:
        yield ctx
        ctx.commit()
    except OperationalError:
        ctx._session.rollback()
        _recover_after_query_failure(project)
        raise
    except Exception:
        ctx._session.rollback()
        raise
    finally:
        ctx.close()
