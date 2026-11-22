"""Releases: frozen, citable copies of the data (`domain/release.py`).

Make one (after a plan of what it would hold), list them, read one's manifest
and citation, check it still holds what it was made with, see what changed
since, correct its citation details, withdraw it or yank it (give its data
up), get its files out the way any selection's are (a folder on a drive, a
move onto one drive, a zip while it is small), and download its bundle of
records (read into a new project with `POST /bundle/import`)."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from civex import fs_open
from civex.context import AppContext
from civex.domain import release as rules
from civex.domain.dtos import ReleaseDTO
from civex.domain.exceptions import CivexError, NotFoundError
from civex.domain.file_access import FilesUnavailableError, LinksNotPossibleError
from civex.domain.features import OPEN_FOLDER
from civex.server.deps import get_ctx
from civex.server.downloads import new_temp_dir, serve, temp_paths
from civex.server.models import RecordQueryRequest
from civex.server.routers.file_access import (
    _from_this_machine,
    _unreachable,
    report_progress,
)
from civex.services.archive import build_download
from civex.services.progress import Progress
from civex.services.record_service import MAX_ZIP_FILE_COUNT, MAX_ZIP_TOTAL_SIZE
from civex.services.release_service import COMPARE_INLINE_MAX, ReleaseScope
from civex.services.transfer_jobs import jobs

router = APIRouter(tags=["releases"])


class ReleaseScopeRequest(BaseModel):
    collections: list[str] | None = Field(
        default=None,
        description="Only these collections (by name). Leave out, with no query, for the whole project.",
    )
    query: RecordQueryRequest | None = Field(
        default=None,
        description="Only the records this query lists, and the records above them.",
    )
    records: list[str] | None = Field(
        default=None,
        description="Exactly these records (by id), and the records above them.",
    )
    below: bool = Field(
        default=True,
        description="With `query` or `records`: also every record inside the "
        "ones chosen (an encounter with its recordings). False takes only the "
        "records chosen and those above them.",
    )
    include_workflows: bool = Field(
        default=False,
        description="Also carry the project's workflows and plugins (their "
        "code). Left out unless asked for: a release is of the data, and code "
        "may not be yours to publish.",
    )

    def scope(self) -> ReleaseScope:
        return ReleaseScope(
            collections=self.collections or None,
            query=self.query.to_query() if self.query else None,
            records=self.records or None,
            below=self.below and bool(self.query or self.records),
        )


class AuthorModel(BaseModel):
    name: str = Field(description="As it is cited, e.g. 'Ada Lovelace'.")
    orcid: str | None = Field(default=None, description="e.g. 0000-0002-1825-0097.")
    affiliation: str | None = Field(default=None, description="Where they work.")


class ReleaseMetadata(BaseModel):
    title: str | None = Field(default=None, description="What the data is.")
    description: str | None = Field(default=None, description="A longer account.")
    authors: list[AuthorModel] | None = Field(
        default=None, description="The authors, in citation order."
    )
    licence: str | None = Field(
        default=None, description="An SPDX id (e.g. CC-BY-4.0) or the licence's name."
    )
    doi: str | None = Field(default=None, description="A DOI, e.g. 10.1234/abcd.")
    keywords: list[str] | None = Field(default=None, description="Words to find it by.")

    def values(self) -> dict[str, Any]:
        out = self.model_dump(exclude_unset=True)
        if "authors" in out and out["authors"] is not None:
            out["authors"] = [{k: v for k, v in a.items() if v} for a in out["authors"]]
        return out


class ReleaseCreateRequest(ReleaseScopeRequest, ReleaseMetadata):
    name: str = Field(description="The version people cite, e.g. v1 or 2026-thesis.")
    title: str = Field(description="What the data is.")


class CitationPreviewRequest(ReleaseMetadata):
    name: str = Field(default="", description="The version it would have.")


class ReasonRequest(BaseModel):
    reason: str = Field(description="Why, in plain words.")


class ReleaseResponse(BaseModel):
    id: str
    name: str = Field(description="The version, e.g. v1.")
    title: str
    description: str | None
    authors: list[dict[str, str]] = Field(
        description="{name, orcid?, affiliation?} each, in citation order."
    )
    licence: str | None
    doi: str | None
    keywords: list[str]
    scope: dict[str, Any] = Field(
        description="{} the whole project, {collections: [...]}, {query: {...}} or {records: [...]}."
    )
    content_hash: str = Field(
        description="sha256 over the records and the hashes of the files they cite (no file is read): identical data, identical hash."
    )
    bundle_sha256: str = Field(
        description="The bundle of records' own hash: where it is kept, and its download address under /files/."
    )
    bundle_size: int
    counts: dict[str, Any] = Field(
        description="What it holds: schemas, collections, records, files, bytes, workflows, plugins."
    )
    local_seq: int | None = Field(
        description="This copy's history position when it was made (None on a copy it was not made on)."
    )
    feed_seq: int | None = Field(
        description="The server's feed number it was made at, on a synced project."
    )
    civex_version: str
    created_at: str
    created_by: str | None
    updated_at: str | None
    withdrawn_at: str | None
    withdrawn_by: str | None
    withdrawn_reason: str | None
    yanked_at: str | None = Field(
        description="When its data was given up; what is left is this record of it."
    )
    yanked_by: str | None
    yanked_reason: str | None
    file_name: str = Field(description="The name the bundle is saved under.")
    compare_in_background: bool = Field(
        default=False,
        description="Comparing it with the data now is long: run it as a job.",
    )

    @classmethod
    def from_dto(cls, r: ReleaseDTO) -> "ReleaseResponse":
        d = r.to_dict()
        d.setdefault("local_seq", None)
        return cls(
            **d,
            file_name=f"release-{r.name}.civex.zip",
            compare_in_background=int(r.counts.get("records") or 0)
            > COMPARE_INLINE_MAX,
        )


class CitationResponse(BaseModel):
    text: str = Field(description="One paragraph for a reference list.")
    bibtex: str = Field(description="A BibTeX @misc entry.")
    cff: str = Field(description="CITATION.cff (Citation File Format 1.2.0).")


class VerifyResponse(BaseModel):
    name: str
    matches: bool = Field(description="It holds exactly what it was made with.")
    expected: str = Field(description="The content hash recorded when it was made.")
    actual: str | None = Field(description="The content hash found now.")
    bundle_intact: bool = Field(
        description="The bundle's bytes match the hash it is kept under."
    )
    files: int = Field(description="Files its records cite.")
    files_not_here: int = Field(description="Of those, recorded on no drive here.")
    files_unchecked: int = Field(
        description="Of those here, never read back against their hash."
    )
    files_read: int = Field(description="Deep: files read back.")
    files_bad: list[str] = Field(description="Deep: files whose bytes didn't match.")
    deep: bool
    problems: list[str] = Field(description="What is wrong, in plain words.")
    notes: list[str] = Field(description="What is worth knowing, in plain words.")


class ReleasePlanResponse(BaseModel):
    records: int
    collections: dict[str, int] = Field(description="Records per collection.")
    schemas: int
    files: int = Field(description="Files the records cite (not copied: owned).")
    file_bytes: int
    by_drive: list[dict[str, Any]] = Field(
        description="Where those files are: {volume (None: not here), files, bytes}."
    )
    workflows: int
    plugins: int
    feed_seq: int | None = Field(description="The server's feed number now.")
    local_seq: int = Field(description="This copy's history position now.")
    unsent: int = Field(
        description="Changes the server hasn't got: a release waits for none."
    )


class YankPlanResponse(BaseModel):
    name: str
    files: int = Field(description="Files the release keeps now.")
    unused_files: int = Field(
        description="Of those, used by nothing else: a clean-up then removes them."
    )
    unused_bytes: int
    kept_files: int = Field(description="Of those, still used by something else.")


class ReleaseExportRequest(BaseModel):
    mode: str = Field(
        default="link",
        description="link: a folder on the drive holding most of the files; copy: copies on `volume`.",
    )
    volume: str | None = Field(default=None, description="Where copies go (copy).")
    name: str | None = Field(default=None, description="The folder's name.")
    allow_partial: bool = Field(
        default=False, description="Make it with what can be reached."
    )
    open: bool = Field(default=False, description="Open the folder when made.")


class ReleaseGatherRequest(BaseModel):
    volume: str = Field(description="The drive to put the release's files on.")


class CollectionComparisonResponse(BaseModel):
    collection_id: str
    collection: str | None = Field(
        description="The collection's name now (or as it was, when it is gone)."
    )
    added: int = Field(description="In the release's scope now, not in it.")
    changed: int = Field(description="In both; its values or place differ.")
    removed: int = Field(description="In it, and not live now (deleted or purged).")
    in_scope: bool = Field(description="The collection is one the release covers.")


class StructureChangeResponse(BaseModel):
    kind: str = Field(description="schema or field.")
    change: str = Field(description="added, removed or changed.")
    name: str | None = Field(description="Its name now (or as it was, if removed).")
    schema_name: str | None = Field(
        default=None, alias="schema", description="For a field: its schema."
    )
    what: list[str] = Field(description="For a change: the attributes that differ.")


class ComparisonResponse(BaseModel):
    name: str
    records: int = Field(description="Records the release holds.")
    unchanged: int = Field(description="Of those, the same now.")
    added: int = Field(description="Records in its scope now that it doesn't hold.")
    changed: int = Field(description="Records it holds whose values or place differ.")
    removed: int = Field(description="Records it holds that are not live now.")
    collections: list[CollectionComparisonResponse]
    structure: list[StructureChangeResponse] = Field(
        description="Schemas and fields added, removed or changed since (a rename is a change)."
    )
    at: int = Field(description="The history position it was worked out at.")


class ComparedRecordResponse(BaseModel):
    id: str
    name: str | None = Field(description="The record's name (as it was, if removed).")
    collection: str | None
    schema_name: str | None = Field(alias="schema")
    live: bool = Field(description="False for a removed record, read from the release.")


class ComparedRecordsResponse(BaseModel):
    total: int = Field(description="How many records this kind of difference means.")
    items: list[ComparedRecordResponse]


class RecordDifferenceResponse(BaseModel):
    field: str = Field(description="The field's id, or dataset_id / parent_record_id.")
    label: str | None = Field(description="The field's name now.")
    dtype: str | None
    before: Any = Field(description="The value in the release.")
    after: Any = Field(description="The value now.")


@router.get("/releases", response_model=list[ReleaseResponse])
def list_releases(ctx: AppContext = Depends(get_ctx)):
    """Every release, newest first."""
    return [ReleaseResponse.from_dto(r) for r in ctx.release_svc.list_all()]


@router.post("/releases/plan", response_model=ReleasePlanResponse)
def plan_release(body: ReleaseScopeRequest, ctx: AppContext = Depends(get_ctx)):
    """What a release of this scope would hold, without making it, from the
    catalog: records per collection, the files they cite by drive, and the
    history position it would be taken at."""
    plan = ctx.release_svc.plan(body.scope(), body.include_workflows)
    return ReleasePlanResponse(**plan.to_dict())


@router.post("/releases/citation-preview", response_model=CitationResponse)
def preview_citation(body: CitationPreviewRequest, ctx: AppContext = Depends(get_ctx)):
    """How a release with these details would be cited, before it is made."""
    values = body.values()
    return CitationResponse(
        **{
            form: ctx.release_svc.preview(values, body.name, form)
            for form in rules.CITATION_FORMATS
        }
    )


@router.post("/releases", response_model=ReleaseResponse, status_code=201)
def create_release(
    body: ReleaseCreateRequest,
    progress: Progress | None = Depends(report_progress),
    ctx: AppContext = Depends(get_ctx),
):
    """Freeze the scope as a release: write the bundle of its records, hash
    it (the hash covers each cited file by its sha256), add a CITATION.cff,
    keep it in the project's storage and own the files the records cite
    (where they are: nothing is copied, and no drive is asked). Needs
    permission to change the project's structure. Refused on a synced copy
    with changes the server hasn't got yet (sync first)."""
    values = body.values()
    made = ctx.release_svc.create(
        body.name,
        body.title,
        body.scope(),
        description=values.get("description"),
        authors=values.get("authors"),
        licence=values.get("licence"),
        doi=values.get("doi"),
        keywords=values.get("keywords"),
        include_workflows=body.include_workflows,
        progress=progress,
    )
    ctx.commit()
    return ReleaseResponse.from_dto(made)


