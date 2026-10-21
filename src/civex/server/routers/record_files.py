"""A file and the record change it is for, as one request.

`PUT /files/stream` stores bytes and a later `PATCH /records/{id}` cites them;
between the two the record may refuse the save (a unique key, a value a field
won't take, a required field the file's name didn't fill), and the bytes are
already stored, as an orphan, after a progress bar said the file went in.
These routes take the file and the record change together: the bytes are
stored, the record saved through `RecordService` (so `from_filename`,
validation, unique keys and triggers all run), and when the save is refused
the content is removed again if it was new, nothing of the record change is
kept, and the answer is the field error the plain record routes give.

A crash between storing the bytes and the commit leaves an orphan blob, which
the clean-up (`GCService`) finds like any other; that is accepted.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterable, AsyncIterator, Callable
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from starlette.datastructures import UploadFile
from pydantic import ValidationError as PydanticValidationError

from civex.context import AppContext, context_factory
from civex.domain.dtos import FileRef, RecordDTO
from civex.domain.exceptions import (
    AllVolumesFull,
    CivexError,
    NotFoundError,
    ValidationError,
    VolumeUnavailableError,
)
from civex.server.background import run_pending_jobs
from civex.server.deps import get_ctx
from civex.server.models import CreateRecordRequest, RecordResponse

router = APIRouter(tags=["records"])

_UPLOAD_CHUNK = 1024 * 1024
_FILE_TYPES = ("file", "file_list")


class _Hashing:
    """A stream of chunks passed through as they come, hashed on the way, so
    that once it has ended we know the content's sha256 and whether the store
    already held it. The store asks for the chunk after the last one before
    it finalises the file, so `existed` is answered before the content is
    recorded as stored: what "was it new?" means for undoing the store."""

    def __init__(
        self, chunks: AsyncIterable[bytes], store_has: Callable[[str], bool]
    ) -> None:
        self._chunks = chunks
        self._store_has = store_has
        self.sha256: str | None = None
        self.existed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        h = hashlib.sha256()
        async for chunk in self._chunks:
            h.update(chunk)
            yield chunk
        self.sha256 = h.hexdigest()
        self.existed = self._store_has(self.sha256)


async def _read_chunks(file: UploadFile) -> AsyncIterator[bytes]:
    while chunk := await file.read(_UPLOAD_CHUNK):
        yield chunk


def _undo_stores(ctx: AppContext, stored: list[tuple[FileRef, bool]]) -> None:
    """Remove the content stored by this request that was new, then forget
    the request's changes. The blob goes first, while its inventory row is
    still in the session to say where it is; the rollback then undoes that
    row with the rest. Content that was already in the store (another record
    uses it, or it was uploaded before) is never touched."""
    for ref, existed in stored:
        if not existed:
            ctx.file_svc.discard(ref.sha256)
    ctx.rollback()


def _file_field(ctx: AppContext, schema_name: str, field: str) -> str:
    """The dtype of `field` on `schema_name`, which must be a file field."""
    shape = ctx.schema_svc.resolve(ctx.schema_svc.get(schema_name))
    found = shape.by_name.get(field)
    if found is None:
        raise NotFoundError(f"Field '{field}' not found on schema '{schema_name}'")
    if found.dtype not in _FILE_TYPES:
        raise ValidationError(f"Field '{field}' is a {found.dtype} field, not a file")
    return found.dtype


def _with_file(
    data: dict[str, Any], field: str, dtype: str, ref: FileRef
) -> dict[str, Any]:
    """`data` with `ref` on `field`: appended to a list of files, in place of
    the file of a single-file field."""
    out = dict(data)
    if dtype == "file_list":
        current = out.get(field)
        out[field] = [*(current if isinstance(current, list) else []), ref.to_dict()]
    else:
        out[field] = ref.to_dict()
    return out


def _after(ctx: AppContext, background_tasks: BackgroundTasks, dto: RecordDTO):
    ctx.commit()
    background_tasks.add_task(run_pending_jobs, context_factory(ctx.project))
    return RecordResponse.from_dto(dto)


@router.put("/records/{record_id}/files/{field}", response_model=RecordResponse)
async def attach_file(
    record_id: str,
    field: str,
    request: Request,
    background_tasks: BackgroundTasks,
    name: str = Query(default="upload", description="The file's name."),
    size: int | None = Query(
        default=None,
        description="The file's size in bytes, so a volume with room is picked "
        "before anything is written; the Content-Length is used when absent.",
    ),
    ctx: AppContext = Depends(get_ctx),
):
    """Add one file to a record's file field and save the record, as one
    request. The raw body is the file, streamed to storage as `PUT
    /files/stream` streams it; the record is then saved with the file on
    `field` (appended to a `file_list`, replacing the file of a `file`), so
    fields filled from the file's name, the field's rules, unique keys and
    workflow triggers all apply. A refused save (422, the field error as
    `PATCH /records/{id}` gives it) stores nothing: the content is removed
    again unless it was already in the store, and the record is unchanged.
    The file is placed as a file of the record's collection."""
    try:
        record = ctx.record_svc.get(record_id)
        dtype = _file_field(ctx, record.schema_name, field)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    if size is None:
        try:
            size = int(request.headers.get("content-length", ""))
        except ValueError:
            size = None
    hashing = _Hashing(request.stream(), ctx.file_svc.exists)
    try:
        ref = await ctx.file_svc.store_stream(
            hashing, name or "upload", size, str(record.dataset_id)
        )
    except (AllVolumesFull, VolumeUnavailableError) as e:
        raise HTTPException(507, detail=str(e))
    try:
        dto = ctx.record_svc.patch(
            record_id, {field: _with_file(record.data, field, dtype, ref)[field]}
        )
    except CivexError:
        _undo_stores(ctx, [(ref, hashing.existed)])
        raise  # answered by the app's handler: 422 for a value refused, as PATCH
    return _after(ctx, background_tasks, dto)


