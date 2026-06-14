from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from civex.domain.exceptions import AlreadyExistsError, CivexError, NotFoundError, ValidationError
from civexhub.config import HubConfig, load_config
from civexhub.db.session import _apply_hub_migrations, create_hub_tables, get_engine
from civexhub.server.routers import auth, data, orgs, repos, settings, sync


@lru_cache(maxsize=1)
def _config() -> HubConfig:
    return load_config()


def get_hub_engine():
    return get_engine(_config().database_url)


def get_object_store():
    cfg = _config()
    if cfg.object_store == "s3":
        from civexhub.repositories.object_store import S3ObjectStore
        return S3ObjectStore(
            bucket=cfg.s3_bucket,
            prefix=cfg.s3_prefix,
            endpoint_url=cfg.s3_endpoint_url,
            access_key=cfg.s3_access_key,
            secret_key=cfg.s3_secret_key,
        )
    from civexhub.repositories.object_store import FilesystemObjectStore
    return FilesystemObjectStore(cfg.objects_dir)


def create_app() -> FastAPI:
    app = FastAPI(title="civex-hub", version="0.1.0")

    @app.on_event("startup")
    def _run_migrations() -> None:
        _apply_hub_migrations(get_hub_engine())

    @app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(AlreadyExistsError)
    async def conflict_handler(request: Request, exc: AlreadyExistsError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ValidationError)
    async def validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(CivexError)
    async def civex_error_handler(request: Request, exc: CivexError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    app.include_router(auth.router)
    app.include_router(repos.router)
    app.include_router(sync.router)
    app.include_router(orgs.router)
    app.include_router(data.router)
    app.include_router(settings.router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    dist_dir = Path(__file__).parent.parent.parent.parent / "frontend" / "dist"
    if dist_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(dist_dir / "assets")), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str) -> object:
            from fastapi.responses import FileResponse
            return FileResponse(str(dist_dir / "index.html"))

    return app


app = create_app()
