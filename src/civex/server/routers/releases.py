"""Releases: frozen, citable copies of the data (`domain/release.py`).

Make one (after a plan of what it would hold), list them, read one's manifest
and citation, check its bundle still holds what it was made with, see what
changed since, correct its citation details, withdraw it, and download its
bundle (read into a new project with `POST /bundle/import` to get the data
back as it was)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from civex.context import AppContext
from civex.domain import release as rules
from civex.domain.dtos import ReleaseDTO
from civex.server.deps import get_ctx
from civex.server.models import RecordQueryRequest
from civex.server.routers.bundle import BundlePlanResponse
from civex.server.routers.file_access import report_progress
from civex.services.progress import Progress
from civex.services.release_service import ReleaseScope

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
    include_files: bool = Field(
        default=True, description="Carry the stored files the records cite."
    )
    include_workflows: bool = Field(
        default=True, description="Carry the project's workflows and plugins."
    )

    def scope(self) -> ReleaseScope:
        return ReleaseScope(
            collections=self.collections or None,
            query=self.query.to_query() if self.query else None,
        )


class ReleaseMetadata(BaseModel):
    title: str | None = Field(default=None, description="What the data is.")
    description: str | None = Field(default=None, description="A longer account.")
    authors: list[str] | None = Field(
        default=None, description="Authors' names, in citation order."
    )
    licence: str | None = Field(default=None, description="e.g. CC-BY-4.0.")
    doi: str | None = Field(default=None, description="A DOI, e.g. 10.1234/abcd.")


class ReleaseCreateRequest(ReleaseScopeRequest):
    name: str = Field(description="The version people cite, e.g. v1 or 2026-thesis.")
    title: str = Field(description="What the data is.")
    description: str | None = Field(default=None, description="A longer account.")
    authors: list[str] = Field(
        default_factory=list, description="Authors' names, in citation order."
    )
    licence: str | None = Field(default=None, description="e.g. CC-BY-4.0.")
    doi: str | None = Field(default=None, description="A DOI, if it has one.")


class WithdrawRequest(BaseModel):
    reason: str = Field(description="Why the release is withdrawn, in plain words.")


class ReleaseResponse(BaseModel):
    id: str
    name: str = Field(description="The version, e.g. v1.")
    title: str
    description: str | None
    authors: list[str]
    licence: str | None
    doi: str | None
    scope: dict[str, Any] = Field(
        description="{} the whole project, {collections: [...]}, or {query: {...}}."
    )
    include_files: bool
    content_hash: str = Field(
        description="sha256 over the bundle's contents (not its zip bytes): identical data, identical hash."
    )
    bundle_sha256: str = Field(
        description="The bundle file's own hash: where it is kept, and its download address under /files/."
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
    file_name: str = Field(description="The name a download is saved under.")

    @classmethod
    def from_dto(cls, r: ReleaseDTO) -> "ReleaseResponse":
        d = r.to_dict()
        d.setdefault("local_seq", None)
        return cls(**d, file_name=f"release-{r.name}.civex.zip")


class CitationResponse(BaseModel):
    text: str = Field(description="One paragraph for a reference list.")
    bibtex: str = Field(description="A BibTeX @misc entry.")
    cff: str = Field(description="CITATION.cff (Citation File Format 1.2.0).")


class VerifyResponse(BaseModel):
    name: str
    matches: bool = Field(description="The bundle holds exactly what it was made with.")
    expected: str = Field(description="The content hash recorded when it was made.")
    actual: str | None = Field(description="The content hash found now.")
    bundle_intact: bool = Field(
        description="The bundle's bytes match the hash it is kept under."
    )
    problems: list[str] = Field(description="What is wrong, in plain words.")


class CollectionChangesResponse(BaseModel):
    collection_id: str | None
    collection: str | None = Field(
        description="The collection's name now; None for records deleted for good."
    )
    added: int
    changed: int = Field(description="Edited, moved, or deleted and brought back.")
    deleted: int = Field(description="Deleted since, and still deleted (or gone).")
    in_scope: bool = Field(description="The collection is one the release covers.")


class ChangesSinceResponse(BaseModel):
    name: str
    comparable: bool = Field(description="Whether its place in history is known here.")
    by: str | None = Field(
        description="'feed' (the server's numbers) or 'local' (this copy's order)."
    )
    reason: str | None = Field(description="Why it can't be compared, when it can't.")
    added: int
    changed: int
    deleted: int
    collections: list[CollectionChangesResponse]
    structure: dict[str, int] = Field(
        description="History entries since about other kinds (schema, field, dataset, view...)."
    )


@router.get("/releases", response_model=list[ReleaseResponse])
def list_releases(ctx: AppContext = Depends(get_ctx)):
    """Every release, newest first."""
    return [ReleaseResponse.from_dto(r) for r in ctx.release_svc.list_all()]


@router.post("/releases/plan", response_model=BundlePlanResponse)
def plan_release(body: ReleaseScopeRequest, ctx: AppContext = Depends(get_ctx)):
    """What a release of this scope would hold, without making it: the
    bundle's own plan (counts, file sizes, files out of reach)."""
    plan = ctx.release_svc.plan(
        body.scope(), body.include_files, body.include_workflows
    )
    return BundlePlanResponse(**plan.to_dict())


@router.post("/releases", response_model=ReleaseResponse, status_code=201)
def create_release(
    body: ReleaseCreateRequest,
    progress: Progress | None = Depends(report_progress),
    ctx: AppContext = Depends(get_ctx),
):
    """Freeze the scope as a release: write its bundle, hash its contents, add
    a CITATION.cff, keep it in the project's storage and record the manifest.
    Needs permission to change the project's structure. Refused on a synced
    copy with changes the server hasn't got yet (sync first)."""
    made = ctx.release_svc.create(
        body.name,
        body.title,
        body.scope(),
        description=body.description,
        authors=body.authors,
        licence=body.licence,
        doi=body.doi,
        include_files=body.include_files,
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
    licence, DOI). Its content never changes; the correction is in history."""
    values = body.model_dump(exclude_unset=True)
    release = ctx.release_svc.correct(name, **values)
    ctx.commit()
    return ReleaseResponse.from_dto(release)


@router.post("/releases/{name}/withdraw", response_model=ReleaseResponse)
def withdraw_release(
    name: str, body: WithdrawRequest, ctx: AppContext = Depends(get_ctx)
):
    """Mark a release withdrawn, saying why. It and its bundle are kept."""
    release = ctx.release_svc.withdraw(name, body.reason)
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
def verify_release(name: str, ctx: AppContext = Depends(get_ctx)):
    """Read the stored bundle back and recompute its content hash (and every
    carried file's against its own): whether it still holds exactly what the
    release was made with. Fetches the bundle from the server first on a copy
    that hasn't got it."""
    return VerifyResponse(**ctx.release_svc.verify(name).to_dict())


@router.get("/releases/{name}/changes", response_model=ChangesSinceResponse)
def release_changes(name: str, ctx: AppContext = Depends(get_ctx)):
    """What changed in the project after the release was made: records added,
    changed and deleted per collection, and other kinds' changes, from
    history."""
    return ChangesSinceResponse(**ctx.release_svc.changes_since(name).to_dict())


@router.get(
    "/releases/{name}/bundle",
    status_code=307,
    responses={307: {"description": "Where the bundle is downloaded from."}},
)
def download_release(name: str, ctx: AppContext = Depends(get_ctx)):
    """Download a release's bundle: answered with where it is
    (`/files/{bundle_sha256}`, named for the release), after fetching it from
    the server on a copy that hasn't got it. 404 when it can't be had."""
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
