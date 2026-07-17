from __future__ import annotations

import csv
import io
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from civex.context import AppContext
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.server.background import run_pending_jobs
from civex.server.deps import get_ctx
from civex.server.models import (
    CreateRecordRequest,
    PaginatedRecordResponse,
    RecordResponse,
    UpdateRecordRequest,
)

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
    where: list[str] = Query(default=[]),
    limit: int = Query(default=50, le=1000),
    offset: int = Query(default=0, ge=0),
    ctx: AppContext = Depends(get_ctx),
):
    try:
        items = ctx.record_svc.find(
            dataset_name,
            schema_name=schema,
            parent_record_id=parent_record_id or None,
            filters=where,
            search=search or None,
            limit=limit,
            offset=offset,
        )
        total = ctx.record_svc.count(
            dataset_name,
            schema_name=schema,
            parent_record_id=parent_record_id or None,
            filters=where,
            search=search or None,
        )
    except (NotFoundError, ValueError) as e:
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


@router.get("/records/{record_id}", response_model=RecordResponse)
def get_record(record_id: str, ctx: AppContext = Depends(get_ctx)):
    try:
        return RecordResponse.from_dto(ctx.record_svc.get(record_id))
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))


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
    ctx.commit()
    background_tasks.add_task(run_pending_jobs)
    return RecordResponse.from_dto(dto)


@router.delete("/records/{record_id}", status_code=204)
def delete_record(record_id: str, ctx: AppContext = Depends(get_ctx)):
    try:
        ctx.record_svc.delete(record_id)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    ctx.commit()


@router.post("/records/bulk-delete")
def bulk_delete_records(
    ids: list[str] = Body(..., embed=True),
    ctx: AppContext = Depends(get_ctx),
):
    deleted = ctx.record_svc.delete_many(ids)
    ctx.commit()
    return {"deleted": deleted}


@router.delete("/collections/{dataset_name}/records")
def delete_all_records(
    dataset_name: str,
    schema: Optional[str] = Query(default=None),
    ctx: AppContext = Depends(get_ctx),
):
    try:
        deleted = ctx.record_svc.delete_all(dataset_name, schema_name=schema or None)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    ctx.commit()
    return {"deleted": deleted}


@router.get("/collections/{collection_name}/export.csv")
def export_records_csv(
    collection_name: str,
    ctx: AppContext = Depends(get_ctx),
):
    """Export all records in a collection as a CSV file."""
    try:
        records = ctx.record_svc.find(collection_name, limit=100_000)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))

    # Gather unique field names in encounter order across all records
    field_names: list[str] = []
    seen: set[str] = set()
    for r in records:
        for k in r.data:
            if k not in seen:
                seen.add(k)
                field_names.append(k)

    columns = ["id", "schema", "created_at", "updated_at"] + field_names

    def generate():
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        yield buf.getvalue()
        for r in records:
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
            row: dict = {
                "id": str(r.id),
                "schema": r.schema_name,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for k, v in r.data.items():
                row[k] = v if not isinstance(v, (list, dict)) else str(v)
            writer.writerow(row)
            yield buf.getvalue()

    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{collection_name}.csv"'
        },
    )
