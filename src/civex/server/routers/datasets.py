from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from civex.context import AppContext
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError
from civex.server.deps import get_ctx
from civex.server.models import (
    AuditLogResponse,
    CreateDatasetRequest,
    DatasetResponse,
    PaginatedAuditLogResponse,
    UpdateDatasetRequest,
)

router = APIRouter(prefix="/collections", tags=["collections"])


@router.get("", response_model=list[DatasetResponse])
def list_datasets(ctx: AppContext = Depends(get_ctx)):
    return [DatasetResponse.from_dto(d) for d in ctx.dataset_svc.list_all()]


@router.get("/deleted", response_model=list[DatasetResponse])
def list_deleted_datasets(ctx: AppContext = Depends(get_ctx)):
    """Collections currently in Recently Deleted, most recently deleted first."""
    return [DatasetResponse.from_dto(d) for d in ctx.dataset_svc.list_deleted()]


@router.post("", response_model=DatasetResponse, status_code=201)
def create_dataset(body: CreateDatasetRequest, ctx: AppContext = Depends(get_ctx)):
    try:
        dto = ctx.dataset_svc.create(body.name, description=body.description)
    except AlreadyExistsError as e:
        raise HTTPException(409, detail=str(e))
    return DatasetResponse.from_dto(dto)


@router.get("/{name_or_id}", response_model=DatasetResponse)
def get_dataset(name_or_id: str, ctx: AppContext = Depends(get_ctx)):
    try:
        uid = uuid.UUID(name_or_id)
        dto = ctx.dataset_svc._datasets.get_by_id(uid)
        if dto:
            return DatasetResponse.from_dto(dto)
    except ValueError:
        pass
    try:
        return DatasetResponse.from_dto(ctx.dataset_svc.get(name_or_id))
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))


@router.get("/{name_or_id}/record-counts")
def record_counts(name_or_id: str, ctx: AppContext = Depends(get_ctx)):
    """Record counts grouped by schema name — single SQL GROUP BY, no record loading."""
    dataset = None
    try:
        uid = uuid.UUID(name_or_id)
        dataset = ctx.dataset_svc._datasets.get_by_id(uid)
    except ValueError:
        pass
    if dataset is None:
        try:
            dataset = ctx.dataset_svc.get(name_or_id)
        except NotFoundError as e:
            raise HTTPException(404, detail=str(e))
    return ctx.record_svc.schema_counts(dataset.name)


@router.get("/{name_or_id}/audit", response_model=PaginatedAuditLogResponse)
def list_dataset_audit(
    name_or_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=1000),
    ctx: AppContext = Depends(get_ctx),
):
    """Audit entries for a collection — renames, description changes,
    delete/restore/purge — most recent first."""
    dataset = None
    try:
        uid = uuid.UUID(name_or_id)
        dataset = ctx.dataset_svc._datasets.get_by_id(uid)
    except ValueError:
        pass
    if dataset is None:
        try:
            dataset = ctx.dataset_svc.get(name_or_id)
        except NotFoundError as e:
            raise HTTPException(404, detail=str(e))
    items = ctx.audit_svc.list_audit(
        entity_id=dataset.id, entity_type="dataset", offset=offset, limit=limit
    )
    total = ctx.audit_svc.count_audit(entity_id=dataset.id, entity_type="dataset")
    return PaginatedAuditLogResponse(
        items=[AuditLogResponse.from_dto(a) for a in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.patch("/{name_or_id}", response_model=DatasetResponse)
def update_dataset(
    name_or_id: str, body: UpdateDatasetRequest, ctx: AppContext = Depends(get_ctx)
):
    # Resolve by UUID or name
    dataset = None
    try:
        uid = uuid.UUID(name_or_id)
        dataset = ctx.dataset_svc._datasets.get_by_id(uid)
    except ValueError:
        pass
    if dataset is None:
        try:
            dataset = ctx.dataset_svc.get(name_or_id)
        except NotFoundError as e:
            raise HTTPException(404, detail=str(e))
    try:
        updated = ctx.dataset_svc.update(
            dataset.name, new_name=body.rename, description=body.description
        )
        ctx.commit()
    except AlreadyExistsError as e:
        raise HTTPException(409, detail=str(e))
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    return DatasetResponse.from_dto(updated)


@router.delete("/{name}", status_code=204)
def delete_dataset(name: str, ctx: AppContext = Depends(get_ctx)):
    try:
        ctx.dataset_svc.delete(name)
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))


@router.post("/{name}/restore", response_model=DatasetResponse)
def restore_dataset(name: str, ctx: AppContext = Depends(get_ctx)):
    try:
        dto = ctx.dataset_svc.restore(name)
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    return DatasetResponse.from_dto(dto)


@router.delete("/{name}/purge", status_code=204)
def purge_dataset(name: str, ctx: AppContext = Depends(get_ctx)):
    try:
        ctx.dataset_svc.purge(name)
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
