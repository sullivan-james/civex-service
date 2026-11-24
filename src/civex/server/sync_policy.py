"""The policies every `/sync/v1` route shares, applied at the router so they
travel with `api_routers` to a host that mounts the routers itself (the hub),
not with civex's own app:

* request deadlines: on PostgreSQL `SET LOCAL lock_timeout` for the calls that
  take the feed's lock or number entries, and `SET LOCAL statement_timeout` for
  the reads (`SET LOCAL` only: it ends with the transaction, so it never leaks
  into a shared pool or PgBouncer); on SQLite the busy timeout the engine
  already sets. A timeout is answered 503 + `Retry-After` (`BusyError`), after
  which the device asks again.
* wire encoding: a JSON request body sent `Content-Encoding: gzip` is
  decompressed as a stream up to a cap (413 `too_large` past it), and a JSON
  answer over `GZIP_MIN_BYTES` is gzipped for a caller that accepts it. File
  bytes, packs, parts and downloads are never touched (not JSON).

Migrations, partition conversion and reclaim do not go through these routes and
are not subject to them."""

from __future__ import annotations

import gzip
import os
import zlib
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends, Request, Response
from fastapi.routing import APIRoute
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from civex.context import AppContext
from civex.domain.exceptions import ValidationError
from civex.server.deps import get_ctx
from civex.server.errors import BusyError, TooLargeError

# How long a call may wait for a lock (the feed's counter, numbering).
LOCK_TIMEOUT_MS = 10_000
# How long one statement of a read may run.
STATEMENT_TIMEOUT_MS = 15_000
# What a busy answer tells the device to wait, seconds.
RETRY_AFTER_SECONDS = 2

# Which routes (by function name) the deadlines apply to, and which of the two.
# A route not named has neither (files, library, join, login). Every route is
# named in exactly one of `DEADLINED` or `UNLIMITED`: a test holds that, so a
# route added later has to be classified.
READS = frozenset({"hello", "feed", "snapshot"})
LOCKING = frozenset({"push"})
UNLIMITED = frozenset(
    {
        "join",
        "request_login",
        "poll_login",
        "session",
        "files_missing",
        "upload_file",
        "upload_pack",
        "begin_parts",
        "upload_part",
        "complete_parts",
        "upload_target",
        "complete_upload",
        "download_file",
        "library",
        "library_item",
        "publish",
        "unpublish",
    }
)

# Decompressed size cap of a request body.
DEFAULT_MAX_REQUEST_BYTES = 64 * 1024 * 1024
MAX_REQUEST_BYTES_ENV = "CIVEX_SYNC_MAX_REQUEST_BYTES"
# A JSON answer smaller than this is sent as it is.
GZIP_MIN_BYTES = 1024

# SQLSTATEs of a lock wait or statement that ran out of time, or was chosen as
# the victim of a deadlock: nothing was done, the same call can be repeated.
_BUSY_SQLSTATES = frozenset({"55P03", "57014", "40P01", "40001"})


def max_request_bytes() -> int:
    raw = os.environ.get(MAX_REQUEST_BYTES_ENV)
    try:
        return int(raw) if raw else DEFAULT_MAX_REQUEST_BYTES
    except ValueError:
        return DEFAULT_MAX_REQUEST_BYTES


# ----------------------------------------------------------------------
# Deadlines
# ----------------------------------------------------------------------


def deadlines(
    request: Request,
    ctx: AppContext = Depends(get_ctx, scope="function"),
) -> None:
    """Router-level dependency: set this request's transaction deadlines."""
    route = request.scope.get("route")
    name = getattr(route, "name", "")
    if name not in READS and name not in LOCKING:
        return
    session = ctx._session
    if session.get_bind().dialect.name != "postgresql":
        return  # SQLite: the connection's busy timeout (db/engine.py) is the wait
    session.execute(text(f"SET LOCAL lock_timeout = {LOCK_TIMEOUT_MS}"))
    if name in READS:
        session.execute(text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))


def is_busy(error: BaseException) -> bool:
    """Whether a database error is a wait that ran out (a lock, a statement
    deadline, a deadlock, SQLite's busy lock) rather than a fault."""
    if not isinstance(error, DBAPIError):
        return False
    orig = error.orig
    state = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if state is not None:
        return str(state) in _BUSY_SQLSTATES
    message = str(orig).lower()
    return "database is locked" in message or "database table is locked" in message


# ----------------------------------------------------------------------
# Wire encoding
# ----------------------------------------------------------------------


class _GzipRequest(Request):
    """A request whose gzip body reads as the JSON it holds. Decompression is
    streamed and stops at the cap, so a small body cannot expand into memory."""

    async def body(self) -> bytes:
        if not hasattr(self, "_body"):
            cap = max_request_bytes()
            inflater = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
            out = bytearray()
            try:
                async for chunk in self.stream():
                    pending = chunk
                    while pending:
                        out += inflater.decompress(pending, cap + 1 - len(out))
                        if len(out) > cap:
                            raise _too_large(cap)
                        pending = inflater.unconsumed_tail
                out += inflater.flush()
            except zlib.error as e:
                raise ValidationError(f"The request body is not valid gzip: {e}")
            if len(out) > cap or not inflater.eof:
                if len(out) > cap:
                    raise _too_large(cap)
                raise ValidationError("The request body is not valid gzip: cut short")
            self._body = bytes(out)
        return self._body


def _too_large(cap: int) -> TooLargeError:
    return TooLargeError(
        f"The request is over {cap // (1024 * 1024)} MiB once decompressed", cap
    )


def _gzipped_json(request: Request) -> bool:
    headers = request.headers
    return (
        headers.get("content-encoding", "").strip().lower() == "gzip"
        and "json" in headers.get("content-type", "").lower()
    )


def _accepts_gzip(request: Request) -> bool:
    for part in request.headers.get("accept-encoding", "").split(","):
        token, _, params = part.partition(";")
        if token.strip().lower() in ("gzip", "x-gzip"):
            q = params.replace(" ", "").lower()
            return q not in ("q=0", "q=0.0", "q=0.00", "q=0.000")
    return False


def compress_response(request: Request, response: Response) -> Response:
    """Gzip a JSON answer over `GZIP_MIN_BYTES` for a caller that accepts it.
    Only answers held in memory as JSON: a download, a stream or a file is
    never compressed."""
    if (
        response.status_code != 200
        or "content-encoding" in response.headers
        or not response.headers.get("content-type", "").startswith("application/json")
        or not isinstance(response.body, (bytes, bytearray))
        or len(response.body) < GZIP_MIN_BYTES
        or not _accepts_gzip(request)
    ):
        return response
    body = gzip.compress(bytes(response.body), compresslevel=5, mtime=0)
    response.body = body
    response.headers["content-encoding"] = "gzip"
    response.headers["content-length"] = str(len(body))
    response.headers.append("vary", "Accept-Encoding")
    return response


class SyncRoute(APIRoute):
    """The route class of every `/sync/v1` route: the wire encoding and the
    translation of a database that ran out of time to 503 + `Retry-After`."""

    def get_route_handler(
        self,
    ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def sync_handler(request: Request) -> Response:
            if _gzipped_json(request):
                request = _GzipRequest(request.scope, request.receive)
                # Read here, not by FastAPI, which turns any error while
                # reading a body into a plain 400: ours are 413 and 422.
                await request.body()
            try:
                response = await handler(request)
            except DBAPIError as e:
                if is_busy(e):
                    raise BusyError(
                        "The server is busy: nothing was done, try again",
                        RETRY_AFTER_SECONDS,
                    ) from e
                raise
            return compress_response(request, response)

        return sync_handler
