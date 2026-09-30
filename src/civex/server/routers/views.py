from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from civex.context import AppContext
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError
from civex.server.deps import get_ctx
from civex.server.downloads import new_temp_path, serve, temp_paths
from civex.server.models import (
    CreateViewRequest,
    PreviewViewRequest,
    PreviewViewResponse,
    UpdateViewRequest,
    ViewResponse,
)
from civex.services.archive import write_zip
from civex.domain.naming import safe_filename
from civex.services.view_service import write_csv, write_json
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
        stream = ctx.view_svc.export_stream(schema_name, view_name)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))

    if format == "csv":
        data_filename, media_type = f"{safe_filename(view_name)}.csv", "text/csv"
    else:
        data_filename, media_type = (
            f"{safe_filename(view_name)}.json",
            "application/json",
        )

    file_entries: list = []

    def row_batches():
        for batch in stream.batches:
            file_entries.extend(batch.file_entries)
            yield batch.rows

    # Rows are paged out of the DB straight into a temp file, then the file is
    # served (or zipped) from disk: memory stays O(page), not O(export).
    with temp_paths() as tmp:
        data_path = new_temp_path(".export")
        tmp.append(data_path)
        with data_path.open("w", encoding="utf-8", newline="") as out:
            if format == "csv":
                write_csv(out, stream.view.columns, row_batches())
            else:
                write_json(out, row_batches())

        if not file_entries:
            tmp.remove(data_path)
            return serve(data_path, media_type, data_filename)

        zip_path = new_temp_path(".zip")
        tmp.append(zip_path)
        try:
            write_zip(
                zip_path,
                ctx.file_svc,
                file_entries,
                data_member=(data_filename, data_path),
            )
        except (FileNotFoundError, SyncError) as e:
            raise HTTPException(404, detail=f"Export file not found: {e}")
        tmp.remove(zip_path)
        tmp.remove(data_path)
        return serve(
            zip_path, "application/zip", f"{safe_filename(view_name)}.zip", data_path
        )
