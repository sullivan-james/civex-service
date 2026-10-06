"""Talking to an authority over HTTP(S): the transport a device uses.

Standard library only (a device is a normal civex install; sync adds no
dependency). Every failure becomes a `SyncError` saying whether trying again can
help: a network error or a 5xx can; a refused token or a protocol mismatch
cannot, and retrying them would only hammer a server that has said no.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from civex.domain.sync import (
    PROTOCOL_VERSION,
    FeedPage,
    Hello,
    PushResult,
    SnapshotPage,
    SyncEntry,
    SyncError,
)

_CHUNK = 1024 * 1024
API = "/api/sync/v1"


class HttpSyncTransport:
    def __init__(
        self, base_url: str, token: str, device_id: str, timeout: float = 30.0
    ) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._device_id = device_id
        self._timeout = timeout

    # -- the protocol ----------------------------------------------------

    def hello(self) -> Hello:
        return Hello.from_dict(self._json("GET", "/hello"))

    def push(self, entries: list[SyncEntry]) -> PushResult:
        body = {"entries": [e.to_dict() for e in entries]}
        return PushResult.from_dict(self._json("POST", "/push", body))

    def feed(self, after: int, limit: int) -> FeedPage:
        return FeedPage.from_dict(
            self._json("GET", f"/feed?after={after}&limit={limit}")
        )

    def snapshot(self, kind: str, after: str | None, limit: int) -> SnapshotPage:
        query = {"limit": limit} | ({"after": after} if after else {})
        return SnapshotPage.from_dict(
            self._json("GET", f"/snapshot/{kind}?{urllib.parse.urlencode(query)}")
        )

    def missing_files(self, shas: list[str]) -> list[str]:
        body = self._json("POST", "/files/missing", {"sha256": shas})
        return list(body["missing"])

    def upload_file(self, sha256: str, path: Path) -> None:
        size = path.stat().st_size
        with open(path, "rb") as f:
            request = self._request("PUT", f"/files/{sha256}", data=f)
            request.add_header("Content-Length", str(size))
            request.add_header("Content-Type", "application/octet-stream")
            self._open(request).close()

    def download_file(self, sha256: str, dest: Path) -> None:
        """Fetch a file to `dest`, checking it is the file asked for: bytes that
        hash to something else are discarded, never kept under that name."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=".sync-")
        digest = hashlib.sha256()
        try:
            with (
                os.fdopen(fd, "wb") as out,
                self._open(self._request("GET", f"/files/{sha256}")) as response,
            ):
                while chunk := response.read(_CHUNK):
                    digest.update(chunk)
                    out.write(chunk)
            if digest.hexdigest() != sha256:
                raise SyncError("The server sent the wrong content for that file")
            os.replace(tmp_name, dest)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    # -- plumbing --------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        data: Any = None,
        headers: dict[str, str] | None = None,
    ) -> urllib.request.Request:
        request = urllib.request.Request(
            f"{self._base}{API}{path}", data=data, method=method
        )
        request.add_header("Authorization", f"Bearer {self._token}")
        request.add_header("X-Civex-Device", self._device_id)
        request.add_header("X-Civex-Protocol", str(PROTOCOL_VERSION))
        request.add_header("Accept", "application/json")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        return request

    def _json(self, method: str, path: str, body: Any = None) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = self._request(method, path, data=data)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        with self._open(request) as response:
            return json.loads(response.read().decode("utf-8"))

    def _open(self, request: urllib.request.Request):
        try:
            return urllib.request.urlopen(request, timeout=self._timeout)
        except urllib.error.HTTPError as e:
            raise _from_status(e) from e
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as e:
            raise SyncError(f"Could not reach the server: {_reason(e)}") from e


def _reason(error: Exception) -> str:
    return str(getattr(error, "reason", None) or error)


def _from_status(error: urllib.error.HTTPError) -> SyncError:
    try:
        detail = json.loads(error.read().decode("utf-8")).get("detail")
    except Exception:  # an HTML error page, or nothing
        detail = None
    text = f"{detail}" if detail else f"The server answered {error.code}"
    if error.code in (401, 403):
        return SyncError(f"The server refused this device: {text}", retryable=False)
    if error.code == 426:
        return SyncError(text, retryable=False)
    if error.code == 404:
        return SyncError(
            "That address is not a civex sync server (or sync is not switched on there)",
            retryable=False,
        )
    if error.code in (408, 429) or error.code >= 500:
        return SyncError(text, retryable=True)
    return SyncError(text, retryable=False)


def build_transport(base_url: str, token: str, device_id: str) -> HttpSyncTransport:
    return HttpSyncTransport(base_url, token, device_id)


__all__ = ["HttpSyncTransport", "build_transport"]
