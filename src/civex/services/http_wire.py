"""The one HTTP client every call to an authority goes through.

What it settles, once, for sync, device sign-in, files, packs, parts, the
shared library and a release bundle:

- Connections: one keep-alive connection per thread per host (uploads use
  several threads), so a pass pays for TCP and TLS once, not once a request.
  A connection that sat idle past what a server keeps open, or that the server
  closed meanwhile, is replaced and the request sent again, once.
- Redirects: never followed with the session token to another host (a presigned
  storage URL is the leave); `follow` says what a call allows.
- Compression: `Accept-Encoding: gzip` on a call that asks for it, and the
  answer decoded. A request body is gzipped by the caller, when the authority
  offers to read it.
- One status table (`status_error`, `Wire.request`): 429 and 503 wait what
  `Retry-After` says (seconds or a date, capped, jittered) and the same request
  is sent again inside the pass; a network error, a timeout and other 5xx back
  off exponentially with jitter; 402, 413 and the rest of the 4xx are refused
  with a message for the person and are not retried. What is still failing
  after the bounded retries is a `SyncError` carrying `retry_after`, for the
  background worker to wait on.
"""

from __future__ import annotations

import gzip
import http.client
import json
import random
import socket
import threading
import time
import urllib.error
import urllib.parse
from collections.abc import Callable, Mapping
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import Any

from civex.domain.sync import SyncError, protocol_mismatch
from civex.tls import certificate_problem, ssl_context

# The longest a Retry-After is believed, before jitter.
RETRY_AFTER_CAP_SECONDS = 120.0
# Waits inside one call (status or network), and how many times it is sent again.
MAX_STATUS_RETRIES = 4
MAX_NETWORK_RETRIES = 3
MAX_TOTAL_WAIT_SECONDS = 180.0
BACKOFF_BASE_SECONDS = 0.5
BACKOFF_CAP_SECONDS = 30.0
JITTER = 0.25
# A kept-open connection idle this long is not trusted: servers close theirs.
IDLE_SECONDS = 30.0
MAX_REDIRECTS = 5
_REDIRECTS = (301, 302, 303, 307, 308)
_STALE = (
    http.client.RemoteDisconnected,
    http.client.CannotSendRequest,
    http.client.BadStatusLine,
    BrokenPipeError,
    ConnectionResetError,
    ConnectionAbortedError,
)


def jittered(seconds: float, rng: random.Random | None = None) -> float:
    """`seconds` spread by +-25%, so devices that failed together don't retry
    together."""
    return seconds * (rng or random).uniform(1 - JITTER, 1 + JITTER)


def backoff_seconds(attempt: int, rng: random.Random | None = None) -> float:
    """Exponential back-off for the `attempt`-th retry (0 first), jittered."""
    return jittered(min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * 2**attempt), rng)


def parse_retry_after(value: str | None, now: float | None = None) -> float | None:
    """What a `Retry-After` header asks for, in seconds (it is delta-seconds or
    an HTTP date), or None when absent or unreadable. Never negative."""
    if not value or not value.strip():
        return None
    text = value.strip()
    try:
        seconds = float(text)
    except ValueError:
        try:
            when = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
        seconds = when.timestamp() - (time.time() if now is None else now)
    if seconds != seconds or seconds in (float("inf"), float("-inf")):
        return None
    return max(0.0, seconds)


def retry_wait(
    retry_after: float | None, attempt: int, rng: random.Random | None = None
) -> float:
    """How long to wait before sending again: what the server asked (capped),
    else the exponential back-off; jittered either way."""
    if retry_after is None:
        return backoff_seconds(attempt, rng)
    return jittered(min(retry_after, RETRY_AFTER_CAP_SECONDS), rng)


