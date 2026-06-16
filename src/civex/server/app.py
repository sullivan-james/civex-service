from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from civex.domain.exceptions import CivexError
from civex.server.routers import datasets, dump, files, jobs, records, remote, schemas, terminal, workflows

_DIST = Path(__file__).parent / "static"
if not (_DIST / "index.html").exists():
    _DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(
        title="civex",
        description="Research data management API",
        version="0.1.0",
    )

    @app.exception_handler(CivexError)
    async def civex_error_handler(request: Request, exc: CivexError) -> JSONResponse:
        from civex.domain.exceptions import NotFoundError, AlreadyExistsError, ValidationError
        if isinstance(exc, NotFoundError):
            status = 404
        elif isinstance(exc, AlreadyExistsError):
            status = 409
        elif isinstance(exc, ValidationError):
            status = 422
        else:
            status = 500
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    app.include_router(schemas.router, prefix="/api")
    app.include_router(datasets.router, prefix="/api")
    app.include_router(dump.router, prefix="/api")
    app.include_router(records.router, prefix="/api")
    app.include_router(files.router, prefix="/api")
    app.include_router(workflows.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")
    app.include_router(remote.router, prefix="/api")
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
            return {"message": "civex API — run `cd frontend && npm run build` then reinstall"}

    return app


app = create_app()
