from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from civex.context import AppContext
from civex.domain.audit_filters import AUDIT_FIELDS
from civex.domain.dtos import BatchRevertDTO
from civex.domain.exceptions import ValidationError
from civex.domain.permissions import MANAGE_MEMBERS
from civex.domain.sync import SyncError
from civex.server.deps import allows, get_ctx, reads_whole_project
from civex.server.models import (
    BatchRevertRequest,
    BatchRevertResponse,
    AuditBatchResponse,
    AuditEventResponse,
    AuditLogResponse,
    EarlierAuditResponse,
    OpenBatchRequest,
    PaginatedAuditEventsResponse,
    PaginatedAuditLogResponse,
    RestoreAllPlanResponse,
    RestoreAllRequest,
    RestoreAllResultResponse,
    RevertPlanResponse,
    RunFieldResponse,
    RevertRequest,
    RevertResultResponse,
)

router = APIRouter(tags=["audit"])


class AuditView:
    """What a history table can ask for: one kind of action, an order, and how
    far back. Taken as a dependency by every audit endpoint."""

    def __init__(
        self,
        action: str | None = Query(
            default=None,
            description="Only entries of this action (create, update, ...).",
        ),
        sort: str | None = Query(
            default=None,
            description="'timestamp' or 'action', optionally ':asc' / ':desc'. "
            "Newest first by default.",
        ),
        since: datetime | None = Query(
            default=None,
            description="Only entries at or after this time (ISO 8601; a time "
            "with no zone is read as UTC).",
        ),
    ) -> None:
        self.action = action
        self.sort = sort
        self.since = (
            since
            if since is None or since.tzinfo
            else since.replace(tzinfo=timezone.utc)
        )


def audit_page(
    ctx: AppContext, view: AuditView, offset: int, limit: int, **scope
) -> PaginatedAuditLogResponse:
    """One page of audit entries for `scope` (entity_id / entity_type /
    entity_ids). Every audit endpoint answers through this."""
    items = ctx.history_svc.page(
        offset=offset,
        limit=limit,
        action=view.action,
        sort=view.sort,
        since=view.since,
        **scope,
    )
    return PaginatedAuditLogResponse(
        items=[AuditLogResponse.from_dto(a) for a in items],
        total=ctx.history_svc.count(action=view.action, since=view.since, **scope),
        offset=offset,
        limit=limit,
    )


@router.get("/audit", response_model=PaginatedAuditLogResponse)
def list_audit(
    entity_type: str | None = Query(
        default=None,
        description="Filter to one entity type: record, schema, field, dataset, view.",
    ),
    entity_id: str | None = Query(
        default=None, description="Filter to a single entity's audit trail."
    ),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=1000),
    view: AuditView = Depends(),
    ctx: AppContext = Depends(get_ctx),
):
    """General-purpose audit search, filterable by entity type and/or id.
    Prefer `/records/{id}/audit` or `/schemas/{name}/audit` when scoping to a
    single known resource — this endpoint is for cross-entity queries."""
    try:
        uid = uuid.UUID(entity_id) if entity_id else None
    except ValueError:
        raise HTTPException(400, detail="Invalid entity ID")
    return audit_page(ctx, view, offset, limit, entity_id=uid, entity_type=entity_type)


@router.get("/audit/filter-fields", response_model=list[RunFieldResponse])
def audit_filter_fields(ctx: AppContext = Depends(get_ctx)):
    """The fields a history filter may test, with their types and operators."""
    return [
        RunFieldResponse(
            name=f.name,
            label=f.label,
            type=f.type,
            description=f.description,
            choices=f.choices,
            operators=f.operators,
        )
        for f in AUDIT_FIELDS
    ]


