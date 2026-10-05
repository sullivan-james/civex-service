from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from civex.server.errors import RequestContextMiddleware, register_error_handlers
from civex.server.routers import (
    ai,
    analytics,
    audit,
    datasets,
    db,
    dump,
    files,
    jobs,
    legal,
    plugins,
    records,
    retention,
    schemas,
    settings,
    status,
    store,
    terminal,
    transfers,
    views,
    workflows,
)
from civex.server.security import LocalGuardMiddleware


def _find_dist() -> Path:
    # 1. Package-installed static copy (populated by `civex install` / pip data)
    p = Path(__file__).parent / "static"
    if (p / "index.html").exists():
        return p
    # 2. PyInstaller one-file bundle — sys._MEIPASS is the temp extraction root
    if getattr(sys, "frozen", False):
        p = Path(getattr(sys, "_MEIPASS")) / "frontend_dist"  # noqa: SLF001
        if (p / "index.html").exists():
            return p
    # 3. Development source tree
    return Path(__file__).resolve().parents[3] / "frontend" / "dist"


_DIST = _find_dist()


def _init_observability() -> None:
    """Configure logging + telemetry from env vars and (best-effort) project config.

    Runs at app creation so it takes effect inside uvicorn's --reload worker too.
    Falls back to sane defaults when no civex project is present (e.g. under tests).
    """
    import os

    from civex.observability import configure_logging, init_telemetry

    level = os.environ.get("CIVEX_LOG_LEVEL", "INFO")
    json_env = os.environ.get("CIVEX_LOG_JSON")
    json_console = None if json_env is None else json_env == "1"
    log_file = None
    dsn = None
    environment = "local"

    try:
        from civex.config import load_config

        cfg = load_config()
        level = os.environ.get("CIVEX_LOG_LEVEL", cfg.logging.level)
        if json_env is None:
            json_console = cfg.logging.json_console
        if cfg.logging.to_file:
            log_file = cfg.civex_dir / "logs" / "civex.log"
        dsn = cfg.telemetry.dsn
        environment = cfg.telemetry.environment
    except Exception:
        pass  # No project / unreadable config — console logging with defaults.

    configure_logging(level=level, json_console=json_console, log_file=log_file)
    init_telemetry(dsn, environment=environment)


_OPENAPI_TAGS = [
    {
        "name": "schemas",
        "description": (
            "Define the shape of your data: schemas are named collections of "
            "typed fields (integer, float, string, boolean, date, datetime, "
            "file, file_list, reference), with restrictions (min/max, choices, "
            "accepted file types, ...) and optional inheritance from a parent "
            "schema. Create a schema before creating any records."
        ),
    },
    {
        "name": "collections",
        "description": (
            "Datasets are named containers of records that all conform to the "
            "same schema. Use this to create, rename, or delete the datasets "
            "you organize records into."
        ),
    },
    {
        "name": "records",
        "description": (
            "Create, read, update, delete, and bulk-import the individual rows "
            "of data that live inside a dataset. Record data is validated "
            "against its schema's field types and restrictions on every write."
        ),
    },
    {
        "name": "files",
        "description": (
            "Upload binary attachments (referenced from `file` / `file_list` "
            "record fields) and download them back out by content hash."
        ),
    },
    {
        "name": "workflows",
        "description": (
            "Author and manage YAML workflow definitions: chains of plugin "
            "steps, triggered automatically on record create/update or run "
            "manually, that read and write record fields."
        ),
    },
    {
        "name": "jobs",
        "description": (
            "Inspect the queue of workflow runs — one job per trigger firing or "
            "manual run — including their status, inputs, and outputs."
        ),
    },
    {
        "name": "audit",
        "description": (
            "Read the change history recorded for records, schemas, fields, "
            "and datasets — every create/update/delete with a full before/"
            "after data snapshot and timestamp."
        ),
    },
    {
        "name": "retention",
        "description": (
            "Clean up by age: deleted items, change history and finished "
            "workflow runs older than the retention settings or a given date."
        ),
    },
    {
        "name": "plugins",
        "description": (
            "Discover the built-in and project-defined plugins available to "
            "use as workflow steps, along with their declared inputs and "
            "outputs. Also handles uploading container-tier (Tier 2) plugins."
        ),
    },
    {
        "name": "ai",
        "description": (
            "AI-assisted helpers layered on top of the data model — schema "
            "suggestions, record extraction, and similar model-backed "
            "endpoints — plus the AI provider configuration they run against."
        ),
    },
    {
        "name": "remote",
        "description": (
            "Push and pull a project's schemas, datasets, and records to/from "
            "a remote civex server, and check the current sync status."
        ),
    },
    {
        "name": "store",
        "description": (
            "Manage the object volumes that back file storage — add, update, "
            "or remove a volume, and inspect per-volume usage stats."
        ),
    },
    {
        "name": "db",
        "description": (
            "Inspect and configure the underlying database connection: "
            "connection status, pending migrations, the configured URL, and "
            "(when using the bundled Docker Postgres) container lifecycle. "
            "Deliberately reachable even when the database itself is down."
        ),
    },
    {
        "name": "dump",
        "description": (
            "Export a full project (schemas, datasets, records) to a single "
            "portable archive, and restore a project from one — the basis for "
            "backups and moving a project between machines."
        ),
    },
    {
        "name": "legal",
        "description": (
            "Read-only endpoints for the software's own license text and "
            "acceptable-use policy, independent of any particular project."
        ),
    },
    {
        "name": "status",
        "description": (
            "Live health checks, such as a round-trip database query, for "
            "monitoring whether a running server is actually functional."
        ),
    },
    {
        "name": "terminal",
        "description": (
            "A WebSocket-backed interactive shell in the project directory, "
            "used by the web UI's embedded terminal panel."
        ),
    },
    {
        "name": "settings",
        "description": (
            "Per-project UI preferences, such as whether the Advanced "
            "navigation section (terminal, YAML editing, plugin editors) "
            "is shown by default."
        ),
    },
    {
        "name": "analytics",
        "description": (
            "Aggregate, filterable, time-bucketed reads over records, "
            "workflow jobs, audit events, and AI usage — the read path "
            "dashboard widgets call. Every endpoint shares one query-param "
            "filter contract (date range, dataset, schema, workflow_id, "
            "plugin_id, status, trigger); each documents which of those it "
            "actually applies."
        ),
    },
]

