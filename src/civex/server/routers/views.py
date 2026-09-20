from __future__ import annotations

import io
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from civex.context import AppContext
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError
from civex.server.deps import get_ctx
from civex.server.models import (
    CreateViewRequest,
    PreviewViewRequest,
    PreviewViewResponse,
    UpdateViewRequest,
    ViewResponse,
)
from civex.services.view_service import rows_to_csv, rows_to_json
from civex.sync.transport import SyncError

router = APIRouter(prefix="/schemas/{schema_name}/views", tags=["views"])
all_views_router = APIRouter(prefix="/views", tags=["views"])


@all_views_router.get("", response_model=list[ViewResponse])
def list_all_views(ctx: AppContext = Depends(get_ctx)):
    """Every saved view across every schema, sorted by schema then view
    name -- backs the top-level Views index page."""
    return [ViewResponse.from_dto(v) for v in ctx.view_svc.list_across_schemas()]


@router.get("", response_model=list[ViewResponse])
def list_views(schema_name: str, ctx: AppContext = Depends(get_ctx)):
    """Saved views for a single schema."""
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


@router.post("/preview", response_model=PreviewViewResponse)
def preview_view(
    schema_name: str, body: PreviewViewRequest, ctx: AppContext = Depends(get_ctx)
):
    """Rows + total count for a column/filter/sort selection without saving
    it as a view -- backs the view builder's live preview."""
    try:
        rows, total = ctx.view_svc.preview(
            schema_name,
            columns=body.columns,
            filter_tree=body.filter_tree,
            sort=body.sort,
            limit=body.limit,
            offset=body.offset,
        )
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    return PreviewViewResponse(rows=rows, total=total)


@router.get("/{view_name}", response_model=ViewResponse)
def get_view(schema_name: str, view_name: str, ctx: AppContext = Depends(get_ctx)):
    """A single saved view by name."""
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
    """Rename a view and/or replace its columns/filter_tree/sort."""
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
    """Delete a saved view. Does not affect the underlying records."""
    try:
        ctx.view_svc.delete(schema_name, view_name)
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))


@router.get("/{view_name}/export")
def export_view(
    schema_name: str,
    view_name: str,
    format: str = Query(default="csv", pattern="^(csv|json)$"),
    ctx: AppContext = Depends(get_ctx),
):
    """Export a view's rows as CSV or JSON, honoring its saved filter/sort
    and flattening `columns` (CSV headers use the dotted
    "ref_field.target_field" join convention; JSON nests joined columns
    instead). Any file/file_list column gets bundled into a zip alongside
    the CSV/JSON, reusing the same resolved-filename + collision-suffix
    logic as the per-record files.zip export."""
    try:
        export = ctx.view_svc.export(schema_name, view_name)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))

    if format == "csv":
        body = rows_to_csv(export.view.columns, export.rows).encode("utf-8")
        data_filename, media_type = f"{view_name}.csv", "text/csv"
    else:
        body = rows_to_json(export.rows).encode("utf-8")
        data_filename, media_type = f"{view_name}.json", "application/json"

    if not export.file_entries:
        return Response(
            content=body,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{data_filename}"'},
        )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(data_filename, body)
        for name, ref in export.file_entries:
            try:
                data = ctx.file_svc.retrieve(ref.sha256)
            except (FileNotFoundError, SyncError):
                raise HTTPException(
                    404, detail=f"Object {ref.sha256} not found locally or on remote"
                )
            zf.writestr(name, data)

    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{view_name}.zip"'},
    )
