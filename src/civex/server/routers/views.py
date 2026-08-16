from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from civex.context import AppContext
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError
from civex.server.deps import get_ctx
from civex.server.models import CreateViewRequest, UpdateViewRequest, ViewResponse

router = APIRouter(prefix="/schemas/{schema_name}/views", tags=["views"])


@router.get("", response_model=list[ViewResponse])
def list_views(schema_name: str, ctx: AppContext = Depends(get_ctx)):
    try:
        return [ViewResponse.from_dto(v) for v in ctx.view_svc.list_all(schema_name)]
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))


@router.post("", response_model=ViewResponse, status_code=201)
def create_view(
    schema_name: str, body: CreateViewRequest, ctx: AppContext = Depends(get_ctx)
):
    """Create a saved column/filter/sort view against a schema's own fields,
    with columns optionally joining one hop through a reference field."""
    try:
        dto = ctx.view_svc.create(
            schema_name,
            body.name,
            columns=body.columns,
            filter_tree=body.filter_tree,
            sort=body.sort,
        )
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except AlreadyExistsError as e:
        raise HTTPException(409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    return ViewResponse.from_dto(dto)


@router.get("/{view_name}", response_model=ViewResponse)
def get_view(schema_name: str, view_name: str, ctx: AppContext = Depends(get_ctx)):
    try:
        return ViewResponse.from_dto(ctx.view_svc.get(schema_name, view_name))
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))


@router.patch("/{view_name}", response_model=ViewResponse)
def update_view(
    schema_name: str,
    view_name: str,
    body: UpdateViewRequest,
    ctx: AppContext = Depends(get_ctx),
):
    # Present-but-null vs. absent matters here: an absent key means "leave
    # unchanged", an explicit null clears filter_tree (columns/sort keep
    # their prior value instead, since [] already means "no columns").
    columns = body.columns if "columns" in body.model_fields_set else ...
    filter_tree = body.filter_tree if "filter_tree" in body.model_fields_set else ...
    sort = body.sort if "sort" in body.model_fields_set else ...
    try:
        dto = ctx.view_svc.update(
            schema_name,
            view_name,
            new_name=body.rename,
            columns=columns,
            filter_tree=filter_tree,
            sort=sort,
        )
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except AlreadyExistsError as e:
        raise HTTPException(409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    return ViewResponse.from_dto(dto)


@router.delete("/{view_name}", status_code=204)
def delete_view(schema_name: str, view_name: str, ctx: AppContext = Depends(get_ctx)):
    try:
        ctx.view_svc.delete(schema_name, view_name)
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
