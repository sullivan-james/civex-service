from __future__ import annotations

import ipaddress
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from civex import fs_open
from civex.context import AppContext
from civex.domain.exceptions import CivexError, NotFoundError, ValidationError
from civex.domain.file_access import (
    place_of,
    FileSelection,
    FilesScatteredError,
    FilesUnavailableError,
    LinksNotPossibleError,
)
from civex.domain.naming import safe_filename
from civex.domain.query import RecordQuery
from civex.domain.sync import SyncError
from civex.domain.tables import TableSpec
from civex.domain.transfers import KIND_FILES, TransferSpec
from civex.server.deps import get_ctx
from civex.server.downloads import new_temp_dir, serve, temp_paths
from civex.server.models import (
    FileExportRequest,
    FileGatherRequest,
    FileListRequest,
    FilePickRequest,
    FilePlanRequest,
    FileSelectionRequest,
    FileZipRequest,
    ExportDefinitionResponse,
    RemoveExportsRequest,
)
from civex.services.archive import build_download
from civex.services.progress import Progress, registry as progress_registry
from civex.services.transfer_jobs import jobs

router = APIRouter(prefix="/file-access", tags=["files"])

PROGRESS_HEADER = "X-Civex-Progress"


def report_progress(request: Request):
    """Report how far this request has got, if the client asked to be told: it
    tags the request with `X-Civex-Progress: <id>` and polls
    `GET /file-access/progress/<id>` meanwhile. Without the header, nothing is
    recorded."""
    progress_id = request.headers.get(PROGRESS_HEADER)
    if not progress_registry.valid(progress_id):
        yield None
        return
    progress = progress_registry.start(progress_id or "")
    try:
        yield progress
    except BaseException as e:
        progress.finish(str(e) or type(e).__name__)
        raise
    else:
        progress.finish()


@router.get("/progress/{progress_id}")
def get_progress(progress_id: str):
    """How far a request tagged with this id has got: the stage it is in, how many
    steps it has done of how many (0 when that isn't known yet), and whether it has
    finished. 404 until the request has begun, and again a little after it ends."""
    state = progress_registry.get(progress_id)
    if state is None:
        raise HTTPException(404, detail="Nothing is reporting under that id.")
    return state


def _selection(body: FileSelectionRequest, ctx: AppContext) -> FileSelection:
    """The selection a request describes, with its table and order applied."""
    selection = _base_selection(body, ctx)
    sent = body.model_fields_set
    if body.tables is not None:
        try:
            selection.tables = [TableSpec(**t.model_dump()) for t in body.tables]
        except ValidationError as e:
            raise HTTPException(422, detail=str(e))
    if "files" in sent:
        selection.files = body.files
    if body.sort:
        selection.query.sort = body.sort
    if not selection.files and not selection.tables:
        raise HTTPException(422, detail="Without files, an export needs a table.")
    return selection


def _base_selection(body: FileSelectionRequest, ctx: AppContext) -> FileSelection:
    if body.export:
        schema_name, _, export_name = body.export.partition("/")
        if not export_name:
            raise HTTPException(422, detail="An export is named schema/name.")
        try:
            definition = ctx.export_def_svc.get(schema_name, export_name)
        except NotFoundError as e:
            raise HTTPException(404, detail=str(e))
        run = ctx.export_def_svc.selection(
            definition, collection=body.collection, within=body.within
        )
        if "layout" in body.model_fields_set:
            run.layout = body.layout
        return run
    if body.view:
        schema_name, _, view_name = body.view.partition("/")
        if not view_name:
            raise HTTPException(422, detail="A view is named schema/view.")
        try:
            selection = ctx.view_svc.file_selection(schema_name, view_name)
        except NotFoundError as e:
            raise HTTPException(404, detail=str(e))
        if selection is None:
            raise HTTPException(
                422, detail=f"The view '{body.view}' has no file columns."
            )
        if body.collection:
            selection.query.dataset = body.collection
        if body.within:
            selection.query.within = body.within
        if "layout" in body.model_fields_set:
            selection.layout = body.layout
        return selection
    return FileSelection(
        query=RecordQuery(
            dataset=body.collection,
            schema=body.schema_name,
            within=body.within,
            filter_tree=body.filter,
            where=body.where,
            search=body.search,
        ),
        record_ids=body.record_ids,
        fields=body.fields,
        base=body.base,
        layout=body.layout,
        schemas=body.kinds,
        below=body.below,
    )


def _from_this_machine(request: Request) -> bool:
    host = request.client.host if request.client else ""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _unreachable(e: FilesUnavailableError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "detail": str(e),
            "code": "files_unavailable",
            "plan": e.plan.to_dict(include_items=False),
        },
    )


