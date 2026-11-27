"""The policies every `/sync/v1` route shares, applied at the router so they
travel with `api_routers` to a host that mounts the routers itself (the hub),
not with civex's own app:

* request deadlines: on PostgreSQL `SET LOCAL lock_timeout` for the calls that
  take the feed's lock or number entries, and `SET LOCAL statement_timeout` for
  the reads (`SET LOCAL` only: it ends with the transaction, so it never leaks
  into a shared pool or PgBouncer); on SQLite the busy timeout the engine
  already sets. A timeout is answered 503 + `Retry-After` (`BusyError`), after
  which the device asks again. Numbering a backlog suspends the statement
  timeout for that one statement (`sequence_local_entries`).
* wire encoding: only `push` takes a gzip request body, read after the caller
  is authenticated and inflated off the event loop, streamed up to a cap (413
  `too_large` past it); any other JSON route refuses `Content-Encoding` (415).
  A JSON answer over `GZIP_MIN_BYTES` is gzipped for a caller that accepts it,
  except those of `push`, `join` and `device-login`: a host in front (the hub)
  reads those and will decode them later. File bytes, packs, parts and
  downloads are never touched (not JSON).

Migrations, partition conversion and reclaim do not go through these routes and
are not subject to them."""

from __future__ import annotations

import gzip
import os
import zlib
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends, HTTPException, Request, Response
from fastapi.routing import APIRoute
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from starlette.concurrency import run_in_threadpool

from civex.context import AppContext
from civex.domain.exceptions import ValidationError
from civex.server.deps import get_ctx
from civex.server.errors import BusyError, TooLargeError, is_busy_error

# How long a call may wait for a lock (the feed's counter, numbering): well
# above `PUSH_BUDGET_SECONDS` plus the flush after it, so a push that is
# working does not make the calls behind it fail.
LOCK_TIMEOUT_MS = 30_000
# How long one statement of a read may run.
STATEMENT_TIMEOUT_MS = 15_000
# What a busy answer tells the device to wait, seconds.
RETRY_AFTER_SECONDS = 2

# Which routes (by function name) the deadlines apply to, and which of the two.
# Every route is named in exactly one of the sets: a test holds that, so a
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
        "download_pack",
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
# The one route that takes a gzip request body.
GZIP_BODY_ROUTES = frozenset({"push"})
# Answers a host in front reads: never compressed here.
NEVER_COMPRESSED = frozenset({"push", "join", "request_login"})

# Decompressed size cap of a request body.
DEFAULT_MAX_REQUEST_BYTES = 64 * 1024 * 1024
MAX_REQUEST_BYTES_ENV = "CIVEX_SYNC_MAX_REQUEST_BYTES"
# A JSON answer smaller than this is sent as it is.
GZIP_MIN_BYTES = 1024
_INFLATE_STEP = 1024 * 1024


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
    return is_busy_error(error)


# ----------------------------------------------------------------------
# Wire encoding
# ----------------------------------------------------------------------


def _too_large(cap: int) -> TooLargeError:
    return TooLargeError(
        f"The request is over {cap // (1024 * 1024)} MiB once decompressed", cap
    )


def inflate(chunks: list[bytes], cap: int) -> bytearray:
    """The gzip stream `chunks` hold, decompressed in steps and stopped at
    `cap` (so a small body cannot expand into memory), without a second copy
    of the result."""
    inflater = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
    out = bytearray()
    try:
        for chunk in chunks:
            pending = chunk
            while pending:
                step = min(_INFLATE_STEP, cap + 1 - len(out))
                out += inflater.decompress(pending, step)
                if len(out) > cap:
                    raise _too_large(cap)
                pending = inflater.unconsumed_tail
        out += inflater.flush()
    except zlib.error as e:
        raise ValidationError(f"The request body is not valid gzip: {e}") from None
    if len(out) > cap:
        raise _too_large(cap)
    if not inflater.eof:
        raise ValidationError("The request body is not valid gzip: cut short")
    return out


def _encoded(request: Request) -> bool:
    return request.headers.get("content-encoding", "").strip().lower() not in (
        "",
        "identity",
    )


async def _read_chunks(request: Request) -> list[bytes]:
    """The body as it arrives (still compressed), capped."""
    cap = max_request_bytes()
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > cap:
            raise _too_large(cap)
        chunks.append(chunk)
    return chunks


async def prefetch_body(request: Request) -> None:
    """Router-level dependency, the first of them: a route that takes a body
    of its own (`push`) has it read here, before anything holds a database
    connection, so a slow upload never keeps one idle in a transaction. The
    bytes are read as they were sent (compressed): nothing is inflated, and
    nothing is read for a caller nobody has authenticated yet beyond what the
    server read of any request body before."""
    route = request.scope.get("route")
    if getattr(route, "name", "") in GZIP_BODY_ROUTES:
        request.state.sync_body = await _read_chunks(request)


async def read_json_body(request: Request) -> bytes | bytearray:
    """The JSON body of a request that takes a gzip one (read by
    `prefetch_body`), once the caller is authenticated: the inflating runs in
    a thread, up to the cap."""
    cap = max_request_bytes()
    chunks = getattr(request.state, "sync_body", None)
    if chunks is None:
        chunks = await _read_chunks(request)
    if not _encoded(request):
        return b"".join(chunks)
    encoding = request.headers.get("content-encoding", "").strip().lower()
    if encoding != "gzip":
        raise HTTPException(
            415, detail=f"Content-Encoding {encoding!r} is not accepted"
        )
    return await run_in_threadpool(inflate, chunks, cap)


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
        name = self.name

        async def sync_handler(request: Request) -> Response:
            if (
                name not in GZIP_BODY_ROUTES
                and _encoded(request)
                and "json" in request.headers.get("content-type", "").lower()
            ):
                # Refused before anything is read: only push takes one.
                raise HTTPException(
                    415, detail="This route does not take a compressed body"
                )
            try:
                response = await handler(request)
            except DBAPIError as e:
                if is_busy_error(e):
                    raise BusyError(
                        "The server is busy: nothing was done, try again",
                        RETRY_AFTER_SECONDS,
                    ) from e
                raise
            if name in NEVER_COMPRESSED:
                return response
            return compress_response(request, response)

        return sync_handler
