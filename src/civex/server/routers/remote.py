"""Following an authority, from this project's side: connect, see how it is
going, sync now, pause, and settle conflicts. (What an authority offers to devices
is `/sync/v1`; this is for people.)"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from civex import keys
from civex.context import AppContext
from civex.domain.exceptions import NotAllowedError, NotFoundError, ValidationError
from civex.domain.library import InstallPlan, LibraryItemDTO
from civex.domain.sync import INVITE_HOURS, SyncError
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
    bytes_done: int = Field(default=0, description="Downloading files: bytes so far.")
    rate: float = Field(
        default=0.0, description="Downloading files: bytes per second, lately."
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
    invite: str | None = Field(
        default=None,
        description="The invite the authority's admin gave. Leave out when this "
        "computer has joined that address before (trying a connect again).",
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
    theirs_device: str | None = Field(
        default=None,
        description="The device their change came through (verified by the "
        "authority), when it came through one.",
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
    sits_under: list[dict[str, Any]] = Field(
        default_factory=list,
        description="For a refused record that sits under deleted records here: "
        "those records (id, schema_name, name), topmost first. `restore_above` "
        "brings them back and sends the record again.",
    )


class ResolveRequest(BaseModel):
    take: str = Field(
        description="`theirs` keeps what the authority has (or lets a refused change "
        "go); `mine` puts your value back as a new edit; `value` puts the one in "
        "`value`; `delete` deletes a record that was deleted there; `retry` sends a "
        "refused change again from the record as it is now; `restore_above` brings back "
        "the deleted records a refused record sits under, then sends it again; "
        "`edited` closes a clash "
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

    The address, the invite and who holds data are checked before this answers
    (an invite is used up here: this computer joins the authority), so a
    mistake is said at once. Copying can take a long time, so it then runs in
    the background: `GET /remote` says how far it has got (`progress`), and why
    it stopped if it did (`connect_error`)."""
    try:
        mode = ctx.sync_svc.check_connect(body.url, body.invite)
    except SyncError as e:
        raise _refuse(e)
    sync_jobs.start_connect(body.url)
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
        if body.download_files == "all" and ctx.sync_svc.fetches_files:
            sync_jobs.fetch_now(ctx.sync_svc.files_to_fetch())
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
    fingerprint: str = Field(
        description="Its key's short code, as `civex sync device list` shows it."
    )
    created_at: str = Field(description="When it joined.")
    last_seen_at: str | None = Field(
        description="When it last signed in; null if never."
    )
    revoked: bool = Field(description="It can no longer sign in.")
    may_publish: bool = Field(
        default=False,
        description="It may publish workflows (and plugins, if taken) to the library.",
    )


class InviteResponse(BaseModel):
    name: str = Field(description="The device it is for.")
    created_at: str
    expires_at: str


class AuthorityResponse(BaseModel):
    serving: bool = Field(description="This project accepts devices.")
    fingerprint: str | None = Field(
        description="This authority's key's short code; null until it first invites."
    )
    devices: list[DeviceResponse] = Field(description="The devices that joined.")
    invites: list[InviteResponse] = Field(
        description="Invites not used yet and not expired."
    )
    library: str = Field(
        default="workflows",
        description="What devices allowed to publish may share through this "
        "server's library: off, workflows, or all (plugins too, which are code).",
    )


class AuthorityUpdateRequest(BaseModel):
    serving: bool | None = Field(
        default=None, description="Accept devices, or stop accepting them."
    )
    library: str | None = Field(
        default=None, description="off, workflows or all: what the library takes."
    )


class DevicePublishRequest(BaseModel):
    allowed: bool = Field(description="May it publish to the library.")


class InviteRequest(BaseModel):
    name: str = Field(description="What to call the device.")
    hours: int = Field(default=INVITE_HOURS, description="How long the invite works.")


class InvitedResponse(AuthorityResponse):
    invite: str = Field(
        description="The invite, for the device to connect with. Shown once: "
        "only its hash is kept. It works once."
    )


