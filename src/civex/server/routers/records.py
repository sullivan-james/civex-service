from __future__ import annotations

import csv
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query

from civex.context import AppContext
from civex.domain import geo as geo_domain
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.domain.query import RecordQuery
from civex.server.background import run_pending_jobs
from civex.server.deps import get_ctx
from civex.server.downloads import new_temp_path, serve, temp_paths
from civex.server.models import (
    CreateRecordRequest,
    PaginatedRecordResponse,
    RecordLabelResponse,
    RecordLabelsRequest,
    RestoreSelectedRequest,
    RestoreSelectedResponse,
    RecordRef,
    RecordResponse,
    RestorePlanResponse,
    ReferrerGroupResponse,
    UpdateRecordRequest,
)
from civex.server.query_params import record_query
from civex.services.archive import write_zip

router = APIRouter(tags=["records"])


@router.get("/records", response_model=list[RecordResponse])
def search_records_global(
    schema: str = Query(..., description="Schema name to search within"),
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=20, le=100),
    reachable_from: Optional[str] = Query(
        default=None,
        description="Collection name: only records a record in that "
        "collection may reference -- its own collection's and those of "
        "global collections. What a reference picker should pass.",
    ),
    ctx: AppContext = Depends(get_ctx),
):
    try:
        items = ctx.record_svc.find_by_schema(
            schema,
            search=search or None,
            limit=limit,
            reachable_from=reachable_from or None,
        )
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    return [RecordResponse.from_dto(r) for r in items]


@router.get("/records/search", response_model=list[RecordResponse])
def search_records(
    q: str = Query(
        ...,
        min_length=1,
        description="Text to find in a record's values, or the start of its id.",
    ),
    limit: int = Query(default=20, ge=1, le=100),
    collection: Optional[str] = Query(
        default=None,
        description="Collection name: only search records in it. Omitted, "
        "every collection is searched.",
    ),
    ctx: AppContext = Depends(get_ctx),
):
    """Search records of every schema in one query, best match first -- what
    the web UI's jump-to box uses. Each result's `collection` says where it
    lives. Records that are deleted, or in a deleted collection or schema,
    are never returned."""
    try:
        items = ctx.record_svc.search(q, limit=limit, collection=collection or None)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    return [RecordResponse.from_dto(r) for r in items]


def _page(
    ctx: AppContext,
    query: RecordQuery,
    columns: list[str],
    child_counts: bool,
    limit: int,
    offset: int,
) -> PaginatedRecordResponse:
    try:
        items = ctx.record_svc.query_records(
            query,
            limit=limit,
            offset=offset,
            columns=columns or None,
            child_counts=child_counts,
        )
        total = ctx.record_svc.count_records(query)
    except (NotFoundError, ValueError, ValidationError) as e:
        raise HTTPException(404 if isinstance(e, NotFoundError) else 422, detail=str(e))
    return PaginatedRecordResponse(
        items=[RecordResponse.from_dto(r) for r in items],
        total=total,
        offset=offset,
        limit=limit,
    )


_COLUMNS = Query(
    default=[],
    description="Repeatable column names whose values aren't in a record's "
    "own 'data' -- inherited fields and 'ref_field.target_field' joins -- "
    "returned under each record's 'derived'.",
)
_CHILD_COUNTS = Query(
    default=False,
    description="Attach each record's live child count per child schema.",
)


@router.get(
    "/collections/{dataset_name}/records", response_model=PaginatedRecordResponse
)
def list_records(
    dataset_name: str,
    query: RecordQuery = Depends(record_query),
    columns: list[str] = _COLUMNS,
    child_counts: bool = _CHILD_COUNTS,
    limit: int = Query(default=50, le=1000),
    offset: int = Query(default=0, ge=0),
    ctx: AppContext = Depends(get_ctx),
):
    """List records in a collection, paginated, filtered and sorted.

    'where' and 'filter' can be combined -- the equality checks from 'where'
    are AND-combined with the 'filter' tree, if both are given.
    """
    query.dataset = dataset_name
    return _page(ctx, query, columns, child_counts, limit, offset)


@router.get("/schemas/{schema_name}/records", response_model=PaginatedRecordResponse)
def list_schema_records(
    schema_name: str,
    query: RecordQuery = Depends(record_query),
    columns: list[str] = _COLUMNS,
    child_counts: bool = _CHILD_COUNTS,
    limit: int = Query(default=50, le=1000),
    offset: int = Query(default=0, ge=0),
    ctx: AppContext = Depends(get_ctx),
):
    """List a schema's records across every collection -- the same query as
    a collection's list, just not scoped to one collection (what a saved view
    browses)."""
    query.schema = schema_name
    return _page(ctx, query, columns, child_counts, limit, offset)


