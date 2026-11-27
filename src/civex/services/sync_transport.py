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
import hashlib
import json
import logging
import tempfile
import queue
import threading
from concurrent.futures import Future, ThreadPoolExecutor, wait
import time
import urllib.parse
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from typing import Any

from civex import keys
from civex.domain.dtos import DirectUpload
from civex.domain.sync import (
    DIRECT_FILES,
    FILE_PACK_DOWNLOADS,
    PACK_DOWNLOAD_FILE_MAX,
    PACK_DOWNLOAD_MAX_BYTES,
    FILE_PACKS,
    GZIP_REQUESTS,
    FILE_PART_BYTES,
    FILE_PART_MAX,
    FILE_PART_MIN,
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
from civex.services import transfer_budget
from civex.services.http_wire import Reply, Wire, retries

_CHUNK = 1024 * 1024
# A file above this many bytes goes in parts (where the authority takes them):
# one stream is held back by the line's round trip, parts are not. Parts of all
# the files on their way share one pool, `windows().part_threads` wide, and the
# bytes they hold come from the process-wide budget (`transfer_budget`).
PARTS_MIN_BYTES = 8 * 1024 * 1024
# A file is cut so that it has at least this many parts, down to FILE_PART_MIN.
PARTS_PER_FILE = 4
# A file coming down is fetched in ranges, this many at a time (shared by all
# the files being fetched), when it is at least DOWNLOAD_PARTS_MIN_BYTES: a
# range is written where it belongs in a temporary file as it arrives, so
# memory holds a chunk per range, and the hash is checked once, by whoever
# stores the whole.
DOWNLOAD_PART_THREADS = 6
DOWNLOAD_PART_BYTES = FILE_PART_BYTES
DOWNLOAD_PARTS_MIN_BYTES = 2 * DOWNLOAD_PART_BYTES
# A range that fails in the middle is asked for again, on its own, this often.
DOWNLOAD_PART_TRIES = 3
# What a pack's answer, and a file's, is held in: memory up to this, then a
# temporary file. With 6 packs and 12 files in hand, 6 ranges and their
# buffers, a download holds at most about 48 MB.
PACK_SPOOL_BYTES = 2 * 1024 * 1024
FILE_SPOOL_BYTES = 2 * 1024 * 1024

log = logging.getLogger(__name__)


@dataclass
class PackAnswer:
    """What a pack download brought: the answer held in `spool`, each file a
    slice of it (`files`: hash -> (offset, size, the sha256 of those bytes, taken as they arrived)); those the authority has no
    readable copy of (`absent`); and those to ask for alone (`alone`: too big
    for a pack, or the answer ended before it got to them)."""

    spool: Any = None
    files: dict[str, tuple[int, int, str]] = field(default_factory=dict)
    absent: set[str] = field(default_factory=set)
    alone: list[str] = field(default_factory=list)

    def close(self) -> None:
        if self.spool is not None:
            self.spool.close()
            self.spool = None


class _FrameReader:
    """A pack's answer read line by line and in exact lengths."""

    def __init__(self, reply: Reply) -> None:
        self._reply = reply
        self._buf = bytearray()
        self._pos = 0

    def _more(self) -> bool:
        chunk = self._reply.read(256 * 1024)
        if not chunk:
            return False
        del self._buf[: self._pos]
        self._pos = 0
        self._buf += chunk
        return True

    def line(self) -> str | None:
        """The next line, None at the clean end of the answer."""
        while True:
            end = self._buf.find(b"\n", self._pos)
            if end >= 0:
                text = self._buf[self._pos : end].decode("ascii")
                self._pos = end + 1
                return text
            if len(self._buf) - self._pos > 512:
                raise SyncError("That is not a pack", retryable=True)
            if not self._more():
                if len(self._buf) > self._pos:
                    raise SyncError("The pack was cut short", retryable=True)
                return None

    def copy(self, size: int, sink: Any, digest: Any = None) -> None:
        left = size
        while left:
            if self._pos >= len(self._buf) and not self._more():
                raise SyncError("The pack was cut short", retryable=True)
            take = min(left, len(self._buf) - self._pos)
            block = memoryview(self._buf)[self._pos : self._pos + take]
            if digest is not None:
                digest.update(block)
            sink.write(block)
            block.release()  # the buffer may be resized next
            self._pos += take
            left -= take


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
GZIP_MIN_BYTES = 1024
API = "/api/sync/v1"


class HttpSyncTransport:
    # How many small files the sender may upload at once over this transport
    # (each is its own HTTP request; the session token is shared).
    upload_threads = 4
    # Big files sent at once: their parts share one pool, and the round trips
    # that open and finish one overlap the parts of the other.
    upload_large_files = 2
    # Asked between the parts of a big file: True ends the upload (the parts
    # sent stay with the authority, for the next try) with `UploadStopped`.
    cancel: Callable[[], bool] | None = None
    # And how many files it may download at once.
    download_threads = 6

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
        # Set once an authority has refused the pack download route.
        self._no_pack_downloads = False
        self._parts: ThreadPoolExecutor | None = None

    def close(self) -> None:
        """Close the connections this transport holds open."""
        parts, self._parts = self._parts, None
        if parts is not None:
            parts.shutdown(wait=False, cancel_futures=True)
        self._wire.close()

    def __del__(self) -> None:  # a backstop: whoever has it should close it
        wire = getattr(self, "_wire", None)
        if wire is not None:
            wire.close()

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
            if e.status in (401, 403, 404):
                # A private project answers like a missing one; an older
                # authority has no way in without an invite.
                raise SyncError(
                    "This project hasn't joined that server, and it can't ask to "
                    "join from here. The project wasn't found or is private, or "
                    "the server can't approve it: sign in to the host, or ask its "
                    "admin for an invite",
                    retryable=False,
                    status=e.status,
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
                idempotent=True,  # the authority answers a repeat from its log
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
        body = self._json("POST", "/files/missing", {"sha256": shas}, idempotent=True)
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
                idempotent=True,  # a file stored twice is stored once
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
                {"size": size, "part_size": _part_size_for(size)},
                idempotent=True,  # says which parts it holds already
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

        def put(number: int, data: memoryview) -> None:
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

        _in_parts(source, size, part_size, held, put, self.cancel)
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
            answer = self._json(
                "POST", f"/files/{sha256}/upload", {"size": size}, idempotent=True
            )
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

            def put(number: int, data: memoryview) -> None:
                etags[number] = self._put_to_storage(urls[number], {}, data, len(data))

            _in_parts(source, size, target.part_size, set(), put, self.cancel)
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

    def accepts_pack_downloads(self) -> bool:
        """Whether small files come down many to a request. Not when the
        authority's files are in a bucket (`direct_files`): there each is a
        presigned download that never touches the authority."""
        return (
            not self._no_pack_downloads
            and self._offers(FILE_PACK_DOWNLOADS)
            and not self._offers(DIRECT_FILES)
        )

    def fetch_pack(
        self, shas: list[str], stop: threading.Event | None = None
    ) -> PackAnswer:
        """Ask for many files in one request. Whatever arrived whole is kept
        (each slice of one spool), and the rest is named in `alone` for the
        caller to ask for one at a time: a request that fails before anything
        arrived raises `SyncError`, but one that is cut off part way (or
        garbled) costs only the files after the cut."""
        body = json.dumps({"sha256": shas}).encode("utf-8")
        answer = PackAnswer(
            spool=tempfile.SpooledTemporaryFile(max_size=PACK_SPOOL_BYTES)
        )
        try:
            try:
                reply = self._again_if_expired(
                    lambda: self._call(
                        "POST",
                        "/files/pack/download",
                        body=body,
                        content_type="application/json",
                        length=len(body),
                        timeout=UPLOAD_TIMEOUT_SECONDS,
                        stream=True,
                        gzip=False,
                        idempotent=True,  # it only reads
                    )
                )
            except SyncError as e:
                # Whatever the reason (an authority without the route, one that
                # refuses it, one that is busy), the files are asked for one at
                # a time: a host that lags behind must not stop a download.
                log.debug("Pack download refused (%s): one by one", e)
                self._no_pack_downloads = True
                answer.alone = list(shas)
                return answer
            wanted = set(shas)
            offset = 0
            with reply:
                reader = _FrameReader(reply)
                try:
                    while not (stop is not None and stop.is_set()):
                        line = reader.line()
                        if line is None:
                            break
                        sha, _, rest = line.partition(" ")
                        if sha not in wanted or sha in answer.files:
                            raise SyncError("That is not a pack", retryable=True)
                        if rest == "absent":
                            answer.absent.add(sha)
                        elif rest.startswith("big "):
                            answer.alone.append(sha)
                        else:
                            size = int(rest)
                            if not 0 <= size <= PACK_DOWNLOAD_FILE_MAX or (
                                offset + size > PACK_DOWNLOAD_MAX_BYTES
                            ):
                                raise SyncError("That is not a pack", retryable=True)
                            answer.spool.seek(offset)
                            digest = hashlib.sha256()
                            reader.copy(size, answer.spool, digest)
                            answer.files[sha] = (offset, size, digest.hexdigest())
                            offset += size
                        wanted.discard(sha)
                except (SyncError, OSError, ValueError, UnicodeError) as e:
                    log.debug("A pack was cut off: %s", e)
            # What the answer never got to is asked for alone.
            answer.alone += [s for s in shas if s in wanted and s not in answer.alone]
            return answer
        except BaseException:
            answer.close()
            raise

    def _open_file(
        self, sha256: str, byte_range: tuple[int, int] | None = None
    ) -> Reply:
        """A file's answer, open: the authority's own (the bytes asked for, when
        it does ranges), or storage's when it sends the device there (a 307,
        fetched without the session: the URL is the leave, and the session must
        not go to another host; `from_storage` is set on that answer, which is
        the whole file). FileNotFoundError when it has not got the file."""
        extra = (
            {"Range": f"bytes={byte_range[0]}-{byte_range[1]}"} if byte_range else None
        )
        try:
            response = self._again_if_expired(
                lambda: self._call(
                    "GET", f"/files/{sha256}", stream=True, gzip=False, extra=extra
                )
            )
            if response.status in (301, 302, 303, 307, 308):
                location = response.header("Location")
                response.close()
                response = self._open_storage(location, sha256)
                response.from_storage = True  # type: ignore[attr-defined]
        except SyncError as e:
            if e.status == 404:  # the server answered: it doesn't have it
                raise FileNotFoundError(sha256) from e
            if byte_range is not None and e.status == 416:  # an empty file
                return self._open_file(sha256)
            raise
        return response

    def file_chunks(self, sha256: str) -> Iterator[bytes]:
        """A file's bytes from the server, as they arrive. Asks at once, so a
        file the server hasn't got raises FileNotFoundError here, before
        anything is written. The caller checks the hash of what it wrote."""
        response = self._open_file(sha256)

        def read() -> Iterator[bytes]:
            with response:
                while chunk := response.read(_CHUNK):
                    yield chunk

        return read()

    def fetch_file(self, sha256: str, stop: threading.Event | None = None) -> Any:
        """A file's bytes from the server in a spool, read from its start; None
        when the server has not got it (or it was stopped). The first request
        asks for the first range: a small file comes whole in it, a big one
        says (Content-Range) how big it is, and the other ranges follow, several
        at a time, written into a temporary file where each belongs. An answer
        with the whole file (a server that does no ranges, or a bucket's
        presigned download) is one stream, never asked for again. The caller
        checks the hash of the whole, and closes the spool."""
        try:
            reply = self._open_file(sha256, (0, DOWNLOAD_PART_BYTES - 1))
        except FileNotFoundError:
            return None
        total = _range_total(reply) if reply.status == 206 else None
        if total is not None and total > DOWNLOAD_PART_BYTES:
            if total >= DOWNLOAD_PARTS_MIN_BYTES:
                return self._fetch_in_ranges(sha256, total, stop, reply)
            # Two or three ranges' worth: one stream is as quick. The rest of
            # the file is asked for from where this answer ends.
            return self._stream_from(sha256, total, stop, reply)
        spool = tempfile.SpooledTemporaryFile(max_size=FILE_SPOOL_BYTES)
        try:
            digest = hashlib.sha256()
            self._drain(reply, spool, 0, stop, digest)
            spool.digest = digest.hexdigest()  # type: ignore[attr-defined]
            spool.seek(0)
            return spool
        except BaseException:
            spool.close()
            raise

    def _drain(
        self,
        reply: Reply,
        out: Any,
        at: int,
        stop: threading.Event | None,
        digest: Any = None,
    ) -> int:
        """Write a reply's body to `out` from offset `at`; the offset after it.
        A body shorter than its Content-Length is a SyncError."""
        want = reply.header("Content-Length")
        start = at
        with reply:
            while chunk := reply.read(_CHUNK):
                if stop is not None and stop.is_set():
                    return at
                out.seek(at)
                out.write(chunk)
                if digest is not None:
                    digest.update(chunk)
                at += len(chunk)
        if want.isdigit() and at - start != int(want):
            raise SyncError("A file came down cut short", retryable=True)
        return at

    def _stream_from(
        self, sha256: str, total: int, stop: threading.Event | None, first: Reply
    ) -> Any:
        spool = tempfile.SpooledTemporaryFile(max_size=FILE_SPOOL_BYTES)
        try:
            digest = hashlib.sha256()
            at = self._drain(first, spool, 0, stop, digest)
            while at < total and not (stop is not None and stop.is_set()):
                last = min(total, at + DOWNLOAD_PART_BYTES) - 1
                reply = self._open_range(sha256, at, last)
                at = self._drain(reply, spool, at, stop, digest)
            spool.digest = digest.hexdigest()  # type: ignore[attr-defined]
            spool.seek(0)
            return spool
        except BaseException:
            spool.close()
            raise

    def _open_range(self, sha256: str, first: int, last: int) -> Reply:
        reply = self._open_file(sha256, (first, last))
        if reply.status != 206 or not reply.header("Content-Range").startswith(
            f"bytes {first}-{last}/"
        ):
            reply.close()
            raise SyncError("The server did not answer the range asked", retryable=True)
        return reply

    def _fetch_in_ranges(
        self,
        sha256: str,
        total: int,
        stop: threading.Event | None,
        first: Reply,
    ) -> Any:
        """The ranges after the first (which `first` holds) are fetched by the
        shared pool, the first is read here; each goes where it belongs in one
        temporary file. A range that fails is asked for again, alone."""
        out = tempfile.TemporaryFile()
        lock = threading.Lock()
        failed = threading.Event()

        def put(reply: Reply, at: int, last: int) -> None:
            with reply:
                while chunk := reply.read(_CHUNK):
                    if at + len(chunk) > last + 1:
                        raise SyncError("A range was longer than asked")
                    with lock:
                        out.seek(at)
                        out.write(chunk)
                    at += len(chunk)
                    if failed.is_set() or (stop is not None and stop.is_set()):
                        return
            if at != last + 1:
                raise SyncError("A range came down cut short", retryable=True)

        def fetch(begin: int, answer: Reply | None = None) -> None:
            last = min(total, begin + DOWNLOAD_PART_BYTES) - 1
            for attempt in range(1, DOWNLOAD_PART_TRIES + 1):
                if failed.is_set() or (stop is not None and stop.is_set()):
                    if answer is not None:
                        answer.close()
                    return
                try:
                    put(answer or self._open_range(sha256, begin, last), begin, last)
                    return
                except (OSError, SyncError) as e:
                    answer = None  # asked for again
                    if (
                        attempt == DOWNLOAD_PART_TRIES
                        or isinstance(e, FileNotFoundError)
                        or (isinstance(e, SyncError) and not e.retryable)
                    ):
                        raise

        try:
            out.truncate(total)
            pool = self._part_pool()
            futures = [
                pool.submit(fetch, begin)
                for begin in range(DOWNLOAD_PART_BYTES, total, DOWNLOAD_PART_BYTES)
            ]
            error: BaseException | None = None
            try:
                fetch(0, first)
            except BaseException as e:  # noqa: BLE001 - raised below
                failed.set()
                error = e
            for future in futures:
                try:
                    future.result()
                except BaseException as e:  # noqa: BLE001 - raised below
                    failed.set()
                    error = error or e
            if error is not None:
                raise error
            if stop is not None and stop.is_set():
                out.close()  # not all of it came: nothing for the caller to keep
                return None
            out.seek(0)
            return out
        except BaseException:
            out.close()
            raise

    def _part_pool(self) -> ThreadPoolExecutor:
        with self._session_lock:
            if self._parts is None:
                self._parts = ThreadPoolExecutor(DOWNLOAD_PART_THREADS)
            return self._parts

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
        grant = SessionGrant.from_dict(
            self._plain("POST", "/session", body, idempotent=True).json()
        )
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

    def _plain(
        self,
        method: str,
        path: str,
        body: Any = None,
        idempotent: bool | None = None,
    ) -> Reply:
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
            idempotent=idempotent,
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
        idempotent: bool | None = None,
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
            idempotent=idempotent,
        )

    def _json(
        self,
        method: str,
        path: str,
        body: Any = None,
        timeout: float | None = None,
        gzip_body: bool = False,
        idempotent: bool | None = None,
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
                idempotent=idempotent,
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


def _range_total(reply: Reply) -> int | None:
    """The size of the whole file, from a 206's `Content-Range: bytes a-b/total`."""
    _, _, total = reply.header("Content-Range").rpartition("/")
    return int(total) if total.isdigit() else None


class _PackBody:
    """A pack's request body, read as it is sent: for each file a line
    `<sha256> <size>` and the file's bytes (a megabyte at a time). It can be
    rewound, to send again. It holds the one chunk in hand (a megabyte), and
    hands it out in slices, without copying it again."""

    def __init__(self, items: list[tuple[str, UploadSource, int]]) -> None:
        self._items = items
        self.length = sum(len(f"{sha} {size}\n") + size for sha, _, size in items)
        self.rewind()

    def rewind(self) -> None:
        for _, source, _ in self._items:
            source.seek(0)
        self._frames = self._generate()
        self._chunk = memoryview(b"")
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
        out: list[bytes] = []
        want = n
        while want != 0:
            if self._pos >= len(self._chunk):
                nxt = next(self._frames, None)
                if nxt is None:
                    break
                self._chunk = memoryview(nxt)
                self._pos = 0
            take = (
                len(self._chunk) - self._pos
                if want < 0
                else min(want, len(self._chunk) - self._pos)
            )
            out.append(self._chunk[self._pos : self._pos + take].tobytes())
            self._pos += take
            if want > 0:
                want -= take
        return out[0] if len(out) == 1 else b"".join(out)


def _part_size_for(size: int) -> int:
    """The part size asked for: FILE_PART_BYTES (smaller on a small machine),
    but a file is cut into about PARTS_PER_FILE parts (each a whole number of
    MiB, none under FILE_PART_MIN) when that is smaller, so that a middling
    file is not a single stream either: 16 MiB goes as 4 parts of 4 MiB, 8 MiB
    and a byte as 3 of 3 MiB."""
    even = -(-size // PARTS_PER_FILE)
    even = -(-even // FILE_PART_MIN) * FILE_PART_MIN
    return max(1, min(FILE_PART_BYTES, transfer_budget.windows().part_bytes, even))


class UploadStopped(Exception):
    """An upload was ended between parts because the sender is stopping."""


_lane_lock = threading.Lock()
_lane: tuple[int, ThreadPoolExecutor, queue.Queue[bytearray]] | None = None


def _part_lane() -> tuple[ThreadPoolExecutor, queue.Queue[bytearray]]:
    """The pool every part of every file goes through, and the buffers its
    parts are read into: one per part in flight, reused for every part, so
    the parts held (queued or sending) are at most the pool's width and memory
    does not grow with the number of parts sent."""
    global _lane
    width = transfer_budget.windows().part_threads
    with _lane_lock:
        if _lane is None or _lane[0] != width:
            buffers: queue.Queue[bytearray] = queue.Queue()
            for _ in range(width):
                buffers.put(bytearray())
            _lane = (
                width,
                ThreadPoolExecutor(width, thread_name_prefix="civex-part"),
                buffers,
            )
        return _lane[1], _lane[2]


def _read_into(source: Any, view: memoryview) -> int:
    readinto = getattr(source, "readinto", None)
    if readinto is not None:
        return int(readinto(view))
    data = source.read(len(view))
    view[: len(data)] = data
    return len(data)


def _in_parts(
    source: UploadSource,
    size: int,
    part_size: int,
    held: set[int],
    put: Callable[[int, memoryview], None],
    stop: Callable[[], bool] | None = None,
) -> None:
    """Read `source` a part at a time and `put` each (but those in `held`)
    through the shared part pool. One thread per file reads, in order, so the
    file is read once; before a part is read it takes a buffer (the pool's
    width, all files together) and its bytes from the process budget, and gives
    both back when the part is sent, so memory holds at most that many parts
    however many files are on their way. `put` gets a view of the buffer, valid
    until it returns. The first failure stops reading, lets this file's parts
    in flight finish (they stay with the authority, for the next try), and is
    raised; `stop` is asked before each part and ends the upload the same way
    with `UploadStopped`."""
    count = max(1, -(-size // part_size)) if size else 0
    pool, buffers = _part_lane()
    budget = transfer_budget.process_budget()
    flying: set[Future[None]] = set()
    failure: list[BaseException] = []
    stopped = False

    def send(number: int, buf: bytearray, length: int, charged: int) -> None:
        try:
            with memoryview(buf) as view:
                put(number, view[:length])
        except BaseException as e:
            # (without the traceback: its frames would hold the part)
            failure.append(e.with_traceback(None))
            raise
        finally:
            budget.release(charged)
            buffers.put(buf)

    try:
        for number in range(1, count + 1):
            length = min(part_size, size - (number - 1) * part_size)
            if number in held:
                source.seek(length, 1)  # held already: counted, not sent
                continue
            if failure:
                break
            if stop is not None and stop():
                stopped = True
                break
            buf = buffers.get()
            try:
                charged = budget.acquire(length)
            except BaseException:
                buffers.put(buf)
                raise
            if failure or (stop is not None and stop()):
                stopped = not failure
                budget.release(charged)
                buffers.put(buf)
                break
            try:
                if len(buf) < length:
                    buf = bytearray(length)
                with memoryview(buf) as view:
                    got = _read_into(source, view[:length])
            except BaseException:
                budget.release(charged)
                buffers.put(buf)
                raise
            if got != length:
                budget.release(charged)
                buffers.put(buf)
                raise SyncError("A file being sent was cut short", retryable=True)
            flying.add(pool.submit(send, number, buf, length, charged))
            flying -= {f for f in flying if f.done()}
    finally:
        wait(flying)
    if failure:
        raise failure[0]
    if stopped:
        raise UploadStopped()


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
    "build_transport",
]