def _authority(ctx: AppContext) -> AuthorityResponse:
    keys_svc = ctx.device_keys
    return AuthorityResponse(
        serving=ctx.sync_svc.status().serving,
        fingerprint=keys_svc.fingerprint() if keys_svc.has_key() else None,
        devices=[
            DeviceResponse(
                name=d.name,
                fingerprint=keys.fingerprint(d.public_key),
                created_at=d.created_at,
                last_seen_at=d.last_seen_at,
                revoked=d.revoked_at is not None,
                may_publish=d.may_publish,
            )
            for d in keys_svc.list_devices()
        ],
        invites=[
            InviteResponse(
                name=i.name, created_at=i.created_at, expires_at=i.expires_at
            )
            for i in keys_svc.pending_invites()
        ],
        library=ctx.sync_svc.library_mode,
    )


@router.get("/authority", response_model=AuthorityResponse)
def authority(ctx: AppContext = Depends(get_ctx)):
    """Whether this project accepts devices, the devices that joined, and the
    invites waiting."""
    return _authority(ctx)


@router.patch("/authority", response_model=AuthorityResponse)
def update_authority(body: AuthorityUpdateRequest, ctx: AppContext = Depends(get_ctx)):
    """Start or stop accepting devices (the devices stay on record), and say
    what the library takes from them."""
    try:
        if body.library is not None:
            ctx.sync_svc.set_library(body.library)
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    if body.serving is not None:
        ctx.sync_svc.set_serving(body.serving)
    return _authority(ctx)


@router.post("/authority/invites", response_model=InvitedResponse)
def invite_device(body: InviteRequest, ctx: AppContext = Depends(get_ctx)):
    """Invite a device. The answer is the only time the invite is shown."""
    try:
        _, code = ctx.device_keys.invite(body.name, body.hours)
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    ctx.commit()
    return InvitedResponse(**_authority(ctx).model_dump(), invite=code)


@router.post("/authority/invites/{name}/cancel", response_model=AuthorityResponse)
def cancel_invite(name: str, ctx: AppContext = Depends(get_ctx)):
    """Cancel a device's invite before it is used."""
    if not ctx.device_keys.cancel_invite(name):
        raise HTTPException(404, detail=f"No invite waiting for {name}")
    ctx.commit()
    return _authority(ctx)


@router.post("/authority/devices/{name}/revoke", response_model=AuthorityResponse)
def revoke_device(name: str, ctx: AppContext = Depends(get_ctx)):
    """Stop a device syncing, at once: its session is refused from now on."""
    if not ctx.device_keys.revoke_device(name):
        raise HTTPException(404, detail=f"No active device named {name}")
    ctx.commit()
    return _authority(ctx)


@router.post("/authority/devices/{name}/publish", response_model=AuthorityResponse)
def allow_publish(
    name: str, body: DevicePublishRequest, ctx: AppContext = Depends(get_ctx)
):
    """Let a device publish to the library, or stop it."""
    if not ctx.device_keys.allow_publish(name, body.allowed):
        raise HTTPException(404, detail=f"No active device named {name}")
    ctx.commit()
    return _authority(ctx)


# -- the library: shared workflows and plugins --------------------------------
# The same calls whether this project is the authority (its own library) or
# follows one (the authority's), so the authority installs like any device.


class LibraryVersionResponse(BaseModel):
    version: int
    sha256: str
    published_by: str | None = None
    published_at: str | None = None
    pins: dict[str, int] = Field(
        default_factory=dict,
        description="A workflow: the plugin versions it was published with.",
    )


class LibraryItemResponse(BaseModel):
    kind: str = Field(description="workflow or plugin.")
    name: str
    filename: str
    sha256: str
    size: int
    version: int = Field(description="This version's number (the newest in a list).")
    title: str | None = Field(default=None, description="A workflow's own name.")
    description: str | None = None
    provides: str | None = Field(
        default=None, description="A plugin: the plugin id it registers as."
    )
    needs: list[str] = Field(
        default_factory=list, description="A workflow: the plugins its steps use."
    )
    pins: dict[str, int] = Field(
        default_factory=dict,
        description="A workflow: the version of each plugin it was published with.",
    )
    triggers: list[str] = Field(
        default_factory=list, description="A workflow: what starts it by itself."
    )
    published_by: str | None = None
    published_at: str | None = None
    history: list[LibraryVersionResponse] = Field(
        default_factory=list, description="Every version, newest first."
    )
    here: str | None = Field(
        default=None,
        description="On this computer, against this version: absent, same, older "
        "(an earlier version from the library) or different (changed here).",
    )
    local_version: int | None = Field(
        default=None, description="The library version this computer has, if any."
    )
    missing: list[str] = Field(
        default_factory=list,
        description="Plugins it needs that are neither here nor in the library.",
    )
    content: str | None = Field(
        default=None, description="Its text, when asked for one."
    )


