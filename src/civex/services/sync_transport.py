"""Talking to an authority over HTTP(S): the transport a device uses.

Every request goes through one `http_wire.Wire` (the transport's own: keep-alive
connections per thread, gzip, and the one status table that waits `Retry-After`
or backs off and sends again inside the pass). Signing in is this transport's own
business: it signs in with the device's key when it has no session or the one
it has is about to expire, and once more if the server says it has expired.
Every failure becomes a `SyncError` saying whether trying again can help: a
network error or a 5xx can; a refused device, a too-big change or a protocol
mismatch cannot, and retrying them would only hammer a server that has said no.
"""

from __future__ import annotations

import gzip
import json
import threading
from concurrent.futures import Future, ThreadPoolExecutor, wait
import time
import urllib.parse
from collections.abc import Callable, Iterator
from dataclasses import replace
from typing import Any

from civex import keys
from civex.domain.dtos import DirectUpload
from civex.domain.sync import (
    DIRECT_FILES,
    FILE_PACKS,
    FILE_PART_BYTES,
    FILE_PART_MAX,
    FILE_PARTS,
    MAX_FILE_PARTS,
    DeviceCredentials,
    FeedPage,
    Hello,
    Joined,
    LoginStarted,
    SessionGrant,
    PushResult,
    SnapshotPage,
    SyncEntry,
    SyncError,
    UploadSource,
    protocol_header,
    session_answer,
    session_request,
)
from civex.services.http_wire import Reply, Wire, retries

_CHUNK = 1024 * 1024
# A file above this many bytes goes in parts, this many at a time (each part is
# held in memory while it is sent, so at most PART_THREADS x the part size is).
PARTS_MIN_BYTES = 2 * FILE_PART_BYTES
PART_THREADS = 4
# Finishing a big file takes the authority a while (it reads the whole once, or
# storage joins the parts): a longer wait than an ordinary call.
FINISH_SECONDS = 600.0
# How long a push may take before this side gives up on the answer. The
# authority's own budget for a push is below this, so a slow push is answered
# short (the rest goes next) rather than timing out here.
CLIENT_PUSH_TIMEOUT_SECONDS = 120.0
# An ordinary call (feed, snapshot, hello, sign-in), and a file or part upload.
READ_TIMEOUT_SECONDS = 60.0
UPLOAD_TIMEOUT_SECONDS = 120.0
# The capability under which an authority reads a gzipped request body.
GZIP_REQUESTS = "gzip_requests"
GZIP_MIN_BYTES = 1024
# A push carries at most this many serialized bytes (an action over it goes
# alone), so the size of a request doesn't depend on how wide the records are.
PUSH_BUDGET_BYTES = 2 * 1024 * 1024
API = "/api/sync/v1"


def batch_by_budget(
    entries: list[SyncEntry],
    max_entries: int,
    max_bytes: int = PUSH_BUDGET_BYTES,
    size_of: Callable[[SyncEntry], int] | None = None,
) -> list[SyncEntry]:
    """The leading entries to send in one push: at most `max_entries` and about
    `max_bytes` serialized, but never part of an action (entries sharing an
    `op` are taken together or not at all; an action over the budget goes
    alone, and the first action is always taken). Entries with no `op` are each
    an action of their own."""
    size = size_of or (lambda e: len(json.dumps(e.to_dict())))
    taken: list[SyncEntry] = []
    used = 0
    i = 0
    while i < len(entries):
        j = i + 1
        if entries[i].op is not None:
            while j < len(entries) and entries[j].op == entries[i].op:
                j += 1
        action = entries[i:j]
        cost = sum(size(e) for e in action)
        if taken and (
            len(taken) + len(action) > max_entries or used + cost > max_bytes
        ):
            break
        taken += action
        used += cost
        i = j
    return taken


