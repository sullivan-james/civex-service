from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from civex.config import load_config, save_config
from civex.domain.exceptions import ConfigError
from civex.repositories.local.file_store import LocalFileObjectStore
from civex.sync.exporter import export_bundle
from civex.sync.importer import apply_bundle
from civex.sync.transport import SyncError, get_transport

router = APIRouter(prefix="/remote", tags=["remote"])


class RemoteStatus(BaseModel):
    url: str
    last_pushed_at: datetime | None
    last_pulled_at: datetime | None


class SyncResult(BaseModel):
    schemas: int
    datasets: int
    records: int
    objects: int


@router.get("", response_model=RemoteStatus)
def remote_status():
    """Return the configured remote URL and last sync timestamps."""
    try:
        config = load_config()
    except ConfigError as e:
        raise HTTPException(500, detail=str(e))
    if config.remote is None:
        raise HTTPException(404, detail="No remote configured")
    return RemoteStatus(
        url=config.remote.url,
        last_pushed_at=config.remote.last_pushed_at,
        last_pulled_at=config.remote.last_pulled_at,
    )


@router.post("/push", response_model=SyncResult)
def remote_push():
    """Push local changes to the remote bare repository."""
    try:
        config = load_config()
    except ConfigError as e:
        raise HTTPException(500, detail=str(e))
    if config.remote is None:
        raise HTTPException(400, detail="No remote configured. Run `civex remote set <url>` first.")

    try:
        transport, _path = get_transport(config.remote.url)
    except SyncError as e:
        raise HTTPException(400, detail=str(e))

    from civex.db.session import _engine
    from sqlalchemy.orm import Session

    since = config.remote.last_pushed_at
    with Session(_engine()) as session:
        bundle = export_bundle(session, since)

    local_store = LocalFileObjectStore(config.objects_dir)
    pushed_objects = 0
    for sha256 in bundle.object_refs:
        if local_store.exists(sha256):
            try:
                transport.put_object(sha256, local_store.get(sha256))
                pushed_objects += 1
            except SyncError:
                pass

    try:
        transport.receive_pack(bundle)
    except SyncError as e:
        raise HTTPException(502, detail=f"Push failed: {e}")

    config.remote.last_pushed_at = datetime.now(timezone.utc)
    save_config(config)

    return SyncResult(
        schemas=len(bundle.schemas),
        datasets=len(bundle.datasets),
        records=len(bundle.records),
        objects=pushed_objects,
    )


@router.post("/pull", response_model=SyncResult)
def remote_pull():
    """Pull remote changes into the local project."""
    try:
        config = load_config()
    except ConfigError as e:
        raise HTTPException(500, detail=str(e))
    if config.remote is None:
        raise HTTPException(400, detail="No remote configured. Run `civex remote set <url>` first.")

    try:
        transport, _path = get_transport(config.remote.url)
    except SyncError as e:
        raise HTTPException(400, detail=str(e))

    try:
        bundle = transport.transfer_pack(since=config.remote.last_pulled_at)
    except SyncError as e:
        raise HTTPException(502, detail=f"Pull failed: {e}")

    from civex.db.session import _engine
    from sqlalchemy.orm import Session

    with Session(_engine()) as session:
        apply_bundle(session, bundle)
        session.commit()

    config.remote.last_pulled_at = datetime.now(timezone.utc)
    save_config(config)

    return SyncResult(
        schemas=len(bundle.schemas),
        datasets=len(bundle.datasets),
        records=len(bundle.records),
        objects=len(bundle.object_refs),
    )