class LibraryPublishRequest(BaseModel):
    kind: str = Field(description="workflow or plugin.")
    name: str = Field(description="The workflow's or plugin file's name here.")
    with_plugins: bool = Field(
        default=True, description="A workflow: send the plugins its steps use too."
    )


class LibraryPublishResponse(BaseModel):
    items: list[LibraryItemResponse] = Field(description="The versions stored.")
    warnings: list[str] = Field(
        default_factory=list,
        description="Shared workflows still on an older version of a plugin that "
        "the new version would break.",
    )


class LibraryInstallRequest(BaseModel):
    version: int | None = Field(default=None, description="Omit for the newest.")
    with_plugins: bool = Field(
        default=True,
        description="A workflow: install the plugin versions it is pinned to too.",
    )
    replace: bool = Field(
        default=False, description="Replace files here that were changed here."
    )
    force: bool = Field(
        default=False,
        description="Install even though it would break workflows here.",
    )


class InstallStepResponse(BaseModel):
    item: LibraryItemResponse
    path: str = Field(description="Where it is written, in the project.")
    here: str = Field(
        description="absent, same, older or different, before installing."
    )
    local_version: int | None = Field(
        default=None, description="The library version here now, if any."
    )


class InstallPlanResponse(BaseModel):
    steps: list[InstallStepResponse]
    blocked: list[str] = Field(description="Why it can't be installed as asked.")
    warnings: list[str] = Field(
        description="What to know first (what starts a workflow by itself)."
    )
    breaks: list[str] = Field(
        default_factory=list,
        description="What the new plugin versions would break among the "
        "workflows here.",
    )
    runs_code: bool = Field(
        description="It writes a plugin, which is code this computer will run."
    )


def _item(i: LibraryItemDTO) -> LibraryItemResponse:
    return LibraryItemResponse(
        **{k: v for k, v in i.to_dict().items() if k != "contract"},
        filename=i.filename,
        here=i.here,
        local_version=i.local_version,
        missing=i.missing,
    )


def _plan(plan: InstallPlan) -> InstallPlanResponse:
    return InstallPlanResponse(
        steps=[
            InstallStepResponse(
                item=_item(s.item),
                path=s.path,
                here=s.here,
                local_version=s.local_version,
            )
            for s in plan.steps
        ],
        blocked=plan.blocked,
        warnings=plan.warnings,
        breaks=plan.breaks,
        runs_code=plan.runs_code,
    )


def _library(call):
    try:
        return call()
    except NotAllowedError as e:
        raise HTTPException(403, detail=str(e))
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    except SyncError as e:
        raise _refuse(e)


@router.get("/library", response_model=list[LibraryItemResponse])
def library(ctx: AppContext = Depends(get_ctx)):
    """The workflows and plugins shared through the authority (the newest
    version of each, with its history), and where each stands here. Empty when
    this project shares with no server."""
    if not ctx.library_svc.sharing():
        return []
    return [_item(i) for i in _library(ctx.library_svc.browse)]


@router.get("/library/{kind}/{name}", response_model=LibraryItemResponse)
def library_item(
    kind: str,
    name: str,
    version: int | None = Query(default=None, description="Omit for the newest."),
    ctx: AppContext = Depends(get_ctx),
):
    """One version of a shared workflow or plugin with its text, to read first."""
    return _item(_library(lambda: ctx.library_svc.show(kind, name, version)))


@router.post("/library/publish", response_model=LibraryPublishResponse)
def publish_to_library(body: LibraryPublishRequest, ctx: AppContext = Depends(get_ctx)):
    """Publish a workflow (with the plugins it uses, which it is pinned to) or
    a plugin from this project to the library. New text is the next version."""
    result = _library(
        lambda: ctx.library_svc.publish(body.kind, body.name, body.with_plugins)
    )
    ctx.commit()
    return LibraryPublishResponse(
        items=[_item(i) for i in result.items], warnings=result.warnings
    )


