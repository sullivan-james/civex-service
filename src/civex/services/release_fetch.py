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
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

from civex.domain.hosts import is_loopback
from civex.domain.sync import SyncError
from civex.tls import certificate_problem, ssl_context

_CHUNK = 1024 * 1024


class _SameHostOnly(urllib.request.HTTPRedirectHandler):
    """Follows a redirect, but never takes the token to another host or from
    https down to http."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        old, new = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        if old.scheme == "https" and new.scheme != "https":
            return None
        follow = super().redirect_request(req, fp, code, msg, headers, newurl)
        if follow is not None and (old.hostname, old.port) != (new.hostname, new.port):
            follow.remove_header("Authorization")
        return follow


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
    request = urllib.request.Request(bundle_url(base, name), headers=headers)
    opener = urllib.request.build_opener(
        _SameHostOnly, urllib.request.HTTPSHandler(context=ssl_context())
    )
    try:
        response = opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as e:
        raise _refused(e, name) from e
    except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as e:
        problem = certificate_problem(e)
        reason = problem or str(getattr(e, "reason", None) or e)
        raise SyncError(
            f"Could not reach the server: {reason}", retryable=problem is None
        ) from e
    written = 0
    length = response.headers.get("Content-Length")
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


def _refused(error: urllib.error.HTTPError, name: str) -> SyncError:
    try:
        detail = json.loads(error.read().decode("utf-8")).get("detail")
    except Exception:  # an HTML error page, or nothing
        detail = None
    if error.code in (401, 403):
        return SyncError(
            f"The server wouldn't give you release '{name}': "
            f"{detail or 'sign in (--token) or ask for access'}",
            retryable=False,
            status=error.code,
        )
    if error.code in (404, 501):
        return SyncError(
            f"There is no release '{name}' there, or that address doesn't "
            f"publish releases{f' ({detail})' if detail else ''}",
            retryable=False,
            status=error.code,
        )
    return SyncError(
        f"The server answered {error.code}{f': {detail}' if detail else ''}",
        retryable=error.code in (408, 429) or error.code >= 500,
        status=error.code,
    )
