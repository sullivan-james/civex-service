"""Helpers for tests that play devices against an authority."""

from __future__ import annotations

import json
import uuid
from typing import Any

from civex.domain.sync import ENTITY_ORDER, OpResult, PushResult, SyncEntry


def device_uuid(name: str) -> str:
    """A device id for a test device of this name: the same every time."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, name))


def wire(obj: Any) -> Any:
    """Send something over a wire: what arrives is what JSON would carry."""
    return json.loads(json.dumps(obj))


def join(authority, device) -> None:
    """Make `device` a copy of `authority` as it is now, as joining would."""
    for kind in ENTITY_ORDER:
        offset = 0
        while True:
            items = authority.sync_repo.snapshots_page(kind, offset, 200)
            for snap in items:
                device.sync_repo.apply_snapshot(kind, wire(snap))
            if len(items) < 200:
                break
            offset += 200
    device.sync_repo.set_cursor(authority.sync_repo.head_seq())
    device.sync_repo.mark_all_synced()
    device.commit()


def push(
    authority, device, name: str = "laptop", device_id: str | None = None
) -> PushResult:
    """Send everything `device` has not sent, to `authority`, and record the
    answers on the device, as the client does."""
    found = (
        authority.sync_repo.device_named(name)
        or authority.authority_svc.add_device(name)[0]
    )
    entries = [
        SyncEntry.from_dict(wire(e.to_dict()))
        for e in device.sync_repo.pending_entries(1000)
    ]
    result = authority.authority_svc.push(
        found, device_id or device_uuid(name), entries
    )
    authority.commit()
    result = PushResult.from_dict(wire(result.to_dict()))
    device.sync_repo.mark_sent(result.results)
    device.commit()
    return result


def statuses(result: PushResult) -> list[str]:
    return [r.status for r in result.results]


def by_status(result: PushResult, status: str) -> list[OpResult]:
    return [r for r in result.results if r.status == status]


def snapshots(ctx) -> dict[str, list[dict]]:
    return {k: ctx.sync_repo.snapshots_page(k, 0, 1000) for k in ENTITY_ORDER}


def new_id() -> str:
    return str(uuid.uuid4())