@router.get("/library/{kind}/{name}/install", response_model=InstallPlanResponse)
def install_plan(
    kind: str,
    name: str,
    version: int | None = Query(default=None),
    with_plugins: bool = Query(default=True),
    replace: bool = Query(default=False),
    force: bool = Query(default=False),
    ctx: AppContext = Depends(get_ctx),
):
    """What installing (a version) would write here, what it would break among
    the workflows here, and what stops it. Writes and runs nothing."""
    return _plan(
        _library(
            lambda: ctx.library_svc.plan_install(
                kind, name, version, with_plugins, replace, force
            )
        )
    )


@router.post("/library/{kind}/{name}/install", response_model=InstallPlanResponse)
def install(
    kind: str,
    name: str,
    body: LibraryInstallRequest,
    ctx: AppContext = Depends(get_ctx),
):
    """Install (a version) from the library into this project. A plugin is
    code: it is described before anything is written, and runs on this
    computer from now on."""
    return _plan(
        _library(
            lambda: ctx.library_svc.install(
                kind, name, body.version, body.with_plugins, body.replace, body.force
            )
        )
    )


@router.delete("/library/{kind}/{name}", status_code=204)
def unpublish(
    kind: str,
    name: str,
    version: int | None = Query(
        default=None, description="One version; omit to remove every version."
    ),
    force: bool = Query(
        default=False, description="Even if shared workflows are pinned to it."
    ),
    ctx: AppContext = Depends(get_ctx),
):
    """Take something out of the library. Copies already installed stay."""
    _library(lambda: ctx.library_svc.unpublish(kind, name, version, force))
    ctx.commit()


# -- files on this computer -------------------------------------------------


class CollectionFilesResponse(BaseModel):
    id: str
    name: str
    mode: str = Field(
        description="keep: a copy stays on this computer (fetched in the "
        "background); opened: fetched when opened or exported."
    )
    chosen: bool = Field(
        description="Set for this collection, rather than following the "
        "project's setting."
    )
    files_here: int = Field(description="Files its records use that are here.")
    bytes_here: int = Field(description="Their size.")
    files_on_server: int = Field(
        description="Files its records use that are only on the server."
    )


class CollectionModeRequest(BaseModel):
    mode: str | None = Field(
        description="keep, opened, or null to follow the project's setting."
    )


class FreeUpResponse(BaseModel):
    files: int = Field(description="Copies removed (or that would be, counting).")
    bytes: int = Field(description="The space that frees.")
    kept_shared: int = Field(
        description="Kept: also used by a collection kept on this computer."
    )
    not_on_server: int = Field(
        description="Kept: the server hasn't got them yet (never sent)."
    )
    done: bool = Field(description="False when only counted.")


@router.get("/files", response_model=list[CollectionFilesResponse])
def collection_files(ctx: AppContext = Depends(get_ctx)):
    """Each collection's files on this computer: how many are here and their
    size, how many are only on the server, and whether it keeps a copy here."""
    return [CollectionFilesResponse(**vars(c)) for c in ctx.sync_svc.collection_files()]


@router.patch("/files/{collection}", response_model=list[CollectionFilesResponse])
def set_collection_mode(
    collection: str, body: CollectionModeRequest, ctx: AppContext = Depends(get_ctx)
):
    """Keep a collection's files on this computer, fetch them only when
    opened, or follow the project's setting. Keeping starts the background
    download of what is missing."""
    mode = ctx.sync_svc.set_collection_mode(collection, body.mode)
    if mode == "keep" and ctx.sync_svc.fetches_files:
        sync_jobs.fetch_now(ctx.sync_svc.files_to_fetch())
    return [CollectionFilesResponse(**vars(c)) for c in ctx.sync_svc.collection_files()]


@router.post("/files/{collection}/free-up", response_model=FreeUpResponse)
def free_up(
    collection: str,
    dry_run: bool = Query(default=True, description="Only count (the default)."),
    ctx: AppContext = Depends(get_ctx),
):
    """Remove this computer's copies of a collection's files to free space;
    they are fetched again when opened. Only files the server confirms it
    holds, and never one a collection kept here also uses. Counts first unless
    `dry_run=false`, which also sets the collection to fetch when opened."""
    try:
        report = ctx.sync_svc.free_up(collection, dry_run=dry_run)
    except SyncError as e:
        raise HTTPException(503, detail=f"The server can't be reached to check: {e}")
    ctx.commit()
    return FreeUpResponse(**vars(report), done=not dry_run)
