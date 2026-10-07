"""Helpers for tests that play devices against an authority."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from civex import keys, user_state
from civex.domain.sync import (
    ENTITY_ORDER,
    PROTOCOL_MAX,
    DeviceCredentials,
    Joined,
    OpResult,
    Principal,
    PushResult,
    SyncEntry,
    SyncError,
    session_answer,
    session_request,
    snapshot_cursor,
)


def device_uuid(name: str) -> str:
    """A device id for a test device of this name: the same every time."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, name))


def wire(obj: Any) -> Any:
    """Send something over a wire: what arrives is what JSON would carry."""
    return json.loads(json.dumps(obj))


def join(authority, device) -> None:
    """Make `device` a copy of `authority` as it is now, as joining would."""
    for kind in ENTITY_ORDER:
        after = None
        while True:
            items = authority.sync_repo.snapshots_page(kind, after, 200)
            for snap in items:
                device.sync_repo.apply_snapshot(kind, wire(snap))
            if len(items) < 200:
                break
            after = snapshot_cursor(items[-1])
    device.sync_repo.set_cursor(authority.sync_repo.head_seq())
    device.sync_repo.mark_all_synced()
    device.commit()


def push(
    authority, device, name: str = "laptop", device_id: str | None = None
) -> PushResult:
    """Send everything `device` has not sent, to `authority`, and record the
    answers on the device, as the client does."""
    entries = [
        SyncEntry.from_dict(wire(e.to_dict()))
        for e in device.sync_repo.pending_entries(1000)
    ]
    result = authority.authority_svc.push(
        principal(authority, name, device_id), entries
    )
    authority.commit()
    result = PushResult.from_dict(wire(result.to_dict()))
    device.sync_repo.mark_sent(result.results)
    device.commit()
    return result


def principal(authority, name: str, device_id: str | None = None) -> Principal:
    """The device called `name` as the authority's authenticator would prove
    it: allowed (given a token) the first time it is asked for."""
    device_id = device_id or device_uuid(name)
    found = authority.sync_repo.device_named(name) or authority.sync_repo.add_device(
        name, device_id, keys.public_of(keys.new_private_key())
    )
    return Principal(found.name, found.id, device_id)


def statuses(result: PushResult) -> list[str]:
    return [r.status for r in result.results]


def by_status(result: PushResult, status: str) -> list[OpResult]:
    return [r for r in result.results if r.status == status]


def snapshots(ctx) -> dict[str, list[dict]]:
    return {k: ctx.sync_repo.snapshots_page(k, None, 1000) for k in ENTITY_ORDER}


def new_id() -> str:
    return str(uuid.uuid4())


