from __future__ import annotations

from collections.abc import Generator

from fastapi import HTTPException
from sqlalchemy.exc import OperationalError

from civex.config import Config, load_config
from civex.context import AppContext, build_local_context
from civex.domain.exceptions import ConfigError, DatabaseUnavailableError


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


def _build_context_with_recovery(config: Config) -> AppContext:
    """
    build_local_context(), but for docker-managed projects: on a connection
    failure, try to auto-start a stopped container and retry once before
    giving up. Safe to retry here — nothing has run yet.
    """
    from civex.docker_manager import ContainerRecoveryOutcome, ensure_container_running

    try:
        return build_local_context(config)
    except OperationalError:
        if not config.db.docker_managed:
            raise
        result = ensure_container_running(config.project_root.name)
        if result.outcome == ContainerRecoveryOutcome.READY:
            return build_local_context(config)
        raise DatabaseUnavailableError(_recovery_failure_message(result)) from None


def _recover_after_query_failure(config: Config) -> None:
    """
    A query failed mid-request. This is the common case in practice: the
    connection was fine when get_ctx() built the context (ensure_schema_current
    only connects once per engine per process — see db/migrate.py), but the
    container has since gone down. Too late to safely retry this request's
    already-partially-applied logic, so this always raises — but for a
    docker-managed project it first tries to fix the container so the
    client's retry succeeds.
    """
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


def get_ctx() -> Generator[AppContext, None, None]:
    try:
        config = load_config()
    except ConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))

    ctx = _build_context_with_recovery(config)
    try:
        yield ctx
        ctx.commit()
    except OperationalError:
        ctx._session.rollback()
        _recover_after_query_failure(config)
        raise
    except Exception:
        ctx._session.rollback()
        raise
    finally:
        ctx.close()
