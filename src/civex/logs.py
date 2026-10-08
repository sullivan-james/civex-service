"""Every log civex writes, in one place: what each is, where it lives, and its
latest lines.

civex writes several logs, each where the thing that writes it can put it:

- **project**: this project's server (`_civex/logs/civex.log`, JSON lines,
  rotated at 5 MB), `[logging] to_file`.
- **desktop**: the desktop app's window (`civex-desktop.log`, beside the
  launcher's log when the launcher started it).
- **launcher**: the desktop app's launcher: installing and updating civex
  (`<app folder>/logs/launcher.log`).
- **update**: updates run after `civex serve` exits (`~/.civex/update.log`).
- **serve-<port>**: servers started again after an update, off Windows, where
  they have no window of their own (`~/.civex/serve-<port>.log`).

A workflow run's log is kept with the run (its page), not here.

A log is only ever read by its id from `sources`, never by a path a caller
supplies, so nothing else on the computer can be read through this.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from civex.domain.exceptions import NotFoundError

MAX_LINES = 5000
_TAIL_BYTES = 8 * 1024 * 1024  # never read more than this from the end

LEVELS = ("debug", "info", "warning", "error", "critical")
_LEVEL = re.compile(r"\b(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL)\b")
_TIME = re.compile(
    r"^\[?(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\]?\s*"
)


@dataclass(frozen=True)
class LogSource:
    id: str
    name: str
    about: str
    path: Path
    json_lines: bool = False

    def describe(self) -> dict[str, Any]:
        try:
            stat = self.path.stat()
            size, modified = (
                stat.st_size,
                datetime.fromtimestamp(stat.st_mtime, timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            )
        except OSError:
            size, modified = None, None
        return {
            "id": self.id,
            "name": self.name,
            "about": self.about,
            "path": str(self.path),
            "exists": size is not None,
            "size": size,
            "modified": modified,
        }


@dataclass(frozen=True)
class LogLine:
    time: str | None
    level: str | None  # lower case, one of LEVELS, when the line says
    message: str
    #: A JSON line's other fields (logger, request id, error, ...).
    fields: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "time": self.time,
            "level": self.level,
            "message": self.message,
            "fields": self.fields,
        }


def _desktop_log() -> Path:
    from civex.updates import app_home

    candidates = []
    if folder := os.environ.get("CIVEX_LOG_DIR"):
        candidates.append(Path(folder) / "civex-desktop.log")
    candidates += [
        app_home() / "logs" / "civex-desktop.log",
        Path.home() / ".config" / "civex" / "civex-desktop.log",
    ]
    return next((c for c in candidates if c.is_file()), candidates[0])


def sources(civex_dir: Path | None) -> list[LogSource]:
    """The logs there are on this computer for this project. The project's
    own log is always listed (it says so if nothing has been written yet);
    the others only where they exist."""
    from civex.updates import app_home, result_path

    found: list[LogSource] = []
    if civex_dir is not None:
        found.append(
            LogSource(
                "project",
                "This project's server",
                "What the civex server did for this project: requests, background "
                "work (sync, file moves, workflow runs) and errors.",
                civex_dir / "logs" / "civex.log",
                json_lines=True,
            )
        )
    optional = [
        LogSource(
            "desktop",
            "Desktop app",
            "The desktop app's window: opening projects and its own errors.",
            _desktop_log(),
        ),
        LogSource(
            "launcher",
            "Desktop app launcher",
            "Installing and updating the desktop app's civex.",
            app_home() / "logs" / "launcher.log",
        ),
        LogSource(
            "update",
            "Updates",
            "Updates of a civex started with `civex serve`, run after it closed.",
            result_path().with_name("update.log"),
        ),
    ]
    found += [s for s in optional if s.path.is_file()]
    for path in sorted(result_path().parent.glob("serve*.log")):
        port = path.stem.partition("-")[2]
        found.append(
            LogSource(
                path.stem,
                f"Server started again{f' (port {port})' if port else ''}",
                "A `civex serve` that an update stopped and started again: its "
                "output, since it has no window of its own here.",
                path,
            )
        )
    return found


def find(civex_dir: Path | None, log_id: str) -> LogSource:
    for source in sources(civex_dir):
        if source.id == log_id:
            return source
    raise NotFoundError(f"There is no log called '{log_id}' here")


def _tail_text(path: Path, lines: int) -> list[str]:
    """The last `lines` lines, read from the end (a log can be large)."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            block, data = 64 * 1024, b""
            while end > 0 and data.count(b"\n") <= lines and len(data) < _TAIL_BYTES:
                start = max(0, end - block)
                f.seek(start)
                data = f.read(end - start) + data
                end = start
    except OSError:
        return []
    text = data.decode("utf-8", errors="replace").splitlines()
    if end > 0 and text:
        text = text[1:]  # the first may be cut part way
    return text[-lines:]


def _parse(raw: str, json_lines: bool) -> LogLine:
    if json_lines and raw.startswith("{"):
        try:
            record = json.loads(raw)
        except ValueError:
            record = None
        if isinstance(record, dict):
            level = str(record.pop("level", "") or "").lower() or None
            return LogLine(
                time=record.pop("timestamp", None),
                level=level if level in LEVELS else None,
                message=str(record.pop("event", "") or ""),
                fields=record,
            )
    time = None
    rest = raw
    if match := _TIME.match(raw):
        time, rest = match.group(1), raw[match.end() :]
    level = None
    if match := _LEVEL.search(rest[:40]):
        word = match.group(1).lower()
        level = "warning" if word == "warn" else word
    return LogLine(time=time, level=level, message=rest, fields={})


def read(
    source: LogSource,
    lines: int = 500,
    level: str | None = None,
    q: str | None = None,
) -> list[LogLine]:
    """A log's latest lines, oldest first: at most `lines` of those at or above
    `level`, containing `q` (any case)."""
    lines = max(1, min(lines, MAX_LINES))
    wanted = LEVELS.index(level) if level in LEVELS else None
    needle = (q or "").strip().lower()
    # Read more than asked when filtering, so a filter still finds `lines`.
    raw = _tail_text(source.path, lines * (10 if wanted is not None or needle else 1))
    out = []
    for text in raw:
        if not text.strip():
            continue
        line = _parse(text, source.json_lines)
        if wanted is not None and (
            line.level is None or LEVELS.index(line.level) < wanted
        ):
            continue
        if needle and needle not in text.lower():
            continue
        out.append(line)
    return out[-lines:]