@router.post(
    "/collections/{dataset_name}/records",
    response_model=RecordResponse,
    status_code=201,
)
def create_record(
    dataset_name: str,
    body: CreateRecordRequest,
    background_tasks: BackgroundTasks,
    ctx: AppContext = Depends(get_ctx),
):
    try:
        dto = ctx.record_svc.add(
            dataset_name,
            body.schema_name,
            body.data,
            parent_record_id=body.parent_record_id,
        )
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    ctx.commit()
    background_tasks.add_task(run_pending_jobs)
    return RecordResponse.from_dto(dto)


@router.get("/records/deleted", response_model=list[RecordResponse])
def list_deleted_records(
    dataset: Optional[str] = Query(
        default=None, description="Limit to records from this collection"
    ),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    ctx: AppContext = Depends(get_ctx),
):
    """Records currently in Recently Deleted, most recently deleted first.
    Paginated: `limit` defaults to 200 and is capped at 1000."""
    try:
        items = ctx.record_svc.list_deleted(
            dataset_name=dataset or None, offset=offset, limit=limit
        )
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    return [RecordResponse.from_dto(r) for r in items]


@router.post("/records/labels", response_model=list[RecordLabelResponse])
def record_labels(body: RecordLabelsRequest, ctx: AppContext = Depends(get_ctx)):
    """Names for a batch of record ids, as they are now.

    Anywhere that kept only a record's id (a workflow run's records, a pinned
    record, a link) asks here for its name instead of keeping a copy that would
    go stale when the record or its schema's name template changes. One call
    resolves any number of ids (up to 200); ids that aren't records, or whose
    record no longer exists, are omitted. Read-only: it is a POST only so the
    ids travel in the body rather than a long address.
    """
    return [
        RecordLabelResponse(
            id=str(r.id),
            schema_name=r.schema_name,
            natural_name=r.natural_name,
            deleted=r.deleted_at is not None,
            deleted_at=r.deleted_at,
        )
        for r in ctx.record_svc.labels(body.ids)
    ]


@router.get("/records/{record_id}", response_model=RecordResponse)
def get_record(record_id: str, ctx: AppContext = Depends(get_ctx)):
    try:
        record = ctx.record_svc.get(record_id)
        ancestors = ctx.record_svc.ancestors(record)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    response = RecordResponse.from_dto(record)
    response.ancestors = [
        RecordRef(id=str(a.id), schema_name=a.schema_name, natural_name=a.natural_name)
        for a in ancestors
    ]
    return response


@router.get(
    "/records/{record_id}/referrers", response_model=list[ReferrerGroupResponse]
)
def get_record_referrers(record_id: str, ctx: AppContext = Depends(get_ctx)):
    """What points at this record: live records referencing it through a
    `reference` or `reference_list` field, counted per (collection, schema,
    field) -- the reverse of the record's own reference values."""
    try:
        groups = ctx.record_svc.referrer_counts(record_id)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    return [ReferrerGroupResponse.from_dto(g) for g in groups]


@router.get("/records/{record_id}/files.zip")
def export_record_files_zip(
    record_id: str,
    field: Optional[str] = Query(
        default=None,
        description="Limit the export to a single file/file_list field; omit for every file on the record",
    ),
    ctx: AppContext = Depends(get_ctx),
):
    """Bundle a record's files into a zip, one entry per file, named with the
    same `resolved_filename` used for single-file download. Entries that
    would collide (e.g. two files resolving to the same template output) get
    a numeric suffix rather than overwriting each other in the archive."""
    try:
        entries = ctx.record_svc.files_for_zip(record_id, field_name=field or None)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))

    zip_name = f"{record_id}-{field}.zip" if field else f"{record_id}-files.zip"
    with temp_paths() as tmp:
        zip_path = new_temp_path(".zip")
        tmp.append(zip_path)
        try:
            write_zip(zip_path, ctx.file_svc, entries)
        except FileNotFoundError as e:
            raise HTTPException(
                404, detail=f"Object not found locally or on remote: {e}"
            )
        tmp.remove(zip_path)
        return serve(zip_path, "application/zip", zip_name)


@router.patch("/records/{record_id}", response_model=RecordResponse)
def update_record(
    record_id: str,
    body: UpdateRecordRequest,
    background_tasks: BackgroundTasks,
    ctx: AppContext = Depends(get_ctx),
):
    try:
        dto = ctx.record_svc.update(record_id, body.data)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    ctx.commit()
    background_tasks.add_task(run_pending_jobs)
    return RecordResponse.from_dto(dto)


@router.delete("/records/{record_id}", status_code=204)
def delete_record(
    record_id: str,
    force: bool = Query(default=False),
    ctx: AppContext = Depends(get_ctx),
):
    try:
        ctx.record_svc.delete(record_id, force=force)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    ctx.commit()