class Reply:
    """An answer: status, headers and (unless streamed) the whole body, with a
    gzip body already decoded."""

    def __init__(
        self,
        status: int,
        headers: Message,
        body: bytes = b"",
        stream: http.client.HTTPResponse | None = None,
        conn: http.client.HTTPConnection | None = None,
    ) -> None:
        self.status = status
        self.headers = headers
        self.body = body
        self._stream = stream
        self._conn = conn

    def header(self, name: str, default: str = "") -> str:
        return str(self.headers.get(name, default) or default)

    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8")) if self.body else {}

    def read(self, n: int = -1) -> bytes:
        assert self._stream is not None, "not a streamed reply"
        return self._stream.read(n) if n >= 0 else self._stream.read()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> Reply:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def detail_of(reply: Reply) -> Any:
    """The `detail` of a JSON error body (a string, or an object with a `code`),
    or None for an HTML page or nothing."""
    try:
        body = json.loads(reply.body.decode("utf-8"))
    except Exception:  # noqa: BLE001 - an HTML error page, or nothing
        return None
    if isinstance(body, dict):
        detail = body.get("detail")
        if detail is None and "code" in body:
            return body
        return detail
    return None


def _code(detail: Any) -> str:
    if isinstance(detail, dict):
        return str(detail.get("code") or "")
    return ""


def _words(detail: Any) -> str:
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("detail") or "")
    return str(detail) if detail else ""


def mismatch_words(detail: Any) -> str:
    """A 426 in this computer's words: which side to update. A server from
    before the protocol range says it in a sentence of its own."""
    if not isinstance(detail, dict) or "protocol_max" not in detail:
        return str(detail or "The server speaks another sync protocol")
    theirs = (int(detail["protocol_min"]), int(detail["protocol_max"]))
    return protocol_mismatch(
        theirs, "the server", "this computer", detail.get("server_version")
    )


def retries(status: int) -> bool:
    """Whether the table has the same request sent again, inside the pass."""
    return status in (408, 429) or (status >= 500 and status not in (501, 507, 505))


def status_error(reply: Reply, not_found: str | None = None) -> SyncError:
    """The `SyncError` for a failed answer, in words for the person, saying
    whether trying again later can help. `not_found` is what a 404 means for
    this call (default: not a civex sync server)."""
    status = reply.status
    detail = detail_of(reply)
    text = _words(detail) or f"The server answered {status}"
    wait = parse_retry_after(reply.header("Retry-After"))

    def err(message: str, retryable: bool) -> SyncError:
        return SyncError(message, retryable=retryable, status=status, retry_after=wait)

    if status == 426:
        return err(mismatch_words(detail), False)
    if status == 401:
        return err(f"The server refused this device: {text}", False)
    if status == 402:
        return err(
            f"The server needs a plan or payment change before it takes this: {text}",
            False,
        )
    if status == 403:
        return err(text, False)  # signed in, but not allowed to do that
    if status == 404:
        return err(
            not_found
            or "That address is not a civex sync server (or sync is not switched "
            "on there)",
            False,
        )
    if status == 413:
        return err(
            "This change is too big to send in one go: the server refused it "
            "as too large. Make it in smaller steps"
            + (f" ({text})" if text and _code(detail) != "too_large" else ""),
            False,
        )
    if status == 429:
        return err(text if detail else "The server is busy: too many requests", True)
    if status == 503:
        return err(text if detail else "The server is busy or restarting", True)
    if status == 501:
        return err(text, False)  # exists but doesn't do that: waiting won't change it
    if status in (408,) or status >= 500:
        return err(text, retries(status) or status == 507)
    return err(text, False)


def _sleep_default(seconds: float) -> None:
    time.sleep(seconds)