@router.get("/audit/events", response_model=PaginatedAuditEventsResponse)
def list_audit_events(
    filter: str | None = Query(
        default=None,
        description='A filter tree as JSON (`{"and": [{"field": "kind", "op": '
        '"eq", "value": "record"}]}`), the same kind records and runs take. '
        "Fields come from GET /audit/filter-fields.",
    ),
    q: str | None = Query(
        default=None,
        description="Text to find in what a change stored (a value, a file's "
        "name) or in a batch's label (a workflow's name, an imported file).",
    ),
    sort: str | None = Query(
        default=None,
        description="`timestamp:asc` for oldest first; newest first by default.",
    ),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=200),
    ctx: AppContext = Depends(get_ctx),
):
    """The whole project's history as events, newest first. A batch (an import,
    a delete that took a tree with it, a workflow run) is one event however
    many changes it holds, with a count of what it did; any other change is an
    event of its own, with its field-level `changes` and where the record is
    `now`. The filter and `q` match changes; an event is listed when any of its
    changes match, with how many did."""
    found, total = ctx.history_svc.events(
        where=filter,
        search=q,
        offset=offset,
        limit=limit,
        newest_first=sort != "timestamp:asc",
    )
    return PaginatedAuditEventsResponse(
        items=[AuditEventResponse.from_dto(e) for e in found],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/audit/earlier", response_model=EarlierAuditResponse)
def earlier_audit(
    before: int | None = Query(
        default=None,
        ge=1,
        description="The previous page's `next_before`; omit for the newest of "
        "the earlier history.",
    ),
    limit: int = Query(default=25, ge=1, le=200),
    under: str | None = Query(
        default=None, description="Only what happened to this record and beneath it."
    ),
    ctx: AppContext = Depends(get_ctx),
):
    """History from before this project was copied from its server: read from
    the server now, a page at a time, and not stored here (nothing is
    downloaded in advance, so the cost follows what is looked at). Only what
    this device may read comes back. Offline, `offline` is true and nothing is
    read."""
    try:
        page = ctx.sync_svc.earlier(before, limit)
    except SyncError:
        return EarlierAuditResponse(items=[], next_before=before, offline=True)
    return EarlierAuditResponse(
        items=[
            AuditEventResponse.from_dto(e)
            for e in ctx.history_svc.events_of_entries(page.entries, under)
        ],
        next_before=page.next_before,
    )


@router.get("/audit/restore-all", response_model=RestoreAllPlanResponse)
def plan_restore_all(
    filter: str | None = Query(
        default=None, description="The history filter, as for `/audit/events`."
    ),
    q: str | None = Query(default=None),
    batch: str | None = Query(
        default=None,
        description="Only what this batch deleted: the id of a bulk delete's "
        "event in `/audit/events`, to undo it whole.",
    ),
    ctx: AppContext = Depends(get_ctx),
):
    """What restoring everything deleted that this filter matches would do,
    without doing it: how many collections, schemas, fields and records, how
    many records come back in all, and how many are blocked because something
    above them is deleted and not in the set."""
    try:
        return RestoreAllPlanResponse.from_dto(
            ctx.history_svc.plan_restore_all(filter, q, batch)
        )
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))


@router.post("/audit/restore-all", response_model=RestoreAllResultResponse)
def restore_all(body: RestoreAllRequest, ctx: AppContext = Depends(get_ctx)):
    """Restore everything deleted that the filter matches, as one event in
    history: collections and schemas first, then records parent-first. A record
    left under something deleted that is not in the set stays deleted and is
    counted as blocked."""
    try:
        result = ctx.history_svc.restore_all(body.filter, body.q, body.batch)
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    ctx.commit()
    return RestoreAllResultResponse.from_dto(result)


@router.post("/audit/batches", response_model=AuditBatchResponse, status_code=201)
def open_audit_batch(body: OpenBatchRequest, ctx: AppContext = Depends(get_ctx)):
    """Start a batch for work done over many requests, such as an import. Send
    its id in an `X-Civex-Batch` header on each of them and what they change is
    one event in history."""
    batch = ctx.audit_svc.open_batch(body.kind, body.label)
    ctx.commit()
    return AuditBatchResponse.from_dto(batch)


@router.get("/audit/batches/{batch_id}", response_model=AuditEventResponse)
def get_audit_batch(batch_id: str, ctx: AppContext = Depends(get_ctx)):
    """One batch as an event, with everything in it counted by kind and action."""
    return AuditEventResponse.from_dto(ctx.history_svc.batch_event(_audit_id(batch_id)))


