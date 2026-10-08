"""Every log civex writes, for people: which there are, their latest lines,
downloading one, and opening its folder (`civex.logs`)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from civex import fs_open, logs
from civex.config import find_project_root
from civex.domain.exceptions import NotFoundError
from civex.domain.hosts import is_loopback

router = APIRouter(prefix="/logs", tags=["logs"])


class LogSourceResponse(BaseModel):
    id: str = Field(description="What to ask for it by.")
    name: str
    about: str = Field(description="What writes it.")
    path: str = Field(description="Where it is on this computer.")
    exists: bool = Field(description="Something has been written to it.")
    size: int | None = Field(description="Its size in bytes.")
    modified: str | None = Field(description="When it was last written (UTC).")


class LogLineResponse(BaseModel):
    time: str | None
    level: str | None = Field(
        description="debug, info, warning, error or critical, when the line says."
    )
    message: str
    fields: dict = Field(
        default_factory=dict,
        description="A structured line's other fields (logger, request id, ...).",
    )


class LogReadResponse(BaseModel):
    source: LogSourceResponse
    lines: list[LogLineResponse] = Field(description="The latest lines, oldest first.")


def _civex_dir() -> Path | None:
    root = find_project_root()
    return root / "_civex" if root else None


def _find(log_id: str) -> logs.LogSource:
    try:
        return logs.find(_civex_dir(), log_id)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))


@router.get("", response_model=list[LogSourceResponse])
def list_logs() -> list[LogSourceResponse]:
    """The logs civex keeps on this computer, for this project and the app."""
    return [LogSourceResponse(**s.describe()) for s in logs.sources(_civex_dir())]


@router.get("/{log_id}", response_model=LogReadResponse)
def read_log(
    log_id: str,
    lines: int = Query(default=500, ge=1, le=logs.MAX_LINES),
    level: str | None = Query(
        default=None, description="Only lines at this level or above."
    ),
    q: str | None = Query(default=None, description="Only lines containing this."),
) -> LogReadResponse:
    """A log's latest lines, oldest first."""
    source = _find(log_id)
    return LogReadResponse(
        source=LogSourceResponse(**source.describe()),
        lines=[
            LogLineResponse(**line.to_dict())
            for line in logs.read(source, lines, level, q)
        ],
    )


@router.get("/{log_id}/download")
def download_log(log_id: str) -> FileResponse:
    """The whole log file, to keep or send to someone."""
    source = _find(log_id)
    if not source.path.is_file():
        raise HTTPException(404, detail="Nothing has been written to it yet")
    return FileResponse(source.path, media_type="text/plain", filename=source.path.name)


@router.post("/{log_id}/open")
def open_log_folder(log_id: str, request: Request) -> dict[str, bool]:
    """Show the log's folder in the file manager, when asked from this
    computer (`opened` false otherwise, or with nothing to open it with)."""
    source = _find(log_id)
    here = is_loopback(request.client.host) if request.client else False
    folder = source.path.parent
    opened = here and folder.is_dir() and fs_open.open_folder(folder)
    return {"opened": bool(opened)}
