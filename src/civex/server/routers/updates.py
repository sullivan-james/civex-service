from __future__ import annotations

import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from civex import updates

router = APIRouter(prefix="/update", tags=["update"])


class UpdateAttempt(BaseModel):
    at: str = Field(description="When it finished (UTC, `YYYY-MM-DDTHH:MM:SSZ`).")
    from_version: str = Field(description="The version it updated from.")
    to_version: str | None = Field(description="The version installed afterwards.")
    ok: bool = Field(description="Whether a newer version was installed.")
    message: str = Field(description="What went wrong; blank when it worked.")


class UpdateStatusResponse(BaseModel):
    current: str = Field(description="The version running now.")
    latest: str | None = Field(
        description="The newest version on PyPI (pre-releases too when asked "
        "for); null when PyPI couldn't be reached."
    )
    newer: bool = Field(description="Whether `latest` is newer than `current`.")
    pre: bool = Field(description="Whether pre-releases were looked for.")
    installer: str = Field(
        description="How this copy was installed: desktop, frozen, editable, "
        "pipx, uv or pip."
    )
    can_update: bool = Field(description="Whether the app can update this copy.")
    blocked: str = Field(description="Why it can't, in plain words; blank when it can.")
    error: str = Field(description="Why PyPI couldn't be asked; blank when it was.")
    last: UpdateAttempt | None = Field(
        description="The outcome of the last update started from the app, "
        "while it is news (until civex moves on from both its versions, or it "
        "is dismissed)."
    )
    running: list[str] = Field(
        default_factory=list,
        description="Other servers running from this copy: updating stops them "
        "and starts them again afterwards.",
    )


class StartUpdateRequest(BaseModel):
    pre: bool = Field(False, description="Install a pre-release if it is the newest.")
    version: str | None = Field(
        None, description="The version to install: the one the status showed."
    )
    stop_others: bool = Field(
        False,
        description="Stop the other servers running from this copy, and start "
        "them again afterwards. Without it, an update with any refuses (409).",
    )


class StartUpdateResponse(BaseModel):
    restarting: bool = Field(
        description="civex is closing to update and will start again; poll "
        "`/health` and reload when it answers."
    )


def _attempt(last: dict[str, Any] | None) -> UpdateAttempt | None:
    if not last:
        return None
    try:
        return UpdateAttempt(
            at=str(last.get("at", "")),
            from_version=str(last.get("from", "")),
            to_version=last.get("to"),
            ok=bool(last.get("ok")),
            message=str(last.get("message", "")),
        )
    except ValueError:
        return None


@router.get("", response_model=UpdateStatusResponse)
def update_status(
    pre: bool = Query(False, description="Look for pre-releases too."),
) -> UpdateStatusResponse:
    """Whether a newer civex is available, and whether this copy can install it
    from the app (the same check as `civex update --check`)."""
    found = updates.check(pre=pre)
    return UpdateStatusResponse(
        current=found.current,
        latest=found.latest,
        newer=found.newer,
        pre=found.pre,
        installer=found.installer,
        can_update=not found.blocked,
        blocked=found.blocked,
        error=found.error,
        last=_attempt(found.last),
        running=found.running,
    )


@router.post("", response_model=StartUpdateResponse, status_code=202)
def start_update(body: StartUpdateRequest) -> StartUpdateResponse:
    """Update civex and start it again. civex closes once this answers; the
    update runs after it has exited (a running copy can't be replaced on
    Windows), and its outcome is in `last` on the next status. 409 when this
    copy can't be updated from the app (`blocked` says why)."""
    try:
        exit_now = updates.begin(
            pre=body.pre, version=body.version, stop=body.stop_others
        )
    except RuntimeError as e:
        raise HTTPException(409, detail=str(e))

    def _later() -> None:
        time.sleep(0.5)  # let this answer reach the browser first
        exit_now()

    threading.Thread(target=_later, daemon=True).start()
    return StartUpdateResponse(restarting=True)


@router.delete("/last", status_code=204)
def dismiss_last() -> None:
    """Forget the outcome of the last update: it was seen."""
    updates.dismiss_last()