@router.get("/releases/{name}", response_model=ReleaseResponse)
def get_release(name: str, ctx: AppContext = Depends(get_ctx)):
    """One release's citation details and manifest, by name or id."""
    return ReleaseResponse.from_dto(ctx.release_svc.get(name))


@router.patch("/releases/{name}", response_model=ReleaseResponse)
def correct_release(
    name: str, body: ReleaseMetadata, ctx: AppContext = Depends(get_ctx)
):
    """Correct a release's citation details (title, description, authors,
    licence, DOI, keywords). Its content never changes; the correction is in
    history."""
    release = ctx.release_svc.correct(name, **body.values())
    ctx.commit()
    return ReleaseResponse.from_dto(release)


@router.post("/releases/{name}/withdraw", response_model=ReleaseResponse)
def withdraw_release(
    name: str, body: ReasonRequest, ctx: AppContext = Depends(get_ctx)
):
    """Mark a release withdrawn, saying why. It keeps its data."""
    release = ctx.release_svc.withdraw(name, body.reason)
    ctx.commit()
    return ReleaseResponse.from_dto(release)


@router.get("/releases/{name}/yank", response_model=YankPlanResponse)
def plan_yank(name: str, ctx: AppContext = Depends(get_ctx)):
    """What yanking the release would give up: how many of its files (and
    bytes) nothing else uses, so a clean-up then removes them, and how many
    stay for their other users. Counted from the catalog by the clean-up's
    own rule; nothing changes."""
    return YankPlanResponse(**ctx.release_svc.plan_yank(name).to_dict())


