"""Notes on records, in threads (`civex.domain.notes`)."""

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
)

router = APIRouter(tags=["notes"])


@router.post("/records/open-notes", response_model=OpenNotesResponse)
def open_notes(body: RecordQueryRequest, ctx: AppContext = Depends(get_ctx)):
    """How many threads are not yet resolved, and on how many records, among
    the records the query lists (a note and its replies count once)."""
    return OpenNotesResponse(**ctx.note_svc.open_notes(body.to_query()).to_dict())


@router.get("/records/{record_id}/notes", response_model=list[NoteResponse])
def list_notes(
    record_id: str,
    include_resolved: bool = Query(
        default=True, description="Also list threads already resolved."
    ),
    ctx: AppContext = Depends(get_ctx),
):
    """A record's threads, oldest first: each note that starts one, with its
    replies, oldest first, in `replies`."""
    return [
        NoteResponse.from_dto(n)
        for n in ctx.note_svc.notes(record_id, include_resolved)
    ]


@router.post("/records/{record_id}/notes", response_model=NoteResponse, status_code=201)
def add_note(record_id: str, body: NoteRequest, ctx: AppContext = Depends(get_ctx)):
    """Leave a note on a record, starting a thread, as whoever is asking.
    Needs permission to write records in its collection."""
    note = ctx.note_svc.add(record_id, body.body)
    ctx.commit()
    return NoteResponse.from_dto(note)


@router.post("/notes/{note_id}/replies", response_model=NoteResponse, status_code=201)
def reply_to_note(note_id: str, body: NoteRequest, ctx: AppContext = Depends(get_ctx)):
    """Reply in the thread a note is in (the note that starts it, or any reply
    in it: a reply to a reply joins the same thread), as whoever is asking. A
    resolved thread opens again. Needs permission to write records in the
    record's collection."""
    note = ctx.note_svc.reply(note_id, body.body)
    ctx.commit()
    return NoteResponse.from_dto(note)


@router.patch("/notes/{note_id}", response_model=NoteResponse)
def edit_note(note_id: str, body: NoteRequest, ctx: AppContext = Depends(get_ctx)):
    """Change a note's or a reply's words. Only its author may."""
    note = ctx.note_svc.edit(note_id, body.body)
    ctx.commit()
    return NoteResponse.from_dto(note)


@router.post("/notes/{note_id}/resolve", response_model=NoteResponse)
def resolve_note(
    note_id: str,
    body: NoteResolveRequest | None = None,
    ctx: AppContext = Depends(get_ctx),
):
    """Mark the thread a note is in resolved, or (`resolved: false`) open it
    again. Answers the note that starts the thread."""
    note = ctx.note_svc.resolve(note_id, body.resolved if body else True)
    ctx.commit()
    return NoteResponse.from_dto(note)


@router.delete("/notes/{note_id}", response_model=NoteResponse)
def delete_note(note_id: str, ctx: AppContext = Depends(get_ctx)):
    """Delete a note or a reply. It stays in history and can be restored.
    Deleting the note that starts a thread hides its replies with it."""
    note = ctx.note_svc.delete(note_id)
    ctx.commit()
    return NoteResponse.from_dto(note)


@router.post("/notes/{note_id}/restore", response_model=NoteResponse)
def restore_note(note_id: str, ctx: AppContext = Depends(get_ctx)):
    """Bring back a deleted note (with its thread's replies, but those deleted
    by themselves) or a reply (only into a thread that is there)."""
    note = ctx.note_svc.restore(note_id)
    ctx.commit()
    return NoteResponse.from_dto(note)