@router.get(
    "/audit/batches/{batch_id}/entries", response_model=PaginatedAuditLogResponse
)
def list_audit_batch_entries(
    batch_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=1000),
    view: AuditView = Depends(),
    ctx: AppContext = Depends(get_ctx),
):
    """The changes in one batch, with their field-level `changes`."""
    return audit_page(ctx, view, offset, limit, batch_id=_audit_id(batch_id))


@router.get("/audit/batches/{batch_id}/revert", response_model=BatchRevertResponse)
def plan_batch_revert(
    batch_id: str,
    force: bool = Query(
        default=False, description="Count fields edited since as undone too."
    ),
    ctx: AppContext = Depends(get_ctx),
):
    """Preview undoing a whole bulk edit without changing anything: how many of
    its changes would be undone, how many met a later edit, and which can't be
    undone and why. Each change is judged as a single revert would judge it."""
    plan = ctx.history_svc.revert_batch(_audit_id(batch_id), force=force)
    return BatchRevertResponse(**plan.to_dict())


@router.post("/audit/batches/{batch_id}/revert", response_model=BatchRevertResponse)
def revert_audit_batch(
    batch_id: str,
    body: BatchRevertRequest | None = None,
    ctx: AppContext = Depends(get_ctx),
):
    """Undo a whole bulk edit: every change in it goes back through the normal
    record update, as one new event in history (which can itself be undone).
    Changes that can't be undone are left and reported."""
    body = body or BatchRevertRequest()
    result = BatchRevertDTO(_audit_id(batch_id))
    with ctx.chunked_writes() as turn:
        for result in ctx.history_svc.revert_batch_chunks(
            result.batch_id, force=body.force, dry_run=False
        ):
            turn()
    ctx.commit()
    return BatchRevertResponse(**result.to_dict())