@router.post("/releases/{name}/yank", response_model=ReleaseResponse)
def yank_release(name: str, body: ReasonRequest, ctx: AppContext = Depends(get_ctx)):
    """Give the release's data up for good, saying why: it stops keeping its
    files and its bundle (a clean-up removes what nothing else uses), and what
    is left is a record of it (name, hash, citation, who, when and why) that a
    citation still finds. It is withdrawn too. Can't be undone."""
    release = ctx.release_svc.yank(name, body.reason)
    ctx.commit()
    return ReleaseResponse.from_dto(release)


@router.get("/releases/{name}/citation", response_model=CitationResponse)
def cite_release(name: str, ctx: AppContext = Depends(get_ctx)):
    """How to cite a release: a paragraph, BibTeX and CITATION.cff."""
    facts = ctx.release_svc.facts(ctx.release_svc.get(name))
    return CitationResponse(
        text=rules.citation_text(facts),
        bibtex=rules.bibtex(facts),
        cff=rules.citation_cff(facts),
    )


@router.post("/releases/{name}/verify", response_model=VerifyResponse)
def verify_release(
    name: str,
    deep: bool = False,
    progress: Progress | None = Depends(report_progress),
    ctx: AppContext = Depends(get_ctx),
):
    """Whether the release still holds what it was made with: its bundle read
    back and its content hash recomputed, and every file it cites recorded on
    a drive here (no file is read). With `deep`, every file here is read back
    against its hash too: a long job for a large release, reporting its
    progress like an export (`X-Civex-Progress`)."""
    result = ctx.release_svc.verify(name, deep=deep, progress=progress)
    if deep:
        ctx.commit()  # the copies read back are marked checked
    return VerifyResponse(**result.to_dict())


