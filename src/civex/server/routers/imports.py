from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends

from civex.context import AppContext
from civex.server.deps import get_ctx
from civex.server.models import (
    ImportBatchResponse,
    ImportInspectRequest,
    ImportRunRequest,
    ImportSheetResponse,
)

router = APIRouter(prefix="/import", tags=["import"])


@router.post("/inspect", response_model=ImportSheetResponse)
def inspect_spreadsheet(body: ImportInspectRequest, ctx: AppContext = Depends(get_ctx)):
    """Look inside an uploaded spreadsheet (CSV, TSV or Excel): its sheets, its
    columns with what each looks like, its first rows and how many rows it has.
    Upload it first with `PUT /files/stream`; nothing is read from a path."""
    return asdict(ctx.import_svc.inspect(body.sha256, body.filename, body.sheet))


@router.post("/run", response_model=ImportBatchResponse)
def import_rows(body: ImportRunRequest, ctx: AppContext = Depends(get_ctx)):
    """Bring in a part of the spreadsheet (`start`, `limit`) as records, making
    the kind of record and fields the choices call for if they aren't there. Call
    again with the next `start` until `done`. With `check`, nothing is kept: the
    answer is what the same call without it will give. Send an `X-Civex-Batch`
    header (see `POST /audit/batches`) so the whole import is one event in
    history."""
    return asdict(
        ctx.import_svc.run(body.spec(), body.start, body.limit, check=body.check)
    )
