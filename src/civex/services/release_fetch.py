"""Fetching a release's bundle from a civex host: what `civex clone <url>
--release NAME` does before reading it into a new project.

A host serves each release as one bundle with its files (`GET
/releases/{name}/bundle`, `routers/releases.py`), the same file `civex bundle
import` reads, so over plain HTTPS this is a download and nothing more: no
device is made, nothing is joined, nothing stays connected. The bundle is
written to disk in chunks, never held in memory.
"""

from __future__ import annotations

import http.client
import socket
import urllib.parse
from collections.abc import Callable
from pathlib import Path

from civex.domain.hosts import is_loopback
from civex.domain.sync import SyncError
from civex.services.http_wire import Reply, Wire, detail_of, retries

_CHUNK = 1024 * 1024


def bundle_url(base: str, name: str) -> str:
    """Where a host serves the release `name` of the repository at `base` (the
    address `civex clone` takes: the one sync connects to)."""
    return (
        f"{base.strip().rstrip('/')}/api/releases/"
        f"{urllib.parse.quote(name, safe='')}/bundle"
    )


def check_address(url: str) -> None:
    """HTTPS, or plain HTTP only to this computer: a token travels in the
    request."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" and parts.hostname:
        return
    if parts.scheme == "http" and parts.hostname and is_loopback(parts.hostname):
        return
    raise SyncError(
        "The address must start with https:// (http:// only for this computer)",
        retryable=False,
    )


def fetch_release_bundle(
    base: str,
    name: str,
    dest: Path,
    token: str | None = None,
    progress: Callable[[int, int | None], None] | None = None,
    timeout: float = 60.0,
) -> int:
    """Download release `name` of the repository at `base` to `dest`, streamed
    in chunks; returns the bytes written. `token` (a host's access token) is
    sent as a bearer token for a private repository. `progress(done, total)`
    is told as bytes arrive (`total` None when the host didn't say)."""
    check_address(base)
    headers = {"Accept": "application/zip"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    # Through the one client every call to a host goes through (the status
    # table and its waits apply). A redirect, to storage say, is followed but
    # never takes the token to another host or down to http.
    response = Wire().request(
        "GET",
        bundle_url(base, name),
        headers=headers,
        timeout=timeout,
        stream=True,
        follow="strip_auth",
        raise_for_status=False,
    )
    if response.status >= 300:
        response.body = _body(response)
        response.close()
        raise _refused(response, name)
    written = 0
    length = response.header("Content-Length")
    total = int(length) if length and length.isdigit() else None
    try:
        with response, dest.open("wb") as out:
            while chunk := response.read(_CHUNK):
                out.write(chunk)
                written += len(chunk)
                if progress:
                    progress(written, total)
    except (http.client.HTTPException, socket.timeout, ConnectionError, OSError) as e:
        raise SyncError(f"The download stopped: {e}", retryable=True) from e
    if total is not None and written != total:
        raise SyncError(
            f"The download stopped early ({written} of {total} bytes)", retryable=True
        )
    return written


def _body(reply: Reply) -> bytes:
    try:
        return reply.read(65536)
    except Exception:  # noqa: BLE001
        return b""


def _refused(reply: Reply, name: str) -> SyncError:
    detail = detail_of(reply)
    if isinstance(detail, dict):
        detail = detail.get("message") or detail.get("code")
    code = reply.status
    if code in (401, 403):
        return SyncError(
            f"The server wouldn't give you release '{name}': "
            f"{detail or 'sign in (--token) or ask for access'}",
            retryable=False,
            status=code,
        )
    if code in (404, 501):
        return SyncError(
            f"There is no release '{name}' there, or that address doesn't "
            f"publish releases{f' ({detail})' if detail else ''}",
            retryable=False,
            status=code,
        )
    if code == 413 or code == 402:
        return SyncError(
            f"The server refused the download ({code}){f': {detail}' if detail else ''}",
            retryable=False,
            status=code,
        )
    return SyncError(
        f"The server answered {code}{f': {detail}' if detail else ''}",
        retryable=retries(code),
        status=code,
    )