@router.post("/releases/{name}/files/plan")
def plan_release_files(
    name: str,
    progress: Progress | None = Depends(report_progress),
    ctx: AppContext = Depends(get_ctx),
):
    """Every file the release cites at its path in the record hierarchy (the
    same paths as any export), whether each can be reached now (what can't,
    grouped by drive, with what to do), and whether it is small enough to
    download as a zip (`zip_allowed`)."""
    plan = ctx.release_svc.file_plan(name, progress)
    out = plan.to_dict(False)
    out["zip_allowed"] = _zip_allowed(plan)
    return out


@router.post("/releases/{name}/files/export")
def export_release_files(
    name: str,
    body: ReleaseExportRequest,
    request: Request,
    progress: Progress | None = Depends(report_progress),
    ctx: AppContext = Depends(get_ctx),
):
    """Make a folder of the release's files, as any export makes one (`link`:
    on the drive holding most of them, hard links where it can; `copy`: copies
    on `volume`), with `manifest-sha256.txt` (BagIt: each file's hash and
    path), `release.json` and `CITATION.cff`. 409 as an export when files are
    out of reach or the drive can't be written to."""
    try:
        with ctx.release_svc.file_access(name) as (access, selection):
            result = access.export_managed(
                selection,
                body.name or f"release-{name}",
                body.mode,
                body.volume,
                allow_partial=body.allow_partial,
                progress=progress,
            )
            plan = access.plan(selection)
    except FilesUnavailableError as e:
        return _unreachable(e)
    except LinksNotPossibleError as e:
        return JSONResponse(
            status_code=409, content={"detail": str(e), "code": "links_not_possible"}
        )
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except CivexError as e:
        raise HTTPException(422, detail=str(e))
    ctx.release_svc.write_bag(name, Path(result.dest), plan)
    opened = (
        body.open
        and OPEN_FOLDER in ctx.features
        and _from_this_machine(request)
        and fs_open.open_folder(Path(result.dest))
    )
    return {**result.to_dict(), "opened": bool(opened)}