@router.post("/plan")
def plan_files(
    body: FilePlanRequest,
    ctx: AppContext = Depends(get_ctx),
    progress: Progress | None = Depends(report_progress),
):
    """What a selection holds, each file named by its place in the record
    hierarchy, and what can be reached right now. Makes nothing: this is what to
    show a person before they are pointed at a folder."""
    try:
        plan = ctx.file_access_svc.plan(_selection(body, ctx), progress=progress)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except CivexError as e:
        raise HTTPException(422, detail=str(e))
    return plan.to_dict(body.include_items, body.offset, body.limit)


@router.post("/export")
def export_files(
    body: FileExportRequest,
    request: Request,
    ctx: AppContext = Depends(get_ctx),
    progress: Progress | None = Depends(report_progress),
):
    """Build the selection as a folder tree on the server's machine.

    `link` makes hard links in a folder on the drive that holds the files;
    `copy` makes copies on the drive named by `volume`. Answers 409, building
    nothing, when files are out of reach (`files_unavailable`, unless
    `allow_partial`), when they are on several drives and a link was asked for
    (`files_scattered`), or when the drive can't hold links
    (`links_not_possible`). Building again into the same folder updates it."""
    svc = ctx.file_access_svc
    selection = _selection(body, ctx)
    try:
        if body.dest:
            result = svc.export(
                selection,
                Path(body.dest),
                body.mode,
                allow_partial=body.allow_partial,
                progress=progress,
            )
        else:
            result = svc.export_managed(
                selection,
                body.name,
                body.mode,
                body.volume,
                allow_partial=body.allow_partial,
                progress=progress,
            )
    except FilesUnavailableError as e:
        return _unreachable(e)
    except FilesScatteredError as e:
        return JSONResponse(
            status_code=409,
            content={
                "detail": str(e),
                "code": "files_scattered",
                "plan": e.plan.to_dict(include_items=False),
            },
        )
    except LinksNotPossibleError as e:
        return JSONResponse(
            status_code=409, content={"detail": str(e), "code": "links_not_possible"}
        )
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except CivexError as e:
        raise HTTPException(422, detail=str(e))
    opened = (
        body.open
        and _from_this_machine(request)
        and fs_open.open_folder(Path(result.dest))
    )
    return {**result.to_dict(), "opened": bool(opened)}


@router.post("/gather", status_code=202)
def gather_files(
    body: FileGatherRequest,
    ctx: AppContext = Depends(get_ctx),
    progress: Progress | None = Depends(report_progress),
):
    """Move the picked files onto one drive: a selection's files, narrowed by
    place, name or ticked files (`shas`). Only those move; the rest of their
    collections stay where they are. Files only on the server are downloaded
    first; files on a drive that can't be reached, or missing, are left out. It
    runs like any other move (one at a time, safe to pause, cancel or lose
    power; see /store/transfers). Files downloaded straight onto the drive need
    no move: when nothing else has to move, `transfer_id` is null and
    `downloaded` says how many came. 422 when they are all already there."""
    items = _picked(body, ctx)
    try:
        shas, downloaded = ctx.file_access_svc.to_move(items, body.volume, progress)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except CivexError as e:
        raise HTTPException(422, detail=str(e))
    ctx.commit()
    if not shas:
        if downloaded:  # those only on the server came straight there
            return JSONResponse(
                {
                    "transfer_id": None,
                    "volume": body.volume,
                    "files": 0,
                    "bytes": 0,
                    "downloaded": downloaded,
                },
                status_code=200,
            )
        raise HTTPException(
            422, detail=f"Every file that can move is already on '{body.volume}'."
        )
    record = jobs.start(
        TransferSpec(
            kind=KIND_FILES, targets=[body.volume], shas=shas, freeze_sources=False
        )
    )
    return {
        "transfer_id": record.id,
        "volume": body.volume,
        "files": record.plan.files if record.plan else len(shas),
        "bytes": record.plan.bytes if record.plan else 0,
        "downloaded": downloaded,
    }


def _picked(body: FilePickRequest, ctx: AppContext):
    selection = _base_selection(body, ctx)
    if body.sort:
        selection.query.sort = body.sort
    try:
        return ctx.file_access_svc.chosen(selection, body.place, body.name, body.shas)[
            1
        ]
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))


@router.post("/files")
def list_files(body: FileListRequest, ctx: AppContext = Depends(get_ctx)):
    """A page of a selection's files, each with where it is (`place`: a
    drive's name, `server` or `missing`; `place_kind`: drive, unreachable,
    server or missing), narrowed by place, name and the selection's own
    filter; and `summary`, where all of the selection's files are, by place."""
    selection = _base_selection(body, ctx)
    if body.sort:
        selection.query.sort = body.sort
    try:
        listing = ctx.file_access_svc.listing(
            selection, body.place, body.name, body.order, body.offset, body.limit
        )
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    return {
        "total": listing.total,
        "summary": [vars(p) for p in listing.summary],
        "items": [
            {
                **i.to_dict(),
                "place": place_of(i)[0],
                "place_kind": place_of(i)[1],
            }
            for i in listing.items
        ],
    }


