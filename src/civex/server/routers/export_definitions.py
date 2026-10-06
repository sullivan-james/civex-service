"""Exports saved with a schema: define them here, run them from a collection or a
record (see /file-access)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from civex.context import AppContext
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError
from civex.server.deps import get_ctx
from civex.server.models import (
    CreateExportDefinitionRequest,
    ExportDefinitionResponse,
    UpdateExportDefinitionRequest,
)

router = APIRouter(prefix="/schemas/{schema_name}/exports", tags=["exports"])


@router.get("", response_model=list[ExportDefinitionResponse])
def list_exports(schema_name: str, ctx: AppContext = Depends(get_ctx)):
    """The exports saved with a schema."""
    try:
        return [
            ExportDefinitionResponse.from_dto(d)
            for d in ctx.export_def_svc.list_for(schema_name)
        ]
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))


@router.post("", response_model=ExportDefinitionResponse, status_code=201)
def create_export(
    schema_name: str,
    body: CreateExportDefinitionRequest,
    ctx: AppContext = Depends(get_ctx),
):
    """Save an export with a schema: the kind of record that holds the files, which
    file fields, an optional filter, and a layout. It is then offered on
    collections that use the schema and on records of it and of the schemas below
    it, down to the kind that holds the files. Checked as a whole: the holder must
    be the schema or beneath it, and the fields must be file fields it has."""
    try:
        dto = ctx.export_def_svc.create(
            schema_name,
            body.name,
            holder=body.holder,
            fields=body.fields,
            filter_tree=body.filter_tree,
            files_layout=body.files_layout,
            include_files=body.include_files,
            tables=[t.model_dump() for t in body.tables],
        )
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except AlreadyExistsError as e:
        raise HTTPException(409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    return ExportDefinitionResponse.from_dto(dto)


@router.get("/{export_name}", response_model=ExportDefinitionResponse)
def get_export(schema_name: str, export_name: str, ctx: AppContext = Depends(get_ctx)):
    """One saved export."""
    try:
        return ExportDefinitionResponse.from_dto(
            ctx.export_def_svc.get(schema_name, export_name)
        )
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))


@router.patch("/{export_name}", response_model=ExportDefinitionResponse)
def update_export(
    schema_name: str,
    export_name: str,
    body: UpdateExportDefinitionRequest,
    ctx: AppContext = Depends(get_ctx),
):
    """Change a saved export. A key left out is left alone; `holder` and
    `filter_tree` may be sent as null to clear them. The result is checked as a
    whole."""
    sent = body.model_fields_set
    try:
        dto = ctx.export_def_svc.update(
            schema_name,
            export_name,
            new_name=body.rename,
            holder=body.holder if "holder" in sent else ...,
            fields=body.fields if body.fields is not None else ...,
            filter_tree=body.filter_tree if "filter_tree" in sent else ...,
            files_layout=body.files_layout if body.files_layout else ...,
            include_files=(
                body.include_files if body.include_files is not None else ...
            ),
            tables=(
                [t.model_dump() for t in body.tables]
                if body.tables is not None
                else ...
            ),
        )
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except AlreadyExistsError as e:
        raise HTTPException(409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    return ExportDefinitionResponse.from_dto(dto)


@router.delete("/{export_name}", status_code=204)
def delete_export(
    schema_name: str, export_name: str, ctx: AppContext = Depends(get_ctx)
):
    """Delete a saved export. Folders it already made are left (they are listed
    under /file-access/exports)."""
    try:
        ctx.export_def_svc.delete(schema_name, export_name)
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