@router.post("/releases/{name}/files/zip")
def zip_release_files(
    name: str,
    allow_partial: bool = False,
    progress: Progress | None = Depends(report_progress),
    ctx: AppContext = Depends(get_ctx),
):
    """The release's files (with its manifest and citation) as one zip, for a
    release small enough to download (at most the zip limit); a larger one is
    made into a folder on a drive instead (422)."""
    with ctx.release_svc.file_access(name) as (access, selection):
        plan = access.plan(selection, progress=progress, fetch=True)
        if not _zip_allowed(plan):
            raise HTTPException(
                422,
                detail="This release is too large to download as one zip: make "
                "a folder of it on a drive instead.",
            )
        if not plan.complete and not allow_partial:
            return _unreachable(FilesUnavailableError(plan))
        with temp_paths() as tmp:
            scratch = new_temp_dir()
            tmp.append(scratch)
            bag = scratch / "bag"
            bag.mkdir()
            beside = ctx.release_svc.write_bag(name, bag, plan)
            try:
                download = build_download(
                    access,
                    ctx.file_svc,
                    selection,
                    plan,
                    scratch,
                    name=f"release-{name}",
                    beside=beside,
                )
            except FileNotFoundError as e:
                raise HTTPException(404, detail=f"A file is no longer stored: {e}")
            tmp.remove(scratch)
            return serve(download.path, download.media_type, download.filename, scratch)


@router.post("/releases/{name}/files/gather", status_code=202)
def gather_release_files(
    name: str, body: ReleaseGatherRequest, ctx: AppContext = Depends(get_ctx)
):
    """Put the release's files on one drive, as any move does (one at a time,
    safe to pause, cancel or lose power; see /store/transfers). Only the
    release's own copies move: a copy its records use elsewhere stays, so it
    is copied."""
    record = jobs.start(ctx.release_svc.gather_spec(name, body.volume))
    return {
        "transfer_id": record.id,
        "volume": body.volume,
        "files": record.plan.files if record.plan else 0,
        "bytes": record.plan.bytes if record.plan else 0,
    }


def _zip_allowed(plan: Any) -> bool:
    return (
        len(plan.items) <= MAX_ZIP_FILE_COUNT
        and sum(i.size for i in plan.items) <= MAX_ZIP_TOTAL_SIZE
    )


