"""Review status and notes on records (`civex.domain.review`)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from civex.context import AppContext
from civex.server.deps import get_ctx
from civex.server.models import (
    NoteRequest,
    NoteResolveRequest,
    NoteResponse,
    OpenNotesResponse,
    RecordQueryRequest,
    ReviewRequest,
    ReviewResponse,
)
from civex.server.routers.records import _selection

router = APIRouter(tags=["review"])


@router.post("/records/review", response_model=ReviewResponse)
def set_review(body: ReviewRequest, ctx: AppContext = Depends(get_ctx)):
    """Mark the chosen records (exactly `ids`, or every record the query lists)
    as needing a check, checked, or (`none`) not reviewed, as whoever is
    asking, now. Not an edit of the records' values: their last-changed date
    stays and no workflow starts. Records that already have the status are
    left as they are. Each record changed is in its history, the lot one event
    in Activity; it syncs."""
    result = ctx.record_svc.set_review(
        body.status, dry_run=body.dry_run, **_selection(body, "review")
    )
    if not body.dry_run:
        ctx.commit()
    return ReviewResponse(**result.to_dict())


@router.post("/records/open-notes", response_model=OpenNotesResponse)
def open_notes(body: RecordQueryRequest, ctx: AppContext = Depends(get_ctx)):
    """How many notes are not yet resolved, and on how many records, among the
    records the query lists."""
    return OpenNotesResponse(**ctx.note_svc.open_notes(body.to_query()).to_dict())


@router.get("/records/{record_id}/notes", response_model=list[NoteResponse])
def list_notes(
    record_id: str,
    include_resolved: bool = Query(
        default=True, description="Also list notes already resolved."
    ),
    ctx: AppContext = Depends(get_ctx),
):
    """A record's notes, oldest first."""
    return [
        NoteResponse.from_dto(n)
        for n in ctx.note_svc.notes(record_id, include_resolved)
    ]


@router.post("/records/{record_id}/notes", response_model=NoteResponse, status_code=201)
def add_note(record_id: str, body: NoteRequest, ctx: AppContext = Depends(get_ctx)):
    """Leave a note on a record, as whoever is asking. Needs permission to
    write records in its collection."""
    note = ctx.note_svc.add(record_id, body.body)
    ctx.commit()
    return NoteResponse.from_dto(note)


@router.patch("/notes/{note_id}", response_model=NoteResponse)
def edit_note(note_id: str, body: NoteRequest, ctx: AppContext = Depends(get_ctx)):
    """Change a note's words. Only its author may."""
    note = ctx.note_svc.edit(note_id, body.body)
    ctx.commit()
    return NoteResponse.from_dto(note)


@router.post("/notes/{note_id}/resolve", response_model=NoteResponse)
def resolve_note(
    note_id: str,
    body: NoteResolveRequest | None = None,
    ctx: AppContext = Depends(get_ctx),
):
    """Mark a note resolved, or (`resolved: false`) open it again."""
    note = ctx.note_svc.resolve(note_id, body.resolved if body else True)
    ctx.commit()
    return NoteResponse.from_dto(note)


@router.delete("/notes/{note_id}", response_model=NoteResponse)
def delete_note(note_id: str, ctx: AppContext = Depends(get_ctx)):
    """Delete a note. It stays in history and can be restored."""
    note = ctx.note_svc.delete(note_id)
    ctx.commit()
    return NoteResponse.from_dto(note)


@router.post("/notes/{note_id}/restore", response_model=NoteResponse)
def restore_note(note_id: str, ctx: AppContext = Depends(get_ctx)):
    """Bring back a deleted note."""
    note = ctx.note_svc.restore(note_id)
    ctx.commit()
    return NoteResponse.from_dto(note)