class Wire:
    """A keep-alive HTTP client, safe to share between threads (each thread
    keeps its own connections)."""

    def __init__(
        self,
        sleep: Callable[[float], None] = _sleep_default,
        rng: random.Random | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sleep = sleep
        self._rng = rng
        self._clock = clock
        self._local = threading.local()
        self._lock = threading.Lock()
        self._all: list[http.client.HTTPConnection] = []
        self.connections_made = 0

    # -- connections -----------------------------------------------------

    def _connect(
        self, parts: urllib.parse.SplitResult, timeout: float
    ) -> http.client.HTTPConnection:
        host = parts.hostname or ""
        if parts.scheme == "https":
            conn: http.client.HTTPConnection = http.client.HTTPSConnection(
                host, parts.port, timeout=timeout, context=ssl_context()
            )
        else:
            conn = http.client.HTTPConnection(host, parts.port, timeout=timeout)
        with self._lock:
            self.connections_made += 1
            self._all.append(conn)
        return conn

    def _forget(self, conn: http.client.HTTPConnection) -> None:
        conn.close()
        with self._lock:
            if conn in self._all:
                self._all.remove(conn)

    def _pooled(
        self, parts: urllib.parse.SplitResult, timeout: float
    ) -> tuple[http.client.HTTPConnection, bool]:
        """This thread's connection to the host and whether it is a reused one."""
        pool: dict[tuple[str, str, int | None], list[Any]] = self.__dict_of_thread()
        key = (parts.scheme, parts.hostname or "", parts.port)
        held = pool.get(key)
        if held is not None:
            conn, used = held
            if self._clock() - used <= IDLE_SECONDS and conn.sock is not None:
                try:
                    conn.timeout = timeout
                    conn.sock.settimeout(timeout)
                    return conn, True
                except OSError:  # the socket is gone: make a new one
                    pass
            self._forget(conn)
            del pool[key]
        conn = self._connect(parts, timeout)
        pool[key] = [conn, self._clock()]
        return conn, False

    def __dict_of_thread(self) -> dict[tuple[str, str, int | None], list[Any]]:
        pool = getattr(self._local, "pool", None)
        if pool is None:
            pool = self._local.pool = {}
        return pool  # type: ignore[no-any-return]

    def _drop(self, parts: urllib.parse.SplitResult) -> None:
        pool = self.__dict_of_thread()
        held = pool.pop((parts.scheme, parts.hostname or "", parts.port), None)
        if held is not None:
            self._forget(held[0])

    def close(self) -> None:
        """Close every connection (all threads')."""
        with self._lock:
            conns, self._all = self._all, []
        for conn in conns:
            conn.close()
        self._local = threading.local()

    # -- one request -----------------------------------------------------

    def _once(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: Any,
        timeout: float,
        stream: bool,
    ) -> Reply:
        """Send one request. Whether the connection was a reused one is left
        in `_local.reused`: a failure on a reused one may only mean the server
        closed it. A streamed reply holds a connection of its own."""
        parts = urllib.parse.urlsplit(url)
        target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        if stream:
            conn, reused = self._connect(parts, timeout), False
        else:
            conn, reused = self._pooled(parts, timeout)
        self._local.reused = reused
        try:
            try:
                conn.request(method, target, body=body, headers=dict(headers))
            except (BrokenPipeError, ConnectionResetError):
                # The server may have answered (413) and closed before the
                # body went: its answer is better than "broken pipe".
                if not self._early_answer_readable(conn):
                    raise
            response = conn.getresponse()
            if stream:
                return Reply(response.status, response.msg, b"", response, conn)
            data = response.read()
            if response.will_close:
                self._drop(parts)
            if response.getheader("Content-Encoding", "").lower() == "gzip" and data:
                data = gzip.decompress(data)
            held = self.__dict_of_thread().get(
                (parts.scheme, parts.hostname or "", parts.port)
            )
            if held is not None:
                held[1] = self._clock()
            return Reply(response.status, response.msg, data)
        except BaseException:
            if stream:
                self._forget(conn)
            else:
                self._drop(parts)
            raise

    def _local_reused(self) -> bool:
        return bool(getattr(self._local, "reused", False))

    @staticmethod
    def _early_answer_readable(conn: http.client.HTTPConnection) -> bool:
        return conn.sock is not None

    # -- a call, with the status table -----------------------------------

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: Any = None,
        timeout: float = 60.0,
        prepare: Callable[[], None] | None = None,
        stream: bool = False,
        follow: str = "never",
        accept_gzip: bool = False,
        raise_for_status: bool = True,
        not_found: str | None = None,
        what: str = "the server",
    ) -> Reply:
        """Send a request and answer its reply, applying the status table.

        `prepare` is called before every attempt (rewind a body). `follow` is
        "never" (a 3xx is answered as it is), "same_host" (followed within the
        host, never from https down to http) or "strip_auth" (also to another
        host, without the `Authorization`). With `raise_for_status` (default) a
        failing answer is a `SyncError` (`status_error`); without it, the last
        answer is returned for the caller to read."""
        send_headers = dict(headers or {})
        if accept_gzip:
            send_headers["Accept-Encoding"] = "gzip"
        status_retries = network_retries = 0
        waited = 0.0
        stale_tried = False
        hops = 0
        while True:
            if prepare:
                prepare()
            try:
                reply = self._once(method, url, send_headers, body, timeout, stream)
            except (OSError, http.client.HTTPException) as e:
                if reused_stale(e) and not stale_tried and self._local_reused():
                    stale_tried = True  # the server closed an idle connection
                    continue
                problem = certificate_problem(urllib.error.URLError(e))
                if problem:
                    raise SyncError(
                        f"Could not reach {what}: {problem}", retryable=False
                    ) from e
                limit = 1 if isinstance(e, socket.timeout) else MAX_NETWORK_RETRIES
                if network_retries >= limit:
                    raise SyncError(
                        f"Could not reach {what}: {_reason(e)}", detail=str(e)
                    ) from e
                wait = backoff_seconds(network_retries, self._rng)
                network_retries += 1
                waited += wait
                self._sleep(wait)
                continue
            status = reply.status
            if status in _REDIRECTS and follow != "never" and hops < MAX_REDIRECTS:
                location = reply.header("Location")
                reply.close()
                new = urllib.parse.urljoin(url, location)
                old_p, new_p = urllib.parse.urlsplit(url), urllib.parse.urlsplit(new)
                if old_p.scheme == "https" and new_p.scheme != "https":
                    raise SyncError(
                        "The server redirected to an unencrypted address",
                        retryable=False,
                        status=status,
                    )
                same = (old_p.hostname, old_p.port) == (new_p.hostname, new_p.port)
                if not same:
                    if follow != "strip_auth":
                        raise SyncError(
                            "The server redirected to another address; the "
                            "session is not sent there",
                            retryable=False,
                            status=status,
                        )
                    send_headers.pop("Authorization", None)
                if status in (301, 302, 303):
                    method, body = ("GET" if method != "HEAD" else method), None
                    send_headers.pop("Content-Length", None)
                    send_headers.pop("Content-Type", None)
                url = new
                hops += 1
                continue
            if status < 400 or (status in _REDIRECTS):
                return reply
            if retries(status) and status_retries < MAX_STATUS_RETRIES:
                after = parse_retry_after(reply.header("Retry-After"))
                wait = retry_wait(after, status_retries, self._rng)
                if waited + wait <= MAX_TOTAL_WAIT_SECONDS:
                    reply.close()
                    status_retries += 1
                    waited += wait
                    self._sleep(wait)
                    continue
            if not raise_for_status:
                return reply
            if stream:
                reply.body = _drain(reply)
                reply.close()
            raise status_error(reply, not_found)


def reused_stale(error: BaseException) -> bool:
    return isinstance(error, _STALE)


def _drain(reply: Reply) -> bytes:
    try:
        return reply.read(65536)
    except Exception:  # noqa: BLE001
        return b""


def _reason(error: BaseException) -> str:
    return str(getattr(error, "reason", None) or error)


__all__ = [
    "Reply",
    "Wire",
    "backoff_seconds",
    "jittered",
    "parse_retry_after",
    "retry_wait",
    "status_error",
]
