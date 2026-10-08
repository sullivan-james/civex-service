"""Stopping this `civex serve` from another civex on this computer: an update
of the copy it runs from stops it the way Ctrl+C would, and starts it again
afterwards (`civex.running`)."""

from __future__ import annotations

import threading
import time

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from civex import running

router = APIRouter(prefix="/server", tags=["update"])


class StopResponse(BaseModel):
    stopping: bool = Field(description="The server is closing.")


@router.post("/stop", response_model=StopResponse, status_code=202)
def stop_server(
    token: str | None = Header(
        default=None,
        alias=running.STOP_HEADER,
        description="The token this server wrote where only its user can read "
        "it, when it started.",
    ),
) -> StopResponse:
    """Close this server, as Ctrl+C in its window would. Only for a request
    carrying the token it recorded when it started (403 otherwise): civex on
    this computer, updating the copy it runs from."""
    if not running.accepts_stop(token):
        raise HTTPException(403, detail="Not allowed")
    from civex.updates import _stop_server

    def _later() -> None:
        time.sleep(0.3)  # let this answer go first
        _stop_server()

    threading.Thread(target=_later, daemon=True).start()
    return StopResponse(stopping=True)
