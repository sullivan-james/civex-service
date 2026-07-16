from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from civex.server.errors import RequestContextMiddleware, register_error_handlers
from civex.server.routers import ai, datasets, dump, files, jobs, plugins, records, remote, schemas, store, terminal, workflows
from civex.server.security import LocalGuardMiddleware


def _find_dist() -> Path:
    # 1. Package-installed static copy (populated by `civex install` / pip data)
    p = Path(__file__).parent / "static"
    if (p / "index.html").exists():
        return p
    # 2. PyInstaller one-file bundle — sys._MEIPASS is the temp extraction root
    if getattr(sys, "frozen", False):
        p = Path(sys._MEIPASS) / "frontend_dist"  # noqa: SLF001
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


def create_app() -> FastAPI:
    _init_observability()
    from civex import __version__
    app = FastAPI(
        title="civex",
        description="Research data management API",
        version=__version__,
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
    app.include_router(remote.router, prefix="/api")
    app.include_router(store.router, prefix="/api")
    app.include_router(terminal.router, prefix="/api")

    @app.get("/health", include_in_schema=False)
    def health():
        return {"status": "ok"}

    if (_DIST / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")

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
