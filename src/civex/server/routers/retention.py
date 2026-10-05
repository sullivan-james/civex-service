from __future__ import annotations

from fastapi import APIRouter, Depends

from civex.context import AppContext
from civex.server.deps import get_ctx
from civex.server.models import (
    ForgetPurgedRequest,
    ForgetPurgedResponse,
    RetentionReportResponse,
    RetentionRunRequest,
)

router = APIRouter(tags=["retention"])


@router.post("/retention/run", response_model=RetentionReportResponse)
def run_retention(body: RetentionRunRequest, ctx: AppContext = Depends(get_ctx)):
    """Clean up by age: permanently delete items deleted before a date, remove
    change history before a date, and remove finished workflow runs (with their
    step logs) before a date. `from_settings` applies the retention settings;
    a date given outright wins over the setting for that kind. With `dry_run`
    (the default) nothing is removed and the response says what would be.

    History about something that can still be restored is never removed. Files nothing
    refers to afterwards are the file clean-up's job (`/store/gc`)."""
    svc = ctx.retention_svc
    cutoffs = svc.cutoffs(
        body.from_settings, body.deleted_before, body.audit_before, body.runs_before
    )
    report = svc.run(cutoffs, dry_run=body.dry_run)
    if not body.dry_run:
        ctx.commit()
    return RetentionReportResponse.from_dto(report)


@router.post("/retention/purged-history", response_model=ForgetPurgedResponse)
def forget_purged(body: ForgetPurgedRequest, ctx: AppContext = Depends(get_ctx)):
    """Delete the history of records that were permanently deleted before
    permanent deletes removed it themselves: every entry about a record that no
    longer exists. Cannot be undone. With `dry_run` (the default) it only
    counts."""
    entries = ctx.retention_svc.forget_purged(dry_run=body.dry_run)
    if not body.dry_run:
        ctx.commit()
    return ForgetPurgedResponse(dry_run=body.dry_run, entries=entries)