@router.post(
    "/collections/{dataset_name}/records/with-files",
    response_model=RecordResponse,
    status_code=201,
)
async def create_record_with_files(
    dataset_name: str,
    request: Request,
    background_tasks: BackgroundTasks,
    ctx: AppContext = Depends(get_ctx),
):
    """Create a record and its files in one request. Multipart: a `record`
    part holding the JSON `POST /collections/{c}/records` takes
    (`schema_name`, `data`, `parent_record_id`), and a part per file named
    for the field it goes in (several parts for a `file_list`). The files are
    stored, then the record is created with them, so what the plain route
    checks is checked here; if it is refused (422), every file this request
    stored that was new is removed again and no record is made. Files are
    placed as files of the collection."""
    form = await request.form()
    raw = form.get("record")
    try:
        if not isinstance(raw, str):
            raise ValueError("a 'record' part is needed")
        body = CreateRecordRequest.model_validate_json(raw)
    except (ValueError, PydanticValidationError) as e:
        raise HTTPException(422, detail=f"The record part can't be read: {e}")
    try:
        dataset = ctx.dataset_svc.get(dataset_name)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    stored: list[tuple[FileRef, bool]] = []
    data = dict(body.data)
    try:
        for key, part in form.multi_items():
            if key == "record":
                continue
            if not isinstance(part, UploadFile):
                raise ValidationError(f"Part '{key}' is not a file")
            dtype = _file_field(ctx, body.schema_name, key)
            hashing = _Hashing(_read_chunks(part), ctx.file_svc.exists)
            ref = await ctx.file_svc.store_stream(
                hashing, part.filename or "upload", part.size, str(dataset.id)
            )
            stored.append((ref, hashing.existed))
            data = _with_file(data, key, dtype, ref)
        dto = ctx.record_svc.add(
            dataset_name,
            body.schema_name,
            data,
            parent_record_id=body.parent_record_id,
        )
    except (AllVolumesFull, VolumeUnavailableError) as e:
        _undo_stores(ctx, stored)
        raise HTTPException(507, detail=str(e))
    except CivexError:
        _undo_stores(ctx, stored)
        raise  # 404 for a missing schema or field, 422 for a value refused
    return _after(ctx, background_tasks, dto)
