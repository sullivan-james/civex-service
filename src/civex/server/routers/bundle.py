"""A project's data as one file another civex can read (see
`domain/bundle.py`): what one would hold, the file itself, and reading one
in."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from civex import fs_open
from civex.context import AppContext
from civex.domain.bundle import EXTENSION, BundleError, ExportOptions
from civex.domain.exceptions import CivexError, NotFoundError
from civex.domain.features import OPEN_FOLDER
from civex.server.deps import get_ctx
from civex.server.downloads import new_temp_path, serve, temp_paths
from civex.server.routers.file_access import _from_this_machine, report_progress
from civex.services.progress import Progress

router = APIRouter(tags=["bundle"])

_COLLECTIONS = Query(
    None,
    alias="collection",
    description="Only these collections' records and files (repeatable); default every collection.",
)
_FILES = Query(True, description="Carry the stored files the records cite.")
_DATA = Query(
    True, description="Carry the records (and so the files); false for structure only."
)
_WORKFLOWS = Query(True, description="Carry the project's workflows and plugins.")


class BundlePlanResponse(BaseModel):
    schemas: int = Field(description="Schemas (every schema goes in).")
    collections: list[str] = Field(description="The collections whose records go in.")
    records: int = Field(description="Records that go in.")
    files: int = Field(description="Distinct stored files those records cite.")
    file_bytes: int = Field(description="Their size in bytes.")
    files_unreachable: int = Field(
        description="Of those, files on no drive that can be reached now (left out)."
    )
    workflows: int
    plugins: int
    include_files: bool = Field(description="Whether the files would be carried.")


class SkippedResponse(BaseModel):
    id: str = Field(description="The record's id, or a workflow/plugin member name.")
    reason: str = Field(description="Why it was left out, in plain words.")


class BundleImportResponse(BaseModel):
    schemas_new: int
    schemas_existing: list[str] = Field(
        description="Schemas already here by name; they only gained fields they lacked."
    )
    collections_new: int
    collections_existing: list[str] = Field(
        description="Collections already here, reused."
    )
    records_added: int
    records_existing: int = Field(
        description="Records already here by id (live or deleted), left as they are."
    )
    records_skipped: int = Field(
        description="Records refused or waiting on a record that never arrived."
    )
    skipped: list[SkippedResponse] = Field(
        description="The first skipped records and why (the count above is exact)."
    )
    files_added: int
    files_missing: int = Field(
        description="Files the records cite that neither the bundle nor this project holds."
    )
    files_refused: int = Field(
        description="Files in the bundle whose bytes did not hash to their name; not stored."
    )
    workflows: int
    plugins: int = Field(
        description="Plugins written to _civex/plugins/. Plugins are code: review them."
    )
    members_skipped: list[SkippedResponse]


def _options(
    collections: Optional[list[str]], files: bool, data: bool, workflows: bool
) -> ExportOptions:
    return ExportOptions(
        include_records=data,
        include_files=data and files,
        include_workflows=workflows,
        collections=collections or None,
    )


@router.get("/bundle/plan", response_model=BundlePlanResponse)
def plan_bundle(
    collections: Optional[list[str]] = _COLLECTIONS,
    files: bool = _FILES,
    data: bool = _DATA,
    workflows: bool = _WORKFLOWS,
    ctx: AppContext = Depends(get_ctx),
):
    """What a bundle with these choices would hold, without writing it: the
    counts the download will have, and how big the files are."""
    try:
        plan = ctx.bundle_svc.plan_export(_options(collections, files, data, workflows))
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return BundlePlanResponse(**plan.to_dict())


@router.get("/bundle")
def export_bundle(
    collections: Optional[list[str]] = _COLLECTIONS,
    files: bool = _FILES,
    data: bool = _DATA,
    workflows: bool = _WORKFLOWS,
    progress: Progress | None = Depends(report_progress),
    ctx: AppContext = Depends(get_ctx),
):
    """Download the project (or the chosen collections) as a bundle: a zip
    holding `bundle.json`, `records.jsonl`, the stored files (unless
    `files=false`) and the workflows and plugins. Read it into another project
    with `POST /bundle/import` or `civex bundle import`."""
    with temp_paths() as tmp:
        path = new_temp_path(".zip")
        tmp.append(path)
        try:
            ctx.bundle_svc.export(
                path, _options(collections, files, data, workflows), progress
            )
        except NotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        tmp.remove(path)
        return serve(path, "application/zip", "civex-bundle" + EXTENSION)


class BundleSaveRequest(BaseModel):
    collections: list[str] | None = Field(
        default=None,
        description="Only these collections' records and files; default every one.",
    )
    files: bool = Field(
        default=True, description="Carry the stored files the records cite."
    )
    data: bool = Field(
        default=True, description="Carry the records; false for structure only."
    )
    workflows: bool = Field(
        default=True, description="Carry the project's workflows and plugins."
    )
    folder: str | None = Field(
        default=None,
        description="The folder on this computer to put it in (any folder: an "
        "external drive, a shared folder); none: the project's own exports "
        "folder.",
    )
    open: bool = Field(
        default=True, description="Open the folder it is in when done (this machine)."
    )


class SavedResponse(BaseModel):
    path: str = Field(description="Where the file was written.")
    opened: bool = Field(description="Whether its folder was opened.")


@router.post("/bundle/save", response_model=SavedResponse)
def save_bundle(
    body: BundleSaveRequest,
    request: Request,
    progress: Progress | None = Depends(report_progress),
    ctx: AppContext = Depends(get_ctx),
):
    """Write the project (or the chosen collections) as a bundle straight into
    a folder of this computer, instead of downloading it through the browser.
    The same file as `GET /bundle`. 404 when there is no such folder, 422 when
    it can't be written to."""
    name = (
        f"{ctx.project.config.civex_dir.parent.name}-"
        f"{datetime.now(timezone.utc):%Y-%m-%d}{EXTENSION}"
    )
    try:
        dest = ctx.file_access_svc.save_to(
            body.folder,
            name,
            lambda path: ctx.bundle_svc.export(
                path,
                _options(body.collections, body.files, body.data, body.workflows),
                progress,
            ),
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except CivexError as e:
        raise HTTPException(status_code=422, detail=str(e))
    opened = (
        body.open
        and OPEN_FOLDER in ctx.features
        and _from_this_machine(request)
        and fs_open.open_folder(dest.parent)
    )
    return SavedResponse(path=str(dest), opened=bool(opened))


@router.post("/bundle/import", response_model=BundleImportResponse)
async def import_bundle(
    file: UploadFile,
    progress: Progress | None = Depends(report_progress),
    ctx: AppContext = Depends(get_ctx),
):
    """Read an uploaded bundle into this project. Schemas and collections are
    matched by name, records by id (one already here is left as it is); each
    record is checked and recorded in history like any other, and the whole
    import is one event in Activity. Plugins in the bundle are written to
    `_civex/plugins/`: they are code, so the answer counts them."""
    with temp_paths() as tmp:
        path = new_temp_path(".zip")
        tmp.append(path)
        with path.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                out.write(chunk)
        try:
            result = ctx.bundle_svc.import_bundle(
                path, progress, label=_label(file.filename)
            )
        except BundleError as e:
            raise HTTPException(status_code=400, detail=str(e))
        ctx.commit()
    if result.plugins:
        from civex.plugins.registry import discover_user_plugins

        discover_user_plugins(ctx.config.civex_dir / "plugins")
    return BundleImportResponse(**result.to_dict())


def _label(filename: str | None) -> str:
    return Path(filename).name if filename else "bundle"
