"""Sync's per-user state: what must not live in the project folder.

A project folder is copied, backed up and shared (a zip, a git repo, a NAS),
so what makes this machine a device stays out of it: its **device id** and its
**private key**, keyed by the project they belong to. If they lived in the
project, a copy of the project would be the same device as the original, and
the authority would take two machines' changes for one machine's. Beside them,
the **public key of each authority** this machine joined, by its address, so a
different server answering there is noticed.

All of it is kept in one small file in the user's home, `~/.civex/sync.toml`
(mode 0600; `CIVEX_USER_STATE` overrides the location, for tests and
containers).
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
    for table in ("devices", "keys", "authorities"):
        entries = data.get(table) or {}
        if entries:
            lines.append(f"[{table}]\n")
            for key, value in sorted(entries.items()):
                lines.append(f"{json.dumps(key)} = {json.dumps(value)}\n")
            lines.append("\n")
    tmp = path.with_suffix(".tmp")
    # Created private from the start: a private key must never be
    # world-readable, even for the instant between writing and tightening.
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


def device_key_for(project_id: uuid.UUID | str) -> str:
    """This machine's private key for this project: made the first time it is
    asked for, then the same every time. It never leaves this file."""
    from civex import keys

    data = _read()
    existing = (data.get("keys") or {}).get(str(project_id))
    if existing:
        return existing
    fresh = keys.new_private_key()
    _write({**data, "keys": {**(data.get("keys") or {}), str(project_id): fresh}})
    return fresh


def move_device(old: uuid.UUID | str, new: uuid.UUID | str) -> uuid.UUID:
    """A project that takes the authority's project id is still this machine:
    carry its device id and key across, so the authority (which knows them)
    still recognises it."""
    device = device_id_for(old)
    key = device_key_for(old)
    data = _read()
    tables = {}
    for table, value in (("devices", str(device)), ("keys", key)):
        entries = dict(data.get(table) or {})
        entries[str(new)] = value
        if str(old) != str(new):
            entries.pop(str(old), None)
        tables[table] = entries
    _write({**data, **tables})
    return device


def forget_device(project_id: uuid.UUID | str) -> None:
    data = _read()
    tables = {t: dict(data.get(t) or {}) for t in ("devices", "keys")}
    if any([entries.pop(str(project_id), None) for entries in tables.values()]):
        _write({**data, **tables})


def save_authority(remote: str, public_key: str) -> None:
    data = _read()
    known = dict(data.get("authorities") or {})
    known[remote.rstrip("/")] = public_key
    _write({**data, "authorities": known})


def authority_for(remote: str) -> str | None:
    """The public key of the authority this machine joined at that address."""
    return (_read().get("authorities") or {}).get(remote.rstrip("/"))


def forget_authority(remote: str) -> None:
    data = _read()
    known = dict(data.get("authorities") or {})
    if known.pop(remote.rstrip("/"), None) is not None:
        _write({**data, "authorities": known})