class HttpSyncTransport:
    # How many small files the sender may upload at once over this transport
    # (each is its own HTTP request; the session token is shared).
    upload_threads = 4

    def __init__(
        self,
        base_url: str,
        credentials: DeviceCredentials,
        timeout: float = READ_TIMEOUT_SECONDS,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._credentials = credentials
        self._timeout = timeout
        # One keep-alive client for everything this transport says (and the
        # presigned storage URLs it is sent to, which never get the session).
        self._wire = Wire()
        self._session: SessionGrant | None = None
        # Uploads run on several threads: signing in, and dropping a session the
        # server refused, are one at a time.
        self._session_lock = threading.RLock()
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
        joined = Joined.from_dict(self._plain("POST", "/join", body).json())
        self._credentials = replace(creds, authority_key=joined.authority_key)
        return joined

    def request_login(self) -> LoginStarted:
        creds = self._credentials
        body = {
            "device_id": creds.device_id,
            "public_key": keys.public_of(creds.private_key),
        }
        try:
            return LoginStarted.from_dict(
                self._plain("POST", "/device-login", body).json()
            )
        except SyncError as e:
            if e.status == 404:  # an authority from before this way in
                raise SyncError(
                    "This computer hasn't joined that server, and the server is "
                    "too old to approve it from there: ask its admin for an invite",
                    retryable=False,
                ) from e
            raise

    def poll_login(self, device_code: str) -> Joined | None:
        body = self._plain("GET", f"/device-login/{device_code}").json()
        if "authority_key" not in body:
            return None
        joined = Joined.from_dict(body)
        self._credentials = replace(
            self._credentials, authority_key=joined.authority_key
        )
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
        # A gzipped body only to an authority that says it reads one.
        return PushResult.from_dict(
            self._json(
                "POST",
                "/push",
                body,
                timeout=CLIENT_PUSH_TIMEOUT_SECONDS,
                gzip_body=self._offers(GZIP_REQUESTS),
            )
        )

    def feed(self, after: int, limit: int) -> FeedPage:
        return FeedPage.from_dict(
            self._json("GET", f"/feed?after={after}&limit={limit}")
        )

    def snapshot(
        self,
        kind: str,
        after: str | None,
        limit: int,
        dataset: str | None = None,
        left_after: int | None = None,
    ) -> SnapshotPage:
        query: dict[str, Any] = {"limit": limit}
        if after:
            query["after"] = after
        if dataset:
            query["dataset"] = dataset
            if left_after is not None:
                query["left_after"] = left_after
        return SnapshotPage.from_dict(
            self._json("GET", f"/snapshot/{kind}?{urllib.parse.urlencode(query)}")
        )

    def missing_files(self, shas: list[str]) -> list[str]:
        body = self._json("POST", "/files/missing", {"sha256": shas})
        return list(body["missing"])

    def accepts_packs(self) -> bool:
        """Whether small files go to the authority many to a request. Not when
        its files go straight to a bucket (`direct_files`): a pack streams the
        bytes through the authority, and direct is what keeps them off it."""
        return self._offers(FILE_PACKS) and not self._offers(DIRECT_FILES)

    def upload_pack(
        self, items: list[tuple[str, UploadSource, int]]
    ) -> dict[str, str | None]:
        """Send small files in one request, each read from its start and
        streamed (nothing but the chunk in hand is held). Answers, per file,
        None when the authority stored it, else why not; a file the answer
        does not mention is not in the dict. Raises `SyncError` when the
        request itself fails: then nothing is known to have arrived."""
        body = _PackBody(items)

        def send() -> dict[str, Any]:
            reply = self._call(
                "POST",
                "/files/pack",
                body=body,
                prepare=body.rewind,
                content_type="application/octet-stream",
                length=body.length,
                timeout=UPLOAD_TIMEOUT_SECONDS,
            )
            return dict(reply.json())

        answer = self._again_if_expired(send)
        return {
            r["sha256"]: None if r.get("stored") else (r.get("error") or "refused")
            for r in answer.get("results", [])
        }

    def upload_file(self, sha256: str, source: UploadSource, size: int) -> None:
        start = source.tell()
        big = size > PARTS_MIN_BYTES
        if self._offers(DIRECT_FILES) and self._upload_direct(sha256, source, size):
            return
        if (
            big
            and self._offers(FILE_PARTS)
            and self._upload_parts(sha256, source, size)
        ):
            return

        def send():
            # Again from the start, when signing in again or sending again.
            self._call(
                "PUT",
                f"/files/{sha256}",
                body=source,
                prepare=lambda: source.seek(start),
                content_type="application/octet-stream",
                length=size,
                timeout=UPLOAD_TIMEOUT_SECONDS,
            )

        self._again_if_expired(send)

    def _upload_parts(self, sha256: str, source: UploadSource, size: int) -> bool:
        """Send a big file to the authority in parts, several at a time
        (capability `file_parts`). The authority says which parts it already
        holds from an upload that was interrupted, and those are not sent
        again. False when it wants the file streamed whole after all."""
        try:
            begun = self._json(
                "POST",
                f"/files/{sha256}/parts",
                {"size": size, "part_size": FILE_PART_BYTES},
            )
        except SyncError as e:
            if e.status == 501:
                return False
            raise
        part_size = int(begun["part_size"])
        if not 0 < part_size <= max(FILE_PART_MAX, -(-size // MAX_FILE_PARTS)):
            raise SyncError(
                f"The server asked for parts of {part_size} bytes", retryable=False
            )
        held = set(begun.get("received", []))

        def put(number: int, data: bytes) -> None:
            def send() -> None:
                self._call(
                    "PUT",
                    f"/files/{sha256}/parts/{number}",
                    body=data,
                    content_type="application/octet-stream",
                    length=len(data),
                    timeout=UPLOAD_TIMEOUT_SECONDS,
                )

            self._again_if_expired(send)

        _in_parts(source, size, part_size, held, put)
        self._json(
            "POST",
            f"/files/{sha256}/parts/complete",
            {"size": size},
            timeout=FINISH_SECONDS,
        )
        return True

    def _upload_direct(self, sha256: str, source: UploadSource, size: int) -> bool:
        """Send the file straight to the authority's storage: ask where, PUT
        the bytes there (whole, or in parts several at a time), then say it is
        done. True when the authority has the file (it had it, or it went in);
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
            urls = {p.number: p.url for p in target.parts}
            etags: dict[int, str] = {}

            def put(number: int, data: bytes) -> None:
                etags[number] = self._put_to_storage(urls[number], {}, data, len(data))

            _in_parts(source, size, target.part_size, set(), put)
            parts = [{"number": n, "etag": etags[n]} for n in sorted(etags)]
        self._json(
            "POST",
            f"/files/{sha256}/complete",
            {"size": size, "upload_id": target.upload_id, "parts": parts},
            timeout=FINISH_SECONDS,
        )
        source.seek(start)
        return True

    def _put_to_storage(
        self, url: str, headers: dict[str, str], body: Any, size: int
    ) -> str:
        """PUT `size` bytes to a presigned URL (no civex session: the URL is
        the leave), answering the ETag storage gave."""
        start = body.tell() if hasattr(body, "tell") else None

        def again() -> None:
            if start is not None:
                body.seek(start)

        reply = self._wire.request(
            "PUT",
            url,
            headers={
                **headers,
                "Content-Length": str(size),
                "Content-Type": "application/octet-stream",
            },
            body=body,
            prepare=again,
            timeout=UPLOAD_TIMEOUT_SECONDS,
            raise_for_status=False,
            what="storage",
        )
        if reply.status >= 300:
            raise SyncError(
                f"Storage refused the upload ({reply.status})",
                retryable=retries(reply.status),
                status=reply.status,
            )
        return reply.header("ETag")

    def file_chunks(self, sha256: str) -> Iterator[bytes]:
        """A file's bytes from the server, as they arrive. Asks at once, so a
        file the server hasn't got raises FileNotFoundError here, before
        anything is written. The caller checks the hash of what it wrote. An
        authority offering `direct_files` answers where storage serves the
        bytes (a 307), which is fetched without the session: the URL is the
        leave, and the session must not go to another host."""
        try:
            response = self._again_if_expired(
                lambda: self._call("GET", f"/files/{sha256}", stream=True, gzip=False)
            )
            if response.status in (301, 302, 303, 307, 308):
                location = response.header("Location")
                response.close()
                response = self._open_storage(location, sha256)
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
        with self._session_lock:
            return self._token_locked()

    def _token_locked(self) -> str:
        session = self._session
        if session and session.expires_at - 60 > time.time():
            return session.token
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
        grant = SessionGrant.from_dict(self._plain("POST", "/session", body).json())
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
        used = self._session
        try:
            return call()
        except SyncError as e:
            if e.status != 401:
                raise
            # Dropped under the lock, and only the session that was refused:
            # with several uploads refused at once, the first drops it, the
            # others find a new one already made and use it (one sign-in).
            with self._session_lock:
                if self._session is used:
                    self._session = None
            return call()

    # -- plumbing --------------------------------------------------------

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        headers = {"X-Civex-Protocol": protocol_header(), "Accept": "application/json"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _plain(self, method: str, path: str, body: Any = None) -> Reply:
        """A call that needs no session (join, sign-in): JSON in, JSON out."""
        data = json.dumps(body).encode("utf-8") if body is not None else None
        return self._wire.request(
            method,
            f"{self._base}{API}{path}",
            headers=self._headers("application/json" if data is not None else None),
            body=data,
            timeout=self._timeout,
            follow="same_host",
            accept_gzip=True,
        )

    def _call(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        prepare: Callable[[], None] | None = None,
        content_type: str | None = None,
        length: int | None = None,
        timeout: float | None = None,
        stream: bool = False,
        gzip: bool = True,
        extra: dict[str, str] | None = None,
    ) -> Reply:
        """A signed-in call through the wire (the status table applies)."""
        headers = self._headers(content_type)
        headers["Authorization"] = f"Bearer {self._token()}"
        if length is not None:
            headers["Content-Length"] = str(length)
        headers.update(extra or {})
        return self._wire.request(
            method,
            f"{self._base}{API}{path}",
            headers=headers,
            body=body,
            prepare=prepare,
            timeout=timeout or self._timeout,
            stream=stream,
            follow="never" if stream else "same_host",
            accept_gzip=gzip and not stream,
        )

    def _json(
        self,
        method: str,
        path: str,
        body: Any = None,
        timeout: float | None = None,
        gzip_body: bool = False,
    ) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        extra: dict[str, str] = {}
        if data is not None and gzip_body and len(data) >= GZIP_MIN_BYTES:
            data = gzip.compress(data, compresslevel=3)
            extra["Content-Encoding"] = "gzip"

        def call() -> dict[str, Any]:
            reply = self._call(
                method,
                path,
                body=data,
                content_type="application/json" if data is not None else None,
                length=len(data) if data is not None else None,
                timeout=timeout,
                extra=extra,
            )
            # 204 (a removal) has no body.
            return dict(reply.json())

        return self._again_if_expired(call)

    def _open_storage(self, url: str, sha256: str) -> Reply:
        """GET from storage (a presigned URL), with none of the authority's
        headers. Storage saying it hasn't the object is FileNotFoundError."""
        if not url:
            raise SyncError("The server pointed at storage without saying where")
        reply = self._wire.request(
            "GET",
            url,
            timeout=self._timeout,
            stream=True,
            raise_for_status=False,
            what="storage",
        )
        if reply.status < 300:
            return reply
        reply.close()
        if reply.status == 404:
            raise FileNotFoundError(sha256)
        raise SyncError(
            f"Storage would not serve the file ({reply.status})",
            retryable=retries(reply.status),
            status=reply.status,
        )


class _PackBody:
    """A pack's request body, read as it is sent: for each file a line
    `<sha256> <size>` and the file's bytes (a megabyte at a time). It can be
    rewound, to send again."""

    def __init__(self, items: list[tuple[str, UploadSource, int]]) -> None:
        self._items = items
        self.length = sum(len(f"{sha} {size}\n") + size for sha, _, size in items)
        self.rewind()

    def rewind(self) -> None:
        for _, source, _ in self._items:
            source.seek(0)
        self._frames = self._generate()
        self._buf = b""
        self._pos = 0

    def _generate(self) -> Iterator[bytes]:
        for sha, source, size in self._items:
            yield f"{sha} {size}\n".encode("ascii")
            left = size
            while left:
                chunk = source.read(min(left, _CHUNK))
                if not chunk:
                    raise SyncError("A file being sent was cut short", retryable=True)
                left -= len(chunk)
                yield chunk

    def read(self, n: int = -1) -> bytes:
        while n < 0 or len(self._buf) - self._pos < n:
            chunk = next(self._frames, None)
            if chunk is None:
                break
            self._buf = self._buf[self._pos :] + chunk
            self._pos = 0
        end = len(self._buf) if n < 0 else self._pos + n
        out = self._buf[self._pos : end]
        self._pos += len(out)
        return out


def _in_parts(
    source: UploadSource,
    size: int,
    part_size: int,
    held: set[int],
    put: Callable[[int, bytes], None],
) -> None:
    """Read `source` a part at a time and `put` each (but those in `held`),
    PART_THREADS at once. One thread reads, in order, so the file is read once;
    it waits for a free slot before reading the next part, so memory holds at
    most PART_THREADS parts. The first failure stops reading, lets the parts in
    flight finish (they stay with the authority, for the next try), and is
    raised."""
    count = max(1, -(-size // part_size)) if size else 0
    slots = threading.BoundedSemaphore(PART_THREADS)
    flying: set[Future[None]] = set()
    failure: list[BaseException] = []

    def send(number: int, data: bytes) -> None:
        try:
            put(number, data)
        except BaseException as e:
            failure.append(e)
            raise
        finally:
            slots.release()

    with ThreadPoolExecutor(PART_THREADS) as pool:
        for number in range(1, count + 1):
            length = min(part_size, size - (number - 1) * part_size)
            if number in held:
                source.seek(length, 1)  # held already: counted, not sent
                continue
            slots.acquire()
            if failure:
                slots.release()
                break
            data = source.read(length)
            if len(data) != length:
                slots.release()
                raise SyncError("A file being sent was cut short", retryable=True)
            flying.add(pool.submit(send, number, data))
            del data
            flying -= {f for f in flying if f.done()}
        wait(flying)
    if failure:
        raise failure[0]


def build_transport(base_url: str, credentials: DeviceCredentials) -> HttpSyncTransport:
    """The transport for an authority's address. An `ssh://` one is the same
    HTTP, through a tunnel SSH opens to a port here (`ssh_tunnel`)."""
    from civex.services import ssh_tunnel

    if ssh_tunnel.is_ssh(base_url):
        base_url = ssh_tunnel.local_url(base_url)
    return HttpSyncTransport(base_url, credentials)


__all__ = [
    "CLIENT_PUSH_TIMEOUT_SECONDS",
    "HttpSyncTransport",
    "batch_by_budget",
    "build_transport",
]