@router.post("/download")
def download_files(
    body: FilePickRequest,
    ctx: AppContext = Depends(get_ctx),
    progress: Progress | None = Depends(report_progress),
):
    """Download the picked files that are only on the server to this computer
    (onto their collection's drive). Answers when they have arrived: how many
    came and which the server hasn't got yet."""
    items = _picked(body, ctx)
    try:
        report = ctx.file_access_svc.download(items, progress)
    except SyncError as e:
        raise HTTPException(503, detail=f"The server can't be reached: {e}")
    ctx.commit()
    return {
        "fetched": report.fetched if report else 0,
        "absent": len(report.absent) if report else 0,
    }


@router.post("/free-up")
def free_up_files(
    body: FilePickRequest,
    dry_run: bool = Query(default=True, description="Only count (the default)."),
    ctx: AppContext = Depends(get_ctx),
):
    """Remove this computer's copies of the picked files to free space; each
    comes back when opened or exported. Only files the server confirms it
    holds, and never one a collection kept on this computer uses (switch that
    collection to fetch when opened first). Counts unless `dry_run=false`."""
    items = _picked(body, ctx)
    try:
        report = ctx.file_access_svc.free_up(items, dry_run=dry_run)
    except SyncError as e:
        raise HTTPException(503, detail=f"The server can't be reached to check: {e}")
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    ctx.commit()
    return {**vars(report), "done": not dry_run}


@router.get("/definitions", response_model=list[ExportDefinitionResponse])
def available_definitions(
    schema: str | None = Query(
        default=None,
        description="A schema name: the exports that can run within a record of it.",
    ),
    collection: str | None = Query(
        default=None,
        description="A collection name: the exports saved with its schemas.",
    ),
    ctx: AppContext = Depends(get_ctx),
):
    """The saved exports to offer where the person is: on a record of `schema`
    (those saved with it or a schema above it whose files are at or beneath it),
    or on a `collection` (those saved with any schema it is for). Give neither for
    every saved export. Run one with `export` as `schema/name` and `collection`
    and/or `within`."""
    if schema is not None and collection is not None:
        raise HTTPException(422, detail="Give 'schema' or 'collection', not both.")
    try:
        if schema is None and collection is None:
            found = ctx.export_def_svc.list_all()
        elif schema is not None:
            found = ctx.export_def_svc.available_on(schema)
        else:
            found = ctx.export_def_svc.for_collection(
                ctx.dataset_svc.get(collection or "").schemas
            )
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    return [ExportDefinitionResponse.from_dto(d) for d in found]


@router.get("/exports")
def list_exports(ctx: AppContext = Depends(get_ctx)):
    """The export folders civex made, newest first, in the project and on each
    connected drive: where they are, how many files, and how much space they
    take (links take none; copies do). Exports on a drive that isn't connected
    can't be listed."""
    return [e.to_dict() for e in ctx.file_access_svc.list_exports()]


@router.post("/exports/remove")
def remove_exports(body: RemoveExportsRequest, ctx: AppContext = Depends(get_ctx)):
    """Delete export folders: the links or copies the export made, then the
    folder. A link is removed without touching the stored file it points at.
    Files in the folder that the export didn't make are left, with the folder.
    A path that isn't an export folder is refused (listed under `errors`)."""
    results, errors = [], []
    for path in body.paths:
        try:
            results.append(ctx.file_access_svc.remove_export(path).to_dict())
        except CivexError as e:
            errors.append({"path": path, "error": str(e)})
        except OSError as e:
            errors.append({"path": path, "error": str(e)})
    return {"results": results, "errors": errors}


@router.post("/zip")
def zip_files(
    body: FileZipRequest,
    ctx: AppContext = Depends(get_ctx),
    progress: Progress | None = Depends(report_progress),
):
    """The selection as something to download, with the same paths and tables as
    an export -- for someone who can't see the server's disk: a zip of the files
    and their tables, or, when the selection is a single table and nothing else,
    that table itself. Unreachable files answer 409 unless `allow_partial` is
    set, and are then listed in MISSING.txt."""
    svc = ctx.file_access_svc
    selection = _selection(body, ctx)
    try:
        plan = svc.plan(selection, progress=progress, fetch=True)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except CivexError as e:
        raise HTTPException(422, detail=str(e))
    if not plan.complete and not body.allow_partial:
        return _unreachable(FilesUnavailableError(plan))
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
                name=safe_filename(body.name) if body.name else None,
            )
        except FileNotFoundError as e:
            raise HTTPException(404, detail=f"A file is no longer stored: {e}")
        except CivexError as e:
            raise HTTPException(422, detail=str(e))
        tmp.remove(scratch)
        return serve(download.path, download.media_type, download.filename, scratch)