_DESCRIPTION = """\
civex is a local-first research data management system: schemas, records, \
files, and workflow automation in one place, running on your own machine \
against your own database.

Every endpoint below is served under the `/api` prefix (e.g. `GET /api/schemas`); \
paths in this reference omit that prefix for brevity.

## Errors

Errors share one envelope shape across the API. Domain errors (not found, \
already exists, validation, misconfiguration) return a 4xx/5xx status with a \
JSON body of `{"detail": "<message>"}`. Request body/query validation \
failures return 422 with `{"detail": "Request validation failed", "errors": \
[...]}`, one entry per invalid field. Anything unexpected returns a generic \
500 with `{"detail": "Internal server error", "request_id": "<id>"}` — the \
same id echoed on the `x-request-id` response header, for correlating with \
server logs.

See the [getting started guide](https://civexdata.github.io/civex-docs/getting-started/install.html) \
for installing the CLI and standing up your first project.
"""


def _migrate_on_startup() -> None:
    """Bring the project database to the current schema before serving.

    Best-effort: with no project, or a database that is down, the server must
    still start (the `db` router is deliberately reachable in that state), so
    failures are logged and left for the per-request path to report.
    """
    import structlog

    try:
        from civex.config import load_config
        from civex.context import _get_engine
        from civex.db.migrate import ensure_schema_current

        ensure_schema_current(_get_engine(load_config().db.url))
    except Exception as exc:
        structlog.get_logger("civex.server").warning(
            "startup_migration_skipped", error=str(exc)
        )


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _migrate_on_startup()
    from civex.services.transfer_jobs import jobs

    jobs.ensure_worker()  # picks up anything a restart left waiting
    try:
        yield
    finally:
        jobs.shutdown()


def create_app() -> FastAPI:
    _init_observability()
    from civex import __version__

    app = FastAPI(
        title="civex",
        description=_DESCRIPTION,
        version=__version__,
        openapi_tags=_OPENAPI_TAGS,
        lifespan=_lifespan,
        contact={
            "name": "James Sullivan",
            "email": "sullivanj041@gmail.com",
        },
        license_info={
            "name": "PolyForm Shield 1.0.0",
            "url": "https://polyformproject.org/licenses/shield/1.0.0",
        },
    )

    # Local-only guard: blocks DNS-rebinding and cross-origin (CSRF) attacks
    # against the loopback server. No-op when CIVEX_ALLOW_REMOTE=1.
    app.add_middleware(LocalGuardMiddleware)
    # Added last → outermost: every request gets a correlation id before any
    # other layer runs, and it stays bound through the exception handlers.
    app.add_middleware(RequestContextMiddleware)

    register_error_handlers(app)

    app.include_router(ai.router, prefix="/api")
    app.include_router(schemas.router, prefix="/api")
    app.include_router(datasets.router, prefix="/api")
    app.include_router(dump.router, prefix="/api")
    app.include_router(plugins.router, prefix="/api")
    app.include_router(records.router, prefix="/api")
    app.include_router(files.router, prefix="/api")
    app.include_router(workflows.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")
    app.include_router(jobs.automation_router, prefix="/api")
    app.include_router(audit.router, prefix="/api")
    app.include_router(retention.router, prefix="/api")
    app.include_router(store.router, prefix="/api")
    app.include_router(transfers.router, prefix="/api")
    app.include_router(db.router, prefix="/api")
    app.include_router(legal.router, prefix="/api")
    app.include_router(status.router, prefix="/api")
    app.include_router(terminal.router, prefix="/api")
    app.include_router(settings.router, prefix="/api")
    app.include_router(analytics.router, prefix="/api")
    app.include_router(views.router, prefix="/api")
    app.include_router(views.all_views_router, prefix="/api")

    @app.get("/health", include_in_schema=False)
    def health():
        return {"status": "ok"}

    if (_DIST / "index.html").exists():
        app.mount(
            "/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets"
        )

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_fallback(full_path: str):
            return FileResponse(str(_DIST / "index.html"))
    else:

        @app.get("/", include_in_schema=False)
        def root():
            return {
                "message": (
                    "civex API is running — no built frontend found. "
                    "For production: `cd frontend && npm run build`. "
                    "For development: `cd frontend && npm run dev` then browse to http://localhost:5173"
                )
            }

    return app


app = create_app()
