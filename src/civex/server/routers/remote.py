"""Following an authority, from this project's side: connect, see how it is
going, sync now, pause, and settle conflicts. (What an authority offers to devices
is `/sync/v1`; this is for people.)"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from civex.context import AppContext
from civex.domain.exceptions import ValidationError
from civex.domain.sync import SyncError
from civex.server.deps import get_ctx
from civex.services.sync_jobs import sync_jobs

router = APIRouter(prefix="/remote", tags=["sync"])


class SyncProgressResponse(BaseModel):
    phase: str = Field(description="copying, filling or history.")
    done: int = Field(description="Things (or history entries) done so far.")
    total: int | None = Field(description="Out of how many; null when not known.")
    kind: str | None = Field(
        default=None, description="The kind of thing it is on (schema, record...)."
    )


class RemoteStatusResponse(BaseModel):
    configured: bool = Field(description="Whether this project follows an authority.")
    remote: str | None = Field(description="The authority's address.")
    project_id: str
    paused: bool = Field(description="The schedule is stopped; Sync now still works.")
    interval_seconds: int = Field(
        description="How often it looks for changes; 0 means only when asked."
    )
    serving: bool = Field(description="This project is itself an authority.")
    pending: int = Field(description="Changes made here that have not been sent.")
    open_conflicts: int = Field(description="Values that did not go in as made.")
    last_synced_at: str | None
    last_error: str | None = Field(
        description="Why the last attempt failed, if it did."
    )
    last_error_at: str | None
    running: bool = Field(description="A sync is in progress right now.")
    download_files: str = Field(
        description="Which files this device keeps a copy of: all, or opened."
    )
    files_to_fetch: int = Field(
        description="Files records here cite that aren't on this computer yet."
    )
    last_result: SyncResultResponse | None = Field(
        default=None,
        description="What the last sync run by this server did; null after a "
        "restart or before the first one.",
    )
    progress: SyncProgressResponse | None = Field(
        default=None,
        description="How far a long step has got while one runs here: copying "
        "the project from the authority, filling an empty one, or fetching the "
        "history from before joining.",
    )
    connecting: bool = Field(
        default=False, description="A connect started here is still running."
    )
    connect_error: str | None = Field(
        default=None, description="Why the last connect started here failed."
    )


class SyncResultResponse(BaseModel):
    pulled: int = Field(description="Changes from others brought in.")
    pushed: int = Field(description="Changes of this project's that were sent.")
    files_sent: int
    conflicts: int = Field(description="Values that did not go in as made.")
    rejected: int = Field(description="Changes the authority refused.")


class RemoteConnectRequest(BaseModel):
    url: str = Field(description="The authority's address.")
    token: str | None = Field(
        default=None,
        description="The device token the authority issued. Leave out to use the "
        "one this computer already holds for that address (trying a connect "
        "again).",
    )


class RemoteConnectResponse(BaseModel):
    mode: str = Field(
        description="joined (became a copy), seeded (filled an empty authority), "
        "empty (both empty) or resumed (already the same project)."
    )


class RemoteUpdateRequest(BaseModel):
    paused: bool | None = Field(default=None, description="Stop or start the schedule.")
    interval_seconds: int | None = Field(
        default=None,
        ge=0,
        description="Seconds between looks for changes; 0 = never (only when asked).",
    )
    download_files: str | None = Field(
        default=None,
        description="Keep a copy of every file (all), or only of files opened "
        "or exported (opened).",
    )


class ConflictResponse(BaseModel):
    id: str
    kind: str = Field(description="conflict, rejected or edit_vs_delete.")
    entity_type: str
    entity_id: str
    field: str | None
    yours: Any = Field(description="The value this device set.")
    theirs: Any = Field(description="The value the authority kept.")
    base: Any = Field(
        default=None, description="What the value was before either side changed it."
    )
    theirs_actor: str | None = Field(
        default=None, description="Who wrote the value that stayed."
    )
    theirs_at: str | None = Field(default=None, description="When they wrote it.")
    device_name: str | None
    message: str | None
    status: str = Field(description="open or resolved.")
    created_at: str
    resolved_at: str | None
    resolution: str | None = Field(
        description="mine, theirs, value, edited, delete or retry, once resolved."
    )
    record_name: str | None = Field(
        default=None, description="The record's name as it is now (records only)."
    )
    dataset_name: str | None = Field(default=None, description="Its collection.")
    schema_name: str | None = Field(default=None, description="Its schema.")
    field_label: str | None = Field(
        default=None, description="The field's label now; null if the field is gone."
    )
    dtype: str | None = Field(default=None, description="The field's type.")
    current: Any = Field(default=None, description="The value on the record now.")
    stale: bool = Field(
        default=False,
        description="The record's value is no longer the one that stayed: it changed "
        "again since, so putting yours back would overwrite something newer.",
    )
    record_deleted: bool = Field(
        default=False, description="The record is deleted (restore it first)."
    )
    takes: list[str] = Field(
        default_factory=list,
        description="What this can be settled with: theirs, mine, value, delete, retry "
        "(`edited` is also accepted for a clash, but is not a choice to offer).",
    )
    also_saved: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Other values the same edit set that did go in: field_label, value.",
    )
    attempted: str | None = Field(
        default=None,
        description="For a refused change or an edit that met a delete: what was "
        "tried (create, update or delete).",
    )
    changes: list[dict[str, Any]] = Field(
        default_factory=list,
        description="The fields that attempt set, for showing it on the record: "
        "field_id, field_name, field_label, dtype, before, after and current.",
    )


class ResolveRequest(BaseModel):
    take: str = Field(
        description="`theirs` keeps what the authority has (or lets a refused change "
        "go); `mine` puts your value back as a new edit; `value` puts the one in "
        "`value`; `delete` deletes a record that was deleted there; `retry` sends a "
        "refused change again from the record as it is now; `edited` closes a clash "
        "because the field was just set by hand on the record."
    )
    value: Any = Field(default=None, description="The value, for `take: value`.")
    force: bool = Field(
        default=False,
        description="Put the value back even though the record's value changed "
        "since the conflict was recorded.",
    )


class ResolveManyRequest(BaseModel):
    take: str = Field(
        description="How to settle each one: `theirs`, `mine`, `delete` or `retry` "
        "(see the single resolve). `value` is not offered: it needs a value each."
    )
    ids: list[str] | None = Field(
        default=None, description="Only these conflicts. Omit for all that match."
    )
    kind: str | None = Field(
        default=None,
        description="Only this kind: conflict, rejected or edit_vs_delete.",
    )
    record_id: str | None = Field(
        default=None, description="Only conflicts about this record."
    )
    force: bool = Field(
        default=False,
        description="For `mine`: put values back even where the record's value "
        "changed since.",
    )
    dry_run: bool = Field(
        default=False,
        description="Only count what would be settled; change nothing.",
    )


class ResolveFailure(BaseModel):
    id: str
    message: str


class ResolveManyResponse(BaseModel):
    done: int = Field(description="Settled (with `dry_run`, how many would be).")
    settled_ids: list[str] = Field(
        description="Which were settled (empty for `dry_run`); `reopen` takes them "
        "back if the way was `theirs`."
    )
    not_offered: int = Field(
        description="Left open because they don't offer that way of settling."
    )
    failed: list[ResolveFailure] = Field(
        description="Left open because they failed their checks; the rest were settled."
    )


class ReopenRequest(BaseModel):
    ids: list[str] = Field(description="Conflicts to open again.")


class ReopenResponse(BaseModel):
    reopened: int = Field(
        description="How many were opened again. Only conflicts settled with "
        "`theirs` can be: that changed nothing, so it can be taken back."
    )


def _uuids(values: list[str]) -> list[uuid.UUID]:
    try:
        return [uuid.UUID(v) for v in values]
    except ValueError:
        raise HTTPException(422, detail="Not a conflict id")


def _last_result() -> SyncResultResponse | None:
    r = sync_jobs.worker.last_report
    if r is None:
        return None
    return SyncResultResponse(
        pulled=r.pulled,
        pushed=r.pushed,
        files_sent=r.files_sent,
        conflicts=r.conflicts,
        rejected=r.rejected,
    )


def _status(ctx: AppContext) -> RemoteStatusResponse:
    s = ctx.sync_svc.status()
    return RemoteStatusResponse(
        configured=s.configured,
        remote=s.remote,
        project_id=s.project_id,
        paused=s.paused,
        interval_seconds=s.interval_seconds,
        serving=s.serving,
        pending=s.pending,
        open_conflicts=s.open_conflicts,
        last_synced_at=s.last_synced_at,
        last_error=s.last_error,
        last_error_at=s.last_error_at,
        running=s.running,
        download_files=s.download_files,
        files_to_fetch=s.files_to_fetch,
        last_result=_last_result(),
        progress=(
            SyncProgressResponse(**p.to_dict()) if (p := sync_jobs.progress) else None
        ),
        connecting=sync_jobs.connecting,
        connect_error=sync_jobs.connect_error,
    )


def _refuse(e: SyncError) -> HTTPException:
    # Not reachable (try later) is a bad gateway; anything else is the request's.
    return HTTPException(502 if e.retryable else 400, detail=str(e))


@router.get("", response_model=RemoteStatusResponse)
def status(ctx: AppContext = Depends(get_ctx)):
    """How this project stands with its authority."""
    return _status(ctx)


@router.post("/connect", response_model=RemoteConnectResponse, status_code=202)
def connect(body: RemoteConnectRequest, ctx: AppContext = Depends(get_ctx)):
    """Point this project at an authority. An empty project becomes a copy of
    it; a project with data fills an empty authority; two with data are refused.

    The address, token and who holds data are checked before this answers, so
    a mistake is said at once. Copying can take a long time, so it then runs in
    the background: `GET /remote` says how far it has got (`progress`), and why
    it stopped if it did (`connect_error`)."""
    try:
        mode = ctx.sync_svc.check_connect(body.url, body.token)
    except SyncError as e:
        raise _refuse(e)
    sync_jobs.start_connect(body.url, body.token)
    return RemoteConnectResponse(mode=mode)


@router.post("/disconnect", response_model=RemoteStatusResponse)
def disconnect(ctx: AppContext = Depends(get_ctx)):
    """Stop following the authority. The data here stays."""
    ctx.sync_svc.disconnect()
    ctx.commit()
    return _status(ctx)


@router.post("/sync", status_code=202)
def sync_now(ctx: AppContext = Depends(get_ctx)):
    """Ask for a sync now. It runs in the background; `GET /remote` shows how it went."""
    if not ctx.sync_svc.configured:
        raise HTTPException(400, detail="This project is not following an authority")
    sync_jobs.sync_now()
    return {"requested": True}


@router.patch("", response_model=RemoteStatusResponse)
def update(body: RemoteUpdateRequest, ctx: AppContext = Depends(get_ctx)):
    """Pause or resume the schedule, change how often it looks, or choose which
    files this device keeps a copy of."""
    if body.paused is not None:
        ctx.sync_svc.set_paused(body.paused)
    if body.interval_seconds is not None:
        ctx.sync_svc.set_interval(body.interval_seconds)
    if body.download_files is not None:
        ctx.sync_svc.set_download_files(body.download_files)
    return _status(ctx)


@router.get("/conflicts", response_model=list[ConflictResponse])
def conflicts(
    status: str | None = Query(default="open", description="open, resolved, or all."),
    record: str | None = Query(
        default=None, description="Only conflicts about this record or thing."
    ),
    ctx: AppContext = Depends(get_ctx),
):
    """Values that did not go in as made, with both sides."""
    found = ctx.sync_svc.conflicts(
        None if status in (None, "all") else status,
        _uuids([record])[0] if record else None,
    )
    return [ConflictResponse(**c.to_dict()) for c in found]


@router.post("/conflicts/{conflict_id}/resolve", response_model=RemoteStatusResponse)
def resolve(conflict_id: str, body: ResolveRequest, ctx: AppContext = Depends(get_ctx)):
    """Settle a conflict. Putting a value back is an ordinary edit (checked, in the
    history, synced); it answers 409 with what is there now when the record's value
    changed since the conflict was recorded, unless `force`."""
    try:
        cid = uuid.UUID(conflict_id)
    except ValueError:
        raise HTTPException(422, detail="Not a conflict id")
    ctx.sync_svc.resolve_conflict(cid, body.take, body.value, body.force)
    ctx.commit()
    if body.take == "retry":
        sync_jobs.sync_now()  # the answer settles it: ask for it now
    return _status(ctx)


@router.post("/conflicts/resolve-many", response_model=ResolveManyResponse)
def resolve_many(body: ResolveManyRequest, ctx: AppContext = Depends(get_ctx)):
    """Settle every open conflict that matches (the given ids, kind and record; all
    of them if none is given) the same way, in one request. Conflicts that don't
    offer that way, or fail their checks, stay open and are counted or listed: the
    rest are still settled. `dry_run` only counts."""
    if body.take == "value":
        raise HTTPException(422, detail="`value` needs a value for each conflict")
    report = ctx.sync_svc.resolve_many(
        body.take,
        ids=_uuids(body.ids) if body.ids is not None else None,
        kind=body.kind,
        entity_id=_uuids([body.record_id])[0] if body.record_id else None,
        force=body.force,
        dry_run=body.dry_run,
    )
    ctx.commit()
    return ResolveManyResponse(
        done=report.done,
        settled_ids=[str(i) for i in report.settled],
        not_offered=report.not_offered,
        failed=[ResolveFailure(id=str(i), message=m) for i, m in report.failed],
    )


@router.post("/conflicts/reopen", response_model=ReopenResponse)
def reopen(body: ReopenRequest, ctx: AppContext = Depends(get_ctx)):
    """Open conflicts again that were settled with `theirs` (an undo: that choice
    changed nothing). Others are ignored; undo those from Activity."""
    n = ctx.sync_svc.reopen_conflicts(_uuids(body.ids))
    ctx.commit()
    return ReopenResponse(reopened=n)


# -- this project as an authority ------------------------------------------------
# What `civex sync authority` and `civex sync device` do, for the app: the same
# service calls, so the two can't differ.


class DeviceResponse(BaseModel):
    name: str
    created_at: str
    last_seen_at: str | None = Field(description="When it last synced; null if never.")
    revoked: bool = Field(description="Its token no longer works.")


class AuthorityResponse(BaseModel):
    serving: bool = Field(description="This project accepts devices.")
    devices: list[DeviceResponse] = Field(
        description="The devices that have been issued a token."
    )


class AuthorityUpdateRequest(BaseModel):
    serving: bool = Field(description="Accept devices, or stop accepting them.")


class DeviceRequest(BaseModel):
    name: str = Field(description="What to call the device.")


class IssuedDeviceResponse(AuthorityResponse):
    token: str = Field(
        description="The new device's token. Shown once: only its hash is kept."
    )


def _authority(ctx: AppContext) -> AuthorityResponse:
    return AuthorityResponse(
        serving=ctx.sync_svc.status().serving,
        devices=[
            DeviceResponse(
                name=d.name,
                created_at=d.created_at,
                last_seen_at=d.last_seen_at,
                revoked=d.revoked_at is not None,
            )
            for d in ctx.authority_svc.list_devices()
        ],
    )


@router.get("/authority", response_model=AuthorityResponse)
def authority(ctx: AppContext = Depends(get_ctx)):
    """Whether this project accepts devices, and the devices issued a token."""
    return _authority(ctx)


@router.patch("/authority", response_model=AuthorityResponse)
def update_authority(body: AuthorityUpdateRequest, ctx: AppContext = Depends(get_ctx)):
    """Start or stop accepting devices. Their tokens stay on record."""
    ctx.sync_svc.set_serving(body.serving)
    return _authority(ctx)


@router.post("/authority/devices", response_model=IssuedDeviceResponse)
def add_device(body: DeviceRequest, ctx: AppContext = Depends(get_ctx)):
    """Issue a device a token. The answer is the only time it is shown."""
    try:
        _, token = ctx.authority_svc.add_device(body.name)
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    ctx.commit()
    return IssuedDeviceResponse(**_authority(ctx).model_dump(), token=token)


@router.post("/authority/devices/{name}/revoke", response_model=AuthorityResponse)
def revoke_device(name: str, ctx: AppContext = Depends(get_ctx)):
    """Stop a device's token working."""
    if not ctx.authority_svc.revoke_device(name):
        raise HTTPException(404, detail=f"No active device named {name}")
    ctx.commit()
    return _authority(ctx)