def _audit_id(audit_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(audit_id)
    except ValueError:
        raise HTTPException(400, detail="Invalid history entry ID")


# -- how history is stored ------------------------------------------------------


class ReclaimTable(BaseModel):
    name: str
    size_bytes: int
    free_bytes: int


class HistoryStorageResponse(BaseModel):
    whole_entries: int = Field(
        description="Edits still stored as two whole copies (written before "
        "history stored only what changed); converted in the background."
    )
    converting: bool = Field(description="The conversion is running now.")
    done: int | None = Field(
        default=None, description="Entries looked at since the conversion began."
    )
    total: int | None = Field(
        default=None, description="What was left when the conversion began."
    )
    size_bytes: int | None = Field(
        default=None,
        description="The database's size: the file (SQLite) or the project's "
        "tables with their indexes (PostgreSQL).",
    )
    free_bytes: int | None = Field(
        default=None,
        description="Room inside the file no longer used: what reclaiming gives "
        "back. Reclaiming needs about `size_bytes` of free disk while it runs.",
    )
    estimate: bool = Field(
        default=False,
        description="`free_bytes` is an estimate from the catalogs (PostgreSQL).",
    )
    reclaim_tables: list[ReclaimTable] | None = Field(
        default=None,
        description="PostgreSQL: the tables a reclaim would rewrite, each locked "
        "while it runs. Null on SQLite, which rewrites the whole file.",
    )
    can_reclaim: bool = Field(
        default=True, description="False where the host doesn't offer a reclaim."
    )
    reclaim_skipped: list[str] = Field(
        default_factory=list,
        description="After a reclaim: tables left for later because another "
        "session held a lock on them.",
    )


def _storage(
    ctx: AppContext, skipped: list[str] | None = None
) -> HistoryStorageResponse:
    from civex.services.history_jobs import history_jobs

    space = ctx.compaction_svc.space()
    progress = history_jobs.progress
    return HistoryStorageResponse(
        whole_entries=ctx.compaction_svc.remaining(),
        converting=history_jobs.running and progress is not None,
        done=progress.done if progress else None,
        total=progress.total if progress else None,
        size_bytes=space.size_bytes if space else None,
        free_bytes=space.free_bytes if space else None,
        estimate=space.estimate if space else False,
        reclaim_tables=[
            ReclaimTable(name=t.name, size_bytes=t.size_bytes, free_bytes=t.free_bytes)
            for t in space.tables
        ]
        if space and space.estimate
        else None,
        can_reclaim=space.can_reclaim if space else True,
        reclaim_skipped=skipped or [],
    )


@router.get(
    "/audit/storage",
    response_model=HistoryStorageResponse,
    dependencies=[reads_whole_project()],
)
def history_storage(ctx: AppContext = Depends(get_ctx)):
    """How history is stored: edits still to convert to what-changed form, how
    far the background conversion has got, and the room a reclaim would give
    back."""
    return _storage(ctx)


@router.post(
    "/audit/storage/reclaim",
    response_model=HistoryStorageResponse,
    dependencies=[reads_whole_project(), allows(MANAGE_MEMBERS)],
)
def reclaim_history_storage(ctx: AppContext = Depends(get_ctx)):
    """Give unused room back to the disk: SQLite's VACUUM, or PostgreSQL's
    VACUUM FULL of the tables that are mostly empty (a host without `DB_ADMIN`
    refuses). Refused while history is being converted. The project waits."""
    from civex.services.history_jobs import history_jobs

    if history_jobs.running:
        raise HTTPException(
            409, detail="History is still being converted; reclaim once it is done"
        )
    ctx.commit()  # nothing of this request may be open while the file is rewritten
    skipped = ctx.compaction_svc.reclaim()
    return _storage(ctx, skipped)


@router.get("/audit/{audit_id}", response_model=AuditLogResponse)
def get_audit_entry(audit_id: str, ctx: AppContext = Depends(get_ctx)):
    """One history entry, with the `changes` it made worked out field by field."""
    return AuditLogResponse.from_dto(ctx.history_svc.get(_audit_id(audit_id)))


@router.get("/audit/{audit_id}/revert", response_model=RevertPlanResponse)
def plan_revert(
    audit_id: str,
    fields: list[str] | None = Query(
        default=None, description="Only plan these fields (repeat the parameter)."
    ),
    ctx: AppContext = Depends(get_ctx),
):
    """Preview undoing a history entry without changing anything: which fields
    would be put back, which were edited since (conflicts), and which cannot be
    put back. `blocked` says why when nothing can be undone at all."""
    plan = ctx.history_svc.plan_revert(_audit_id(audit_id), fields)
    return RevertPlanResponse.from_dto(plan)


@router.post("/audit/{audit_id}/revert", response_model=RevertResultResponse)
def revert_audit_entry(
    audit_id: str,
    body: RevertRequest | None = None,
    ctx: AppContext = Depends(get_ctx),
):
    """Undo a history entry on a record: an update puts the changed fields back,
    a delete restores the record, a create deletes it. Goes through the normal
    record update, so the same rules apply and the revert is itself recorded
    (and can be reverted). Fields edited since the entry are left alone unless
    `force` is set."""
    body = body or RevertRequest()
    result = ctx.history_svc.revert(
        _audit_id(audit_id), fields=body.fields, force=body.force
    )
    ctx.commit()
    return RevertResultResponse(**result.to_dict())


@router.get("/records/{record_id}/audit", response_model=PaginatedAuditLogResponse)
def list_record_audit(
    record_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=1000),
    view: AuditView = Depends(),
    ctx: AppContext = Depends(get_ctx),
):
    """Audit entries for a single record — every create/update/delete recorded
    against it, most recent first."""
    return audit_page(
        ctx, view, offset, limit, **ctx.history_svc.scope_of("record", record_id)
    )


@router.get("/schemas/{name}/audit", response_model=PaginatedAuditLogResponse)
def list_schema_audit(
    name: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=1000),
    view: AuditView = Depends(),
    ctx: AppContext = Depends(get_ctx),
):
    """Audit entries for a schema and its own fields (not inherited ones),
    most recent first — schema/field renames, field additions and removals,
    restriction changes, and so on."""
    return audit_page(
        ctx, view, offset, limit, **ctx.history_svc.scope_of("schema", name)
    )