class Loopback:
    """A transport that calls an authority in this process, carrying real JSON
    both ways, as a device on a network would see it. It joins and signs in as
    the HTTP transport does: with the device's key, checking the authority's
    signature, and it is refused once the device is revoked."""

    def __init__(self, authority, credentials: DeviceCredentials) -> None:
        self._authority = authority
        self._credentials = credentials
        self._token: str | None = None
        self.calls: list[str] = []

    def join(self, invite):
        self.calls.append("join")
        creds = self._credentials
        joined = self._authority.device_keys.join(
            invite, creds.device_id, keys.public_of(creds.private_key)
        )
        self._authority.commit()
        joined = Joined.from_dict(wire(joined.to_dict()))
        self._credentials = replace(creds, authority_key=joined.authority_key)
        return joined

    def _svc(self):
        svc = self._authority.authority_svc
        if self._token is not None:
            try:
                self._device = svc.authenticate(self._token)
                return svc
            except SyncError:  # no longer good: sign in again, as HTTP does
                self._token = None
        self._sign_in()
        self._device = svc.authenticate(self._token)
        return svc

    def _sign_in(self) -> None:
        creds = self._credentials
        if self._token is None:
            if not creds.authority_key:
                raise SyncError("Not joined", retryable=False)
            at = int(time.time())
            signature = keys.sign(
                creds.private_key,
                session_request(creds.authority_key, creds.device_id, at),
            )
            grant = self._authority.device_keys.start_session(
                creds.device_id, at, signature
            )
            self._authority.commit()
            assert keys.verifies(
                creds.authority_key, session_answer(signature), grant.signature
            )
            self._token = grant.token

    def _done(self, value):
        self._authority.commit()
        return wire(value)

    def hello(self):
        from civex.domain.sync import Hello

        self.calls.append("hello")
        hello = self._svc().hello(self._device, PROTOCOL_MAX)
        return Hello.from_dict(self._done(hello.to_dict()))

    def push(self, entries):
        from civex.domain.sync import PushResult

        self.calls.append("push")
        svc = self._svc()
        sent = [SyncEntry.from_dict(wire(e.to_dict())) for e in entries]
        result = svc.push(self._device, sent)
        return PushResult.from_dict(self._done(result.to_dict()))

    def feed(self, after, limit):
        from civex.domain.sync import FeedPage

        self.calls.append("feed")
        return FeedPage.from_dict(self._done(self._svc().feed(after, limit).to_dict()))

    def snapshot(self, kind, after, limit):
        from civex.domain.sync import SnapshotPage

        self.calls.append("snapshot")
        page = self._svc().snapshot(kind, after, limit)
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

    def file_chunks(self, sha256):
        self.calls.append("file_chunks")
        self._svc()
        data = self._authority.file_svc.retrieve(sha256)  # FileNotFoundError
        return iter([data[i : i + 4096] for i in range(0, len(data), 4096)])


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
    """A new, empty project that syncs to `authority` over a loopback, invited
    as `name`. The transport is the Flaky wrapper if asked."""
    ctx = project(name)
    _, invite = authority.device_keys.invite(name)
    authority.commit()
    ctx._holder = {}  # type: ignore[attr-defined]
    _use(ctx, authority, flaky)
    root = ctx.sync_svc._config.project_root
    ctx.sync_svc = AsDevice(ctx.sync_svc, root.parent / f"{name}-user-state.toml")
    ctx._invite = invite  # type: ignore[attr-defined]
    return ctx


def _use(ctx, authority, flaky: bool = False) -> None:
    holder = ctx._holder

    def factory(url, credentials):
        # One transport per device, so a fault planned on it outlives the
        # service asking for a fresh one each time it syncs.
        if holder.get("device_id") != credentials.device_id:
            inner = Loopback(authority, credentials)
            holder["inner"] = inner
            holder["transport"] = Flaky(inner) if flaky else inner
            holder["device_id"] = credentials.device_id
        return holder["transport"]

    service = ctx.sync_svc
    if isinstance(service, AsDevice):  # the service itself, not the wrapper
        service = object.__getattribute__(service, "_svc")
    service._make_transport = factory


def follow(ctx, other, name):
    """Point the device `ctx` (made by `device`) at another authority, with an
    invite of its own there, as a person moving to a new server would."""
    _, invite = other.device_keys.invite(name)
    other.commit()
    ctx._holder.clear()
    _use(ctx, other)
    ctx._invite = invite


def connect(ctx, authority_url: str = "https://authority.test") -> str:
    """Connect as a person would: with the invite the first time, and without
    once this computer has joined that address."""
    state = object.__getattribute__(ctx.sync_svc, "_state")
    previous = os.environ.get("CIVEX_USER_STATE")
    os.environ["CIVEX_USER_STATE"] = str(state)
    try:
        joined = user_state.authority_for(authority_url) is not None
    finally:
        if previous is None:
            os.environ.pop("CIVEX_USER_STATE", None)
        else:
            os.environ["CIVEX_USER_STATE"] = previous
    return ctx.sync_svc.connect(authority_url, None if joined else ctx._invite)


def flaky(ctx) -> Flaky:
    """The Flaky wrapper for a device made with flaky=True (after connect)."""
    return ctx._holder["transport"]


def build_study(ctx):
    ctx.schema_svc.create("encounter")
    ctx.schema_svc.add_field("encounter", "site", "string")
    ctx.schema_svc.add_field("encounter", "depth", "float")
    ctx.dataset_svc.create("study")
    ctx.dataset_svc.update("study", schemas=["encounter"])
    record = ctx.record_svc.add("study", "encounter", {"site": "x", "depth": 1.0})
    ctx.commit()
    return record
