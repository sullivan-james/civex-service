from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from civex.context import AppContext
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError
from civex.server.deps import get_ctx
from civex.server.downloads import new_temp_dir, serve, temp_paths
from civex.server.models import (
    CreateViewRequest,
    PreviewViewRequest,
    PreviewViewResponse,
    UpdateViewRequest,
    ViewResponse,
)
from civex.services.archive import build_download
from civex.domain.naming import safe_filename

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
    with columns optionally joining one hop through a reference field.
    `files_layout` says how its files are arranged when it is exported as a
    folder or zip."""
    try:
        dto = ctx.view_svc.create(
            schema_name,
            body.name,
            columns=body.columns,
            filter_tree=body.filter_tree,
            sort=body.sort,
            files_layout=body.files_layout,
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
    """Rename a view and/or replace its columns/filter_tree/sort/files_layout."""
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
            files_layout=(body.files_layout if body.files_layout is not None else ...),
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
    format: str = Query(default="csv", pattern="^(csv|tsv|xlsx|json|jsonl)$"),
    ctx: AppContext = Depends(get_ctx),
):
    """Export a view's rows as csv, tsv, xlsx, json or jsonl, honoring its saved
    filter and sort and flattening `columns` (joined columns are dotted headers
    "ref_field.target_field" in the text formats; json nests them). Any
    file/file_list column gets bundled into a zip alongside the table, laid out as
    the view's `files_layout` says -- the same paths as the Files menu -- and each
    file cell holds that path. Files that can't be reached (a drive that isn't
    connected) are left out and listed in MISSING.txt. This is the same export as
    POST /file-access/zip with `view`, which also takes a collection or record to
    run it in."""
    svc = ctx.file_access_svc
    try:
        selection = ctx.view_svc.table_selection(schema_name, view_name, format)
        plan = svc.plan(selection)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))

    with temp_paths() as tmp:
        scratch = new_temp_dir()
        tmp.append(scratch)
        try:
            download = build_download(
                svc,
                ctx.file_svc,
                selection,
                plan,
                scratch,
                name=safe_filename(view_name),
            )
        except FileNotFoundError as e:
            raise HTTPException(404, detail=f"Export file not found: {e}")
        tmp.remove(scratch)
        return serve(download.path, download.media_type, download.filename, scratch)
