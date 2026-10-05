"""Sync's per-user state: what must not live in the project folder.

A project folder is copied, backed up and shared (a zip, a git repo, a NAS),
so two things stay out of it: the **token** a device was given for an authority
(a secret), and the **device id** (an identity). If the id lived in the project,
a copy of the project would be the same device as the original, and the
authority would take two machines' changes for one machine's.

Both are kept in one small file in the user's home, `~/.civex/sync.toml`
(mode 0600; `CIVEX_USER_STATE` overrides the location, for tests and
containers), the device id keyed by the project it belongs to.
"""

from __future__ import annotations

import os
import tomllib
import uuid
from pathlib import Path
from typing import Any


def state_path() -> Path:
    override = os.environ.get("CIVEX_USER_STATE")
    return Path(override) if override else Path.home() / ".civex" / "sync.toml"


def _read() -> dict[str, Any]:
    try:
        return tomllib.loads(state_path().read_text("utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _write(data: dict[str, Any]) -> None:
    import json

    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for table in ("devices", "tokens", "actors"):
        entries = data.get(table) or {}
        if entries:
            lines.append(f"[{table}]\n")
            for key, value in sorted(entries.items()):
                lines.append(f"{json.dumps(key)} = {json.dumps(value)}\n")
            lines.append("\n")
    tmp = path.with_suffix(".tmp")
    # Created private from the start: a token must never be world-readable, even
    # for the instant between writing and tightening.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("".join(lines))
    os.replace(tmp, path)


def device_id_for(project_id: uuid.UUID | str) -> uuid.UUID:
    """This machine's id for this project: made the first time it is asked for,
    then the same every time."""
    data = _read()
    key = str(project_id)
    existing = (data.get("devices") or {}).get(key)
    if existing:
        try:
            return uuid.UUID(existing)
        except ValueError:
            pass
    fresh = uuid.uuid4()
    devices = dict(data.get("devices") or {})
    devices[key] = str(fresh)
    _write({**data, "devices": devices})
    return fresh


def move_device(old: uuid.UUID | str, new: uuid.UUID | str) -> uuid.UUID:
    """A project that takes the authority's project id is still this machine:
    carry its device id across, so the authority (which bound a token to it)
    still recognises it."""
    device = device_id_for(old)
    data = _read()
    devices = dict(data.get("devices") or {})
    devices[str(new)] = str(device)
    actors = dict(data.get("actors") or {})
    if str(old) != str(new):
        devices.pop(str(old), None)
        if str(old) in actors:
            actors[str(new)] = actors.pop(str(old))
    _write({**data, "devices": devices, "actors": actors})
    return device


def actor_for(project_id: uuid.UUID | str) -> str | None:
    """The name this user chose to appear as on changes to this project, if any
    (otherwise the caller falls back to the operating-system user)."""
    value = (_read().get("actors") or {}).get(str(project_id))
    return value or None


def set_actor(project_id: uuid.UUID | str, name: str | None) -> None:
    """Choose, or with None/blank clear, the name for this project. It is per
    user and per project, so it lives here, not in the shared project folder."""
    data = _read()
    actors = dict(data.get("actors") or {})
    if name and name.strip():
        actors[str(project_id)] = name.strip()[:100]
    else:
        actors.pop(str(project_id), None)
    _write({**data, "actors": actors})


def forget_device(project_id: uuid.UUID | str) -> None:
    data = _read()
    devices = dict(data.get("devices") or {})
    if devices.pop(str(project_id), None) is not None:
        _write({**data, "devices": devices})


def save_token(remote: str, token: str) -> None:
    data = _read()
    tokens = dict(data.get("tokens") or {})
    tokens[remote.rstrip("/")] = token
    _write({**data, "tokens": tokens})


def token_for(remote: str) -> str | None:
    return (_read().get("tokens") or {}).get(remote.rstrip("/"))


def forget_token(remote: str) -> None:
    data = _read()
    tokens = dict(data.get("tokens") or {})
    if tokens.pop(remote.rstrip("/"), None) is not None:
        _write({**data, "tokens": tokens})
