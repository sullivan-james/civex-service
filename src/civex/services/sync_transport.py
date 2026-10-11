"""Talking to an authority over HTTP(S): the transport a device uses.

HTTP from the standard library (urllib). Signing in is this transport's own
business: it signs in with the device's key when it has no session or the one
it has is about to expire, and once more if the server says it has expired.
Every failure becomes a `SyncError` saying whether trying again can help: a
network error or a 5xx can; a refused device or a protocol mismatch cannot, and
retrying them would only hammer a server that has said no.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

from civex import keys
from civex.domain.dtos import DirectUpload
from civex.domain.sync import (
    DIRECT_FILES,
    DeviceCredentials,
    FeedPage,
    Hello,
    Joined,
    SessionGrant,
    PushResult,
    SnapshotPage,
    SyncEntry,
    SyncError,
    UploadSource,
    protocol_header,
    protocol_mismatch,
    session_answer,
    session_request,
)
from civex.tls import certificate_problem, ssl_context

_CHUNK = 1024 * 1024
API = "/api/sync/v1"


class HttpSyncTransport:
    def __init__(
        self, base_url: str, credentials: DeviceCredentials, timeout: float = 30.0
    ) -> None:
        self._base = base_url.rstrip("/")
        self._credentials = credentials
        self._timeout = timeout
        self._session: SessionGrant | None = None
        # What the authority said it offers (`Hello.capabilities`), once asked.
        self._capabilities: frozenset[str] | None = None

    # -- the protocol ----------------------------------------------------

    def join(self, invite: str) -> Joined:
        creds = self._credentials
        body = {
            "invite": invite,
            "device_id": creds.device_id,
            "public_key": keys.public_of(creds.private_key),
        }
        request = self._request("POST", "/join", data=json.dumps(body).encode())
        request.add_header("Content-Type", "application/json")
        with self._open(request) as response:
            joined = Joined.from_dict(json.loads(response.read().decode("utf-8")))
        self._credentials = replace(creds, authority_key=joined.authority_key)
        return joined

    def hello(self) -> Hello:
        hello = Hello.from_dict(self._json("GET", "/hello"))
        self._capabilities = frozenset(hello.capabilities)
        return hello

    def _offers(self, capability: str) -> bool:
        if self._capabilities is None:
            self.hello()
        return capability in (self._capabilities or ())

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

    def upload_file(self, sha256: str, source: UploadSource, size: int) -> None:
        start = source.tell()
        if self._offers(DIRECT_FILES) and self._upload_direct(sha256, source, size):
            return

        def send():
            source.seek(start)  # again from the start, when signing in again
            request = self._signed_in("PUT", f"/files/{sha256}", data=source)
            request.add_header("Content-Length", str(size))
            request.add_header("Content-Type", "application/octet-stream")
            self._open(request).close()

        self._again_if_expired(send)

    def _upload_direct(self, sha256: str, source: UploadSource, size: int) -> bool:
        """Send the file straight to the authority's storage: ask where, PUT
        the bytes there (whole, or a part at a time), then say it is done.
        True when the authority has the file (it had it, or it went in);
        False when it wants the bytes streamed to it after all."""
        try:
            answer = self._json("POST", f"/files/{sha256}/upload", {"size": size})
        except SyncError as e:
            if e.status == 501:  # this authority doesn't do it: stream instead
                return False
            raise
        if not answer:  # 204: it has the file already
            return True
        target = DirectUpload.from_dict(answer)
        start = source.tell()
        parts: list[dict[str, Any]] = []
        if target.url is not None:
            self._put_to_storage(target.url, target.headers, source, size)
        else:
            for part in target.parts:
                data = source.read(target.part_size)
                etag = self._put_to_storage(part.url, {}, data, len(data))
                parts.append({"number": part.number, "etag": etag})
        self._json(
            "POST",
            f"/files/{sha256}/complete",
            {"size": size, "upload_id": target.upload_id, "parts": parts},
        )
        source.seek(start)
        return True

    def _put_to_storage(
        self, url: str, headers: dict[str, str], body: Any, size: int
    ) -> str:
        """PUT `size` bytes to a presigned URL (no civex session: the URL is
        the leave), answering the ETag storage gave."""
        request = urllib.request.Request(url, data=body, method="PUT")
        for name, value in headers.items():
            request.add_header(name, value)
        request.add_header("Content-Length", str(size))
        request.add_header("Content-Type", "application/octet-stream")
        try:
            with urllib.request.urlopen(
                request, timeout=self._timeout, context=ssl_context()
            ) as response:
                return str(response.headers.get("ETag", ""))
        except urllib.error.HTTPError as e:
            raise SyncError(
                f"Storage refused the upload ({e.code})",
                retryable=e.code in (408, 429) or e.code >= 500,
                status=e.code,
            ) from e
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as e:
            raise SyncError(f"Could not reach storage: {_reason(e)}") from e

    def file_chunks(self, sha256: str) -> Iterator[bytes]:
        """A file's bytes from the server, as they arrive. Asks at once, so a
        file the server hasn't got raises FileNotFoundError here, before
        anything is written. The caller checks the hash of what it wrote. An
        authority offering `direct_files` answers where storage serves the
        bytes (a 307), which is fetched without the session: the URL is the
        leave, and the session must not go to another host."""
        try:
            response = self._again_if_expired(
                lambda: self._open(
                    self._signed_in("GET", f"/files/{sha256}"), follow=False
                )
            )
        except _Redirected as to:
            response = self._open_storage(to.url, sha256)
        except SyncError as e:
            if e.status == 404:  # the server answered: it doesn't have it
                raise FileNotFoundError(sha256) from e
            raise

        def read() -> Iterator[bytes]:
            with response:
                while chunk := response.read(_CHUNK):
                    yield chunk

        return read()

    # -- the library (shared workflows and plugins) -----------------------

    def library(self) -> list[dict[str, Any]]:
        return list(self._json("GET", "/library")["items"])

    def library_item(
        self, kind: str, name: str, version: int | None = None
    ) -> dict[str, Any]:
        path = f"/library/{urllib.parse.quote(kind)}/{urllib.parse.quote(name)}"
        if version is not None:
            path += f"?version={int(version)}"
        try:
            return self._json("GET", path)
        except SyncError as e:
            if e.status == 404:
                raise FileNotFoundError(f"{kind} {name}") from e
            raise

    def publish(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        return self._json("POST", "/library", {"items": items})

    def unpublish(
        self, kind: str, name: str, version: int | None = None, force: bool = False
    ) -> None:
        query = urllib.parse.urlencode(
            {"force": "true" if force else "false"}
            | ({"version": int(version)} if version is not None else {})
        )
        path = f"/library/{urllib.parse.quote(kind)}/{urllib.parse.quote(name)}?{query}"
        try:
            self._json("DELETE", path)
        except SyncError as e:
            if e.status == 404:
                raise FileNotFoundError(f"{kind} {name}") from e
            raise

    # -- signing in ------------------------------------------------------

    def _token(self) -> str:
        """A session token, signing in when there is none or it is about to
        expire. The authority's answer must carry its signature over this very
        request, so a server that isn't the one this device joined is refused
        before anything is sent to it."""
        if self._session and self._session.expires_at - 60 > time.time():
            return self._session.token
        creds = self._credentials
        if not creds.authority_key:
            raise SyncError(
                "This computer hasn't joined that server: connect with an invite",
                retryable=False,
            )
        at = int(time.time())
        signature = keys.sign(
            creds.private_key, session_request(creds.authority_key, creds.device_id, at)
        )
        body = {"device_id": creds.device_id, "at": at, "signature": signature}
        request = self._request("POST", "/session", data=json.dumps(body).encode())
        request.add_header("Content-Type", "application/json")
        with self._open(request) as response:
            grant = SessionGrant.from_dict(json.loads(response.read().decode("utf-8")))
        if not keys.verifies(
            creds.authority_key, session_answer(signature), grant.signature
        ):
            raise SyncError(
                "The server at that address is not the one this computer joined "
                "(its key is different). Nothing was sent to it.",
                retryable=False,
            )
        self._session = grant
        return grant.token

    def _again_if_expired(self, call):
        """Make an authenticated call, signing in again once if the server says
        the session is no longer good (it expired, or the server restarted)."""
        try:
            return call()
        except SyncError as e:
            if e.status != 401 or self._session is None:
                raise
            self._session = None
            return call()

    # -- plumbing --------------------------------------------------------

    def _request(
        self, method: str, path: str, data: Any = None
    ) -> urllib.request.Request:
        request = urllib.request.Request(
            f"{self._base}{API}{path}", data=data, method=method
        )
        request.add_header("X-Civex-Protocol", protocol_header())
        request.add_header("Accept", "application/json")
        return request

    def _signed_in(
        self, method: str, path: str, data: Any = None
    ) -> urllib.request.Request:
        request = self._request(method, path, data=data)
        request.add_header("Authorization", f"Bearer {self._token()}")
        return request

    def _json(self, method: str, path: str, body: Any = None) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None

        def call() -> dict[str, Any]:
            request = self._signed_in(method, path, data=data)
            if data is not None:
                request.add_header("Content-Type", "application/json")
            with self._open(request) as response:
                raw = response.read()
                # 204 (a removal) has no body.
                return json.loads(raw.decode("utf-8")) if raw else {}

        return self._again_if_expired(call)

    def _open(self, request: urllib.request.Request, follow: bool = True):
        try:
            if follow:
                return urllib.request.urlopen(
                    request, timeout=self._timeout, context=ssl_context()
                )
            opener = urllib.request.build_opener(
                _NoRedirect, urllib.request.HTTPSHandler(context=ssl_context())
            )
            return opener.open(request, timeout=self._timeout)
        except urllib.error.HTTPError as e:
            if not follow and e.code in (301, 302, 303, 307, 308):
                raise _Redirected(e.headers.get("Location") or "") from e
            raise _from_status(e) from e
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as e:
            problem = certificate_problem(e)
            if problem:
                # Waiting won't fix a certificate; trying again every few
                # seconds would only fill the status bar.
                raise SyncError(
                    f"Could not reach the server: {problem}", retryable=False
                ) from e
            raise SyncError(f"Could not reach the server: {_reason(e)}") from e

    def _open_storage(self, url: str, sha256: str):
        """GET from storage (a presigned URL), with none of the authority's
        headers. Storage saying it hasn't the object is FileNotFoundError."""
        if not url:
            raise SyncError("The server pointed at storage without saying where")
        request = urllib.request.Request(url, method="GET")
        try:
            return urllib.request.urlopen(
                request, timeout=self._timeout, context=ssl_context()
            )
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise FileNotFoundError(sha256) from e
            raise SyncError(
                f"Storage would not serve the file ({e.code})",
                retryable=e.code in (408, 429) or e.code >= 500,
                status=e.code,
            ) from e
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as e:
            raise SyncError(f"Could not reach storage: {_reason(e)}") from e


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Leaves a redirect to the caller, so the session token never follows
    one to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


