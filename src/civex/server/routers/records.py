from __future__ import annotations

import csv
import json
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query

from civex.context import AppContext
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.server.background import run_pending_jobs
from civex.server.deps import get_ctx
from civex.server.downloads import new_temp_path, serve, temp_paths
from civex.server.models import (
    CreateRecordRequest,
    PaginatedRecordResponse,
    RecordResponse,
    UpdateRecordRequest,
)
from civex.services.archive import write_zip
from civex.sync.transport import SyncError

router = APIRouter(tags=["records"])


@router.get("/records", response_model=list[RecordResponse])
def search_records_global(
    schema: str = Query(..., description="Schema name to search within"),
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=20, le=100),
    ctx: AppContext = Depends(get_ctx),
):
    try:
        items = ctx.record_svc.find_by_schema(
            schema, search=search or None, limit=limit
        )
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    return [RecordResponse.from_dto(r) for r in items]


@router.get(
    "/collections/{dataset_name}/records", response_model=PaginatedRecordResponse
)
def list_records(
    dataset_name: str,
    schema: Optional[str] = Query(default=None),
    parent_record_id: Optional[str] = Query(default=None),
    search: Optional[str] = Query(
        default=None, description="Full-text search across all field values"
    ),
    where: list[str] = Query(
        default=[],
        description="Simple equality filter, repeatable: 'field=value'. "
        "AND-combined with each other and with 'filter'. Kept for backwards "
        "compatibility -- prefer 'filter' for anything beyond plain equality.",
    ),
    filter_: Optional[str] = Query(
        default=None,
        alias="filter",
        description="JSON-encoded filter tree, AND/OR groups of field "
        "conditions against the base schema's own fields (joined/reference "
        "fields aren't supported here). "
        'Leaf: {"field": "<name>", "op": "eq"|"ne"|"gt"|"gte"|'
        '"lt"|"lte"|"contains"|"in"|"is_null", "value": ...}. '
        'Group: {"and": [<node>, ...]} or {"or": [<node>, ...]}, nestable. '
        "'value' must be a list for 'in' and is optional (default true) for "
        "'is_null'. Example: "
        '{"and": [{"field": "status", "op": "eq", "value": "active"}, '
        '{"field": "age", "op": "gte", "value": 18}]}',
    ),
    limit: int = Query(default=50, le=1000),
    offset: int = Query(default=0, ge=0),
    ctx: AppContext = Depends(get_ctx),
):
    """List records in a collection, paginated and optionally filtered.

    'where' and 'filter' can be combined -- the equality checks from 'where'
    are AND-combined with the 'filter' tree, if both are given.
    """
    try:
        filter_tree = json.loads(filter_) if filter_ else None
    except json.JSONDecodeError as e:
        raise HTTPException(422, detail=f"Invalid 'filter' JSON: {e}")
    try:
        items = ctx.record_svc.find(
            dataset_name,
            schema_name=schema,
            parent_record_id=parent_record_id or None,
            filters=where,
            filter_tree=filter_tree,
            search=search or None,
            limit=limit,
            offset=offset,
        )
        total = ctx.record_svc.count(
            dataset_name,
            schema_name=schema,
            parent_record_id=parent_record_id or None,
            filters=where,
            filter_tree=filter_tree,
            search=search or None,
        )
    except (NotFoundError, ValueError, ValidationError) as e:
        raise HTTPException(404 if isinstance(e, NotFoundError) else 422, detail=str(e))
    return PaginatedRecordResponse(
        items=[RecordResponse.from_dto(r) for r in items],
        total=total,
        offset=offset,
        limit=limit,
    )


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


@router.get("/records/{record_id}", response_model=RecordResponse)
def get_record(record_id: str, ctx: AppContext = Depends(get_ctx)):
    try:
        return RecordResponse.from_dto(ctx.record_svc.get(record_id))
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))


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
        except (FileNotFoundError, SyncError) as e:
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


@router.post("/records/{record_id}/restore", response_model=RecordResponse)
def restore_record(record_id: str, ctx: AppContext = Depends(get_ctx)):
    try:
        dto = ctx.record_svc.restore(record_id)
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    return RecordResponse.from_dto(dto)


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
    schema: Optional[str] = Query(default=None),
    force: bool = Query(default=False),
    ctx: AppContext = Depends(get_ctx),
):
    try:
        deleted = ctx.record_svc.delete_all(
            dataset_name, schema_name=schema or None, force=force
        )
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    ctx.commit()
    return {"deleted": deleted}


@router.get("/collections/{collection_name}/export.csv")
def export_records_csv(
    collection_name: str,
    schema: Optional[str] = Query(default=None),
    search: Optional[str] = Query(
        default=None, description="Full-text search across all field values"
    ),
    where: list[str] = Query(default=[]),
    ctx: AppContext = Depends(get_ctx),
):
    """Export records in a collection as a CSV file, honoring the same
    schema/where/search filters as the record list endpoint."""

    def pages():
        return ctx.record_svc.iter_find(
            collection_name, schema_name=schema, filters=where, search=search or None
        )

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
    except ValueError as e:
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
                        row[k] = v if not isinstance(v, (list, dict)) else str(v)
                    writer.writerow(row)
        tmp.remove(path)
        return serve(path, "text/csv", f"{collection_name}.csv")
