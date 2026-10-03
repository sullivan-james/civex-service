"""Moving stored files between volumes: preview it, start it, watch it, pause it."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from civex.context import AppContext
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.domain.transfers import TransferRecord, TransferSpec
from civex.server.deps import get_ctx
from civex.server.models import TransferPlanResponse, TransferRequest, TransferResponse
from civex.services.transfer_jobs import jobs

router = APIRouter(prefix="/store/transfers", tags=["store"])


def _spec(body: TransferRequest) -> TransferSpec:
    return TransferSpec(**body.model_dump())


def _response(record: TransferRecord) -> TransferResponse:
    data = record.to_dict()
    data["live"] = jobs.is_live(record.id)
    if data.get("plan") is not None:
        data["plan"]["can_proceed"] = record.plan.can_proceed  # type: ignore[union-attr]
    return TransferResponse(**data)


@router.post("/preview", response_model=TransferPlanResponse)
def preview_transfer(body: TransferRequest, ctx: AppContext = Depends(get_ctx)):
    """What a transfer would do, without doing anything.

    Reports how many files and bytes would move and where each target would put
    them, and lists `problems` that would stop it (a volume that is offline or
    read-only, not enough room, another transfer running) and `warnings` that
    are worth knowing. The sizes come from the catalog, so they are close, not
    exact.
    """
    plan = ctx.transfer_svc.plan(_spec(body))
    return {**asdict(plan), "can_proceed": plan.can_proceed}


@router.post("", response_model=TransferResponse, status_code=202)
def start_transfer(body: TransferRequest):
    """Start moving files between volumes, in the background.

    Poll `GET /store/transfers/{id}` for progress. A file is only removed from
    its source after the copy has been checked and recorded, so a transfer can
    be paused, cancelled, interrupted or lose power at any moment without losing
    anything. Refused (422) with every reason if it can't start.
    """
    return _response(jobs.start(_spec(body)))


@router.get("", response_model=list[TransferResponse])
def list_transfers(ctx: AppContext = Depends(get_ctx)):
    """Past and running transfers, newest first."""
    return [_response(r) for r in ctx.transfer_svc.recent()]


@router.get("/{transfer_id}", response_model=TransferResponse)
def get_transfer(transfer_id: str, ctx: AppContext = Depends(get_ctx)):
    """A transfer's progress and outcome: files and bytes done, speed and time
    remaining, the file being copied, anything that couldn't be moved, and why
    it is paused if it is. A running transfer that has stopped saving progress
    (its process died) is reported as `interrupted`."""
    return _response(ctx.transfer_svc.get(transfer_id))


@router.post("/{transfer_id}/pause", response_model=TransferResponse)
def pause_transfer(transfer_id: str, ctx: AppContext = Depends(get_ctx)):
    """Ask a running transfer to pause. It stops within a moment, discarding any
    half-copied file, and keeps everything already moved. Works for a transfer
    started from the command line as well as one running here."""
    if not jobs.pause(transfer_id):
        raise HTTPException(409, detail="It isn't running.")
    return _response(ctx.transfer_svc.get(transfer_id))


@router.post("/{transfer_id}/resume", response_model=TransferResponse, status_code=202)
def resume_transfer(transfer_id: str):
    """Carry on a paused, failed or interrupted transfer where it left off. What
    is already moved is not moved again."""
    return _response(jobs.resume(transfer_id))


@router.post("/{transfer_id}/cancel", response_model=TransferResponse)
def cancel_transfer(transfer_id: str, ctx: AppContext = Depends(get_ctx)):
    """Stop a transfer for good. Nothing already moved is moved back and no file
    is lost; volumes it made read-only are restored."""
    try:
        jobs.cancel(transfer_id)
    except (NotFoundError, ValidationError):
        raise
    return _response(ctx.transfer_svc.get(transfer_id))