class _Redirected(Exception):
    def __init__(self, url: str) -> None:
        super().__init__(url)
        self.url = url


def _reason(error: Exception) -> str:
    return str(getattr(error, "reason", None) or error)


def _from_status(error: urllib.error.HTTPError) -> SyncError:
    try:
        detail = json.loads(error.read().decode("utf-8")).get("detail")
    except Exception:  # an HTML error page, or nothing
        detail = None
    if error.code == 426:
        return SyncError(_mismatch(detail), retryable=False, status=426)
    text = f"{detail}" if detail else f"The server answered {error.code}"
    if error.code == 401:
        return SyncError(
            f"The server refused this device: {text}", retryable=False, status=401
        )
    if error.code == 403:
        # Signed in, but not allowed to do that (publish to the library).
        return SyncError(text, retryable=False, status=403)
    if error.code == 429:
        return SyncError(text, retryable=True, status=429)
    if error.code == 404:
        return SyncError(
            "That address is not a civex sync server (or sync is not switched on there)",
            retryable=False,
            status=404,
        )
    if error.code == 501:
        # The server exists but doesn't do that (a feature its host lacks):
        # waiting won't change it.
        return SyncError(text, retryable=False, status=501)
    if error.code in (408, 429) or error.code >= 500:
        return SyncError(text, retryable=True, status=error.code)
    return SyncError(text, retryable=False, status=error.code)


def _mismatch(detail: Any) -> str:
    """A 426 in this computer's words: which side to update. A server from
    before the protocol range says it in a sentence of its own."""
    if not isinstance(detail, dict) or "protocol_max" not in detail:
        return str(detail or "The server speaks another sync protocol")
    theirs = (int(detail["protocol_min"]), int(detail["protocol_max"]))
    return protocol_mismatch(theirs, "the server", "this computer")


def build_transport(base_url: str, credentials: DeviceCredentials) -> HttpSyncTransport:
    """The transport for an authority's address. An `ssh://` one is the same
    HTTP, through a tunnel SSH opens to a port here (`ssh_tunnel`)."""
    from civex.services import ssh_tunnel

    if ssh_tunnel.is_ssh(base_url):
        base_url = ssh_tunnel.local_url(base_url)
    return HttpSyncTransport(base_url, credentials)


__all__ = ["HttpSyncTransport", "build_transport"]
