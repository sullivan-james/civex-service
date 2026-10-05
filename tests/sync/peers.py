"""Helpers for tests that play devices against an authority."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from civex.domain.sync import ENTITY_ORDER, OpResult, PushResult, SyncEntry, SyncError


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


class Loopback:
    """A transport that calls an authority in this process, carrying real JSON
    both ways, as a device on a network would see it."""

    def __init__(self, authority, token: str, device_id: str) -> None:
        self._authority = authority
        self._token = token
        self._device_id = device_id
        self.calls: list[str] = []

    def _svc(self):
        svc = self._authority.authority_svc
        self._device = svc.authenticate(self._token, self._device_id)
        return svc

    def _done(self, value):
        self._authority.commit()
        return wire(value)

    def hello(self):
        from civex.domain.sync import Hello

        self.calls.append("hello")
        return Hello.from_dict(self._done(self._svc().hello(self._device).to_dict()))

    def push(self, entries):
        from civex.domain.sync import PushResult

        self.calls.append("push")
        svc = self._svc()
        sent = [SyncEntry.from_dict(wire(e.to_dict())) for e in entries]
        result = svc.push(self._device, self._device_id, sent)
        return PushResult.from_dict(self._done(result.to_dict()))

    def feed(self, after, limit):
        from civex.domain.sync import FeedPage

        self.calls.append("feed")
        return FeedPage.from_dict(self._done(self._svc().feed(after, limit).to_dict()))

    def snapshot(self, kind, offset, limit):
        from civex.domain.sync import SnapshotPage

        self.calls.append("snapshot")
        page = self._svc().snapshot(kind, offset, limit)
        return SnapshotPage.from_dict(self._done(page.to_dict()))

    def missing_files(self, shas):
        self.calls.append("missing_files")
        return self._done(self._svc().missing_files(list(shas)))

    def upload_file(self, sha256, path):
        self.calls.append("upload_file")
        self._svc()
        stored = self._authority.file_svc.store_bytes(path.read_bytes(), "upload")
        assert stored.sha256 == sha256
        self._authority.commit()

    def download_file(self, sha256, dest):
        self.calls.append("download_file")
        self._svc()
        dest.write_bytes(self._authority.file_svc.retrieve(sha256))


class Flaky:
    """Wraps a transport and fails calls on purpose. `lose_reply` lets the call
    happen on the authority and then loses the answer (the nastiest failure: the
    device must not redo what was done); `refuse` fails before anything happens."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self._plan: dict[str, list[str]] = {}

    def clear(self) -> None:
        """Drop any faults still planned, so the network behaves again."""
        self._plan.clear()

    def fail(self, method: str, how: str = "refuse", times: int = 1) -> None:
        self._plan.setdefault(method, []).extend([how] * times)

    def __getattr__(self, name):
        target = getattr(self._inner, name)
        if not callable(target) or name.startswith("_") or name == "calls":
            return target

        def call(*args, **kwargs):
            plan = self._plan.get(name) or []
            how = plan.pop(0) if plan else None
            if how == "refuse":
                raise SyncError("The network is down")
            result = target(*args, **kwargs)
            if how == "lose_reply":
                raise SyncError("The connection dropped before the answer arrived")
            return result

        return call


class AsDevice:
    """A device's sync service, acting from its own machine: every call sees that
    device's own user state (its token and device id), not another's."""

    def __init__(self, service, state_file: Path) -> None:
        object.__setattr__(self, "_svc", service)
        object.__setattr__(self, "_state", state_file)

    def __getattr__(self, name):
        target = getattr(self._svc, name)
        if not callable(target):
            return target

        def call(*args, **kwargs):
            previous = os.environ.get("CIVEX_USER_STATE")
            os.environ["CIVEX_USER_STATE"] = str(self._state)
            try:
                return target(*args, **kwargs)
            finally:
                if previous is None:
                    os.environ.pop("CIVEX_USER_STATE", None)
                else:
                    os.environ["CIVEX_USER_STATE"] = previous

        return call


def device(project, authority, name, *, flaky: bool = False):
    """A new, empty project that syncs to `authority` over a loopback. Returns
    (context, transport) where the transport is the Flaky wrapper if asked."""
    ctx = project(name)
    _, token = authority.authority_svc.add_device(name)
    authority.commit()
    holder: dict = {}

    def factory(url, tok, device_id):
        # One transport per device id, so a fault planned on it outlives the
        # service asking for a fresh one each time it syncs.
        if holder.get("device_id") != device_id:
            inner = Loopback(authority, tok, device_id)
            holder["inner"] = inner
            holder["transport"] = Flaky(inner) if flaky else inner
            holder["device_id"] = device_id
        return holder["transport"]

    ctx.sync_svc._make_transport = factory
    root = ctx.sync_svc._config.project_root
    ctx.sync_svc = AsDevice(ctx.sync_svc, root.parent / f"{name}-user-state.toml")
    ctx._token = token  # type: ignore[attr-defined]
    ctx._holder = holder  # type: ignore[attr-defined]
    return ctx


def connect(ctx, authority_url: str = "http://authority.test") -> str:
    return ctx.sync_svc.connect(authority_url, ctx._token)


def flaky(ctx) -> Flaky:
    """The Flaky wrapper for a device made with flaky=True (after connect)."""
    return ctx._holder["transport"]