@router.post("/releases/{name}/compare", response_model=ComparisonResponse)
def compare_release(
    name: str,
    progress: Progress | None = Depends(report_progress),
    ctx: AppContext = Depends(get_ctx),
):
    """The release compared with the data now, record by record (never from
    history, so every copy answers the same): records added to its scope,
    changed and removed, per collection, and the schemas and fields added,
    removed or changed since. A large release reports its progress
    (`X-Civex-Progress`); the answer is kept until the data changes."""
    return ComparisonResponse(**ctx.release_svc.compare(name, progress).to_dict())


@router.get("/releases/{name}/compare/records", response_model=ComparedRecordsResponse)
def compared_records(
    name: str,
    kind: str,
    offset: int = 0,
    limit: int = 50,
    collection: str | None = None,
    ctx: AppContext = Depends(get_ctx),
):
    """A page of the records one kind of difference (`added`, `changed`,
    `removed`) means, in one collection (by id) when given. Removed records
    are read from the release itself."""
    total, items = ctx.release_svc.compared_records(
        name, kind, offset, min(limit, 500), collection
    )
    return ComparedRecordsResponse(
        total=total, items=[ComparedRecordResponse(**i) for i in items]
    )


@router.get(
    "/releases/{name}/compare/records/{record_id}",
    response_model=list[RecordDifferenceResponse],
)
def record_differences(name: str, record_id: str, ctx: AppContext = Depends(get_ctx)):
    """How one record differs from the release's copy of it, field by field
    (value in the release, value now), and its place when it moved."""
    return [
        RecordDifferenceResponse(**dataclasses.asdict(c))
        for c in ctx.release_svc.record_differences(name, record_id)
    ]


class ReleaseSaveRequest(BaseModel):
    folder: str | None = Field(
        default=None,
        description="The folder on this computer to put it in (any folder: an "
        "external drive, a shared folder); none: the project's own exports "
        "folder.",
    )
    open: bool = Field(
        default=True, description="Open the folder it is in when done (this machine)."
    )


class ReleaseSavedResponse(BaseModel):
    path: str = Field(description="Where the file was written.")
    opened: bool = Field(description="Whether its folder was opened.")


@router.post("/releases/{name}/save", response_model=ReleaseSavedResponse)
def save_release(
    name: str,
    body: ReleaseSaveRequest,
    request: Request,
    ctx: AppContext = Depends(get_ctx),
):
    """Write a release's bundle of records straight into a folder of this
    computer, instead of downloading it through the browser. 404 when it
    can't be had (or it was yanked) or there is no such folder; 422 when the
    folder can't be written to."""
    try:
        dest = ctx.file_access_svc.save_to(
            body.folder,
            ctx.release_svc.file_name_for(name),
            lambda path: ctx.release_svc.write_copy(name, path),
        )
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except CivexError as e:
        raise HTTPException(422, detail=str(e))
    opened = (
        body.open
        and OPEN_FOLDER in ctx.features
        and _from_this_machine(request)
        and fs_open.open_folder(dest.parent)
    )
    return ReleaseSavedResponse(path=str(dest), opened=bool(opened))


@router.get(
    "/releases/{name}/bundle",
    status_code=307,
    responses={307: {"description": "Where the bundle is downloaded from."}},
)
def download_release(name: str, ctx: AppContext = Depends(get_ctx)):
    """Download a release's bundle of records: answered with where it is
    (`/files/{bundle_sha256}`, named for the release), after fetching it from
    the server on a copy that hasn't got it. 404 when it can't be had (or it
    was yanked)."""
    release, here = ctx.release_svc.bundle_here(name)
    if not here:
        raise HTTPException(
            404,
            detail="The bundle is not on this computer and the server couldn't send it",
        )
    file_name = quote(ctx.release_svc.file_name_for(release.name))
    return RedirectResponse(
        f"../../files/{release.bundle_sha256}?filename={file_name}", status_code=307
    )
