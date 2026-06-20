from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from civex.context import AppContext
from civex.domain.exceptions import AlreadyExistsError, NotFoundError
from civex.server.deps import get_ctx
from civex.server.models import (
    AddFieldRequest,
    CreateSchemaRequest,
    FieldResponse,
    SchemaResponse,
    UpdateFieldRequest,
    UpdateSchemaRequest,
)

router = APIRouter(prefix="/schemas", tags=["schemas"])


@router.get("", response_model=list[SchemaResponse])
def list_schemas(ctx: AppContext = Depends(get_ctx)):
    return [SchemaResponse.from_dto(s) for s in ctx.schema_svc.list_all()]


@router.post("", response_model=SchemaResponse, status_code=201)
def create_schema(body: CreateSchemaRequest, ctx: AppContext = Depends(get_ctx)):
    try:
        dto = ctx.schema_svc.create(body.name, description=body.description, parent=body.parent)
    except AlreadyExistsError as e:
        raise HTTPException(409, detail=str(e))
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    return SchemaResponse.from_dto(dto)


@router.get("/{name_or_id}", response_model=SchemaResponse)
def get_schema(name_or_id: str, ctx: AppContext = Depends(get_ctx)):
    try:
        uid = uuid.UUID(name_or_id)
        dto = ctx.schema_svc._repo.get_by_id(uid)
        if dto:
            return SchemaResponse.from_dto(dto)
    except ValueError:
        pass
    try:
        return SchemaResponse.from_dto(ctx.schema_svc.get(name_or_id))
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))


@router.patch("/{name}", response_model=SchemaResponse)
def update_schema(name: str, body: UpdateSchemaRequest, ctx: AppContext = Depends(get_ctx)):
    display_field = body.display_field if "display_field" in body.model_fields_set else ...
    try:
        dto = ctx.schema_svc.update(
            name,
            new_name=body.rename,
            description=body.description,
            display_field=display_field,
        )
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except AlreadyExistsError as e:
        raise HTTPException(409, detail=str(e))
    return SchemaResponse.from_dto(dto)


@router.delete("/{name}", status_code=204)
def delete_schema(name: str, ctx: AppContext = Depends(get_ctx)):
    try:
        ctx.schema_svc.delete(name)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))


@router.post("/{name}/fields", response_model=FieldResponse, status_code=201)
def add_field(name: str, body: AddFieldRequest, ctx: AppContext = Depends(get_ctx)):
    try:
        field = ctx.schema_svc.add_field(name, body.name, body.type, required=body.required, restrictions=body.restrictions)
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except (AlreadyExistsError, ValueError) as e:
        raise HTTPException(422, detail=str(e))
    return FieldResponse(id=str(field.id), name=field.name, type=field.dtype, required=field.required, restrictions=field.restrictions)


@router.delete("/{name}/fields/{field_name}", status_code=204)
def delete_field(name: str, field_name: str, ctx: AppContext = Depends(get_ctx)):
    try:
        ctx.schema_svc.delete_field(name, field_name)
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))


@router.patch("/{name}/fields/{field_name}", response_model=FieldResponse)
def update_field(name: str, field_name: str, body: UpdateFieldRequest, ctx: AppContext = Depends(get_ctx)):
    if body.rename is None and body.required is None and body.restrictions is None:
        raise HTTPException(422, detail="Provide at least one of: rename, required, restrictions")
    try:
        field = ctx.schema_svc.update_field(
            name, field_name,
            new_name=body.rename,
            required=body.required,
            restrictions=body.restrictions,
        )
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except AlreadyExistsError as e:
        raise HTTPException(409, detail=str(e))
    return FieldResponse(id=str(field.id), name=field.name, type=field.dtype, required=field.required, restrictions=field.restrictions)