@router.get("/records/{record_id}/restore-plan", response_model=RestorePlanResponse)
def restore_record_plan(record_id: str, ctx: AppContext = Depends(get_ctx)):
    """What restoring a deleted record would do, without doing it: how many
    records come back with it (those deleted together with it), the collection
    it will be in, and `blocked_by` when its collection, schema or a parent
    record is still deleted and must be restored first."""
    try:
        return RestorePlanResponse.from_dto(ctx.record_svc.restore_plan(record_id))
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))


@router.post("/records/{record_id}/restore", response_model=RecordResponse)
def restore_record(
    record_id: str,
    only_this: bool = Query(
        default=False,
        description="Restore just this record, not what was deleted alongside "
        "it (its children).",
    ),
    with_parents: bool = Query(
        default=False,
        description="When only deleted records above this one hold it back, "
        "restore them too, each by itself, so its deleted siblings stay "
        "deleted.",
    ),
    ctx: AppContext = Depends(get_ctx),
):
    """Restore a deleted record with what was deleted alongside it. Refused while
    its collection or schema is deleted, or a record above it is (unless
    `with_parents`)."""
    try:
        dto = ctx.record_svc.restore(
            record_id, only_this=only_this, with_parents=with_parents
        )
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    return RecordResponse.from_dto(dto)


@router.post("/records/restore-selected", response_model=RestoreSelectedResponse)
def restore_selected_records(
    body: RestoreSelectedRequest, ctx: AppContext = Depends(get_ctx)
):
    """Restore exactly these deleted records, not what was deleted alongside
    them: for taking back three of the sixty records one delete took. The
    deleted records above a chosen one come back too (each by itself) unless
    `with_parents` is false, in which case such a record is left."""
    result = ctx.record_svc.restore_records(body.ids, body.with_parents)
    ctx.commit()
    return RestoreSelectedResponse(
        restored=result.restored, came_back=result.came_back, left=len(result.left)
    )


@router.delete("/records/{record_id}/purge", status_code=204)
def purge_record(record_id: str, ctx: AppContext = Depends(get_ctx)):
    try:
        ctx.record_svc.purge(record_id)
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))


@router.post("/records/bulk-delete")
def bulk_delete_records(
    ids: list[str] = Body(..., embed=True),
    force: bool = Body(default=False, embed=True),
    ctx: AppContext = Depends(get_ctx),
):
    deleted = ctx.record_svc.delete_many(ids, force=force)
    ctx.commit()
    return {"deleted": deleted}


@router.delete("/collections/{dataset_name}/records")
def delete_all_records(
    dataset_name: str,
    query: RecordQuery = Depends(record_query),
    force: bool = Query(default=False),
    ctx: AppContext = Depends(get_ctx),
):
    """Delete every record the query matches -- with no filters, all of the
    collection's records (of 'schema', if given). The same filters as the
    list endpoint, so "delete all N matching" deletes exactly what a list
    with those filters shows."""
    query.dataset = dataset_name
    try:
        deleted = ctx.record_svc.delete_matching(query, force=force)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except (ValueError, ValidationError) as e:
        raise HTTPException(422, detail=str(e))
    ctx.commit()
    return {"deleted": deleted}


@router.get("/collections/{collection_name}/export.csv")
def export_records_csv(
    collection_name: str,
    query: RecordQuery = Depends(record_query),
    ctx: AppContext = Depends(get_ctx),
):
    """Export records in a collection as a CSV file, honoring the same
    filters as the record list endpoint."""
    query.dataset = collection_name

    def pages():
        return ctx.record_svc.stream_records(query)

    try:
        # First pass: only the set of column names is kept (in encounter
        # order), never the records themselves.
        field_names: list[str] = []
        seen: set[str] = set()
        for page in pages():
            for r in page:
                for k in r.data:
                    if k not in seen:
                        seen.add(k)
                        field_names.append(k)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except (ValueError, ValidationError) as e:
        raise HTTPException(422, detail=str(e))

    columns = ["id", "schema", "created_at", "updated_at"] + field_names

    # Second pass: rows go page by page into a temp file that is then served
    # from disk, so the export's size is bounded by disk, not memory.
    with temp_paths() as tmp:
        path = new_temp_path(".csv")
        tmp.append(path)
        with path.open("w", encoding="utf-8", newline="") as out:
            writer = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for page in pages():
                for r in page:
                    row: dict = {
                        "id": str(r.id),
                        "schema": r.schema_name,
                        "created_at": r.created_at.isoformat(),
                        "updated_at": r.updated_at.isoformat(),
                    }
                    for k, v in r.data.items():
                        if geo_domain.is_geometry(v):
                            row[k] = geo_domain.to_text(v)
                        else:
                            row[k] = v if not isinstance(v, (list, dict)) else str(v)
                    writer.writerow(row)
        tmp.remove(path)
        return serve(path, "text/csv", f"{collection_name}.csv")
