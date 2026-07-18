"""
HTTP error boundary and request-context middleware.

Split of responsibilities:
  * 4xx from a CivexError carry an intentional, user-facing message — surfaced as-is.
  * RequestValidationError → clean 422 with `input` values stripped (they may contain
    secrets, e.g. an API key in a PATCH body).
  * Anything else is unexpected: logged with a full traceback + request id server-side,
    and returned to the client as a generic 500 carrying only the request id.
"""

from __future__ import annotations

import json
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from civex.domain.exceptions import (
    AlreadyExistsError,
    CivexError,
    ConfigError,
    DatabaseUnavailableError,
    NotFoundError,
    ValidationError,
)
from civex.observability import get_logger, request_id_var

log = get_logger("civex.server")

_REQUEST_ID_HEADER = "x-request-id"


class RequestContextMiddleware:
    """Pure-ASGI: assign/propagate a request id, bind it into the log context, and
    act as the final catch-all for unhandled exceptions.

    The catch-all lives here rather than in an ``exception_handler(Exception)``
    because FastAPI routes that to Starlette's outermost ServerErrorMiddleware —
    which runs *after* this middleware unbinds the request id, so the id would be
    lost. Catching here keeps the id (and header) attached to the 500 response.

    Body-transparent, so it doesn't interfere with SSE/streaming responses.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        import structlog

        headers = dict(scope.get("headers", []))
        incoming = headers.get(_REQUEST_ID_HEADER.encode())
        rid = incoming.decode("latin-1")[:64] if incoming else uuid.uuid4().hex

        token = request_id_var.set(rid)
        structlog.contextvars.bind_contextvars(request_id=rid)

        response_started = False

        async def send_with_header(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                message.setdefault("headers", [])
                message["headers"].append(
                    (_REQUEST_ID_HEADER.encode(), rid.encode("latin-1"))
                )
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        except Exception as exc:
            # Full traceback to logs/telemetry only — never to the client.
            log.exception(
                "unhandled_exception",
                path=scope.get("path"),
                method=scope.get("method"),
                error_type=type(exc).__name__,
            )
            if response_started:
                raise  # Too late to send a clean response — let the server abort.
            body = json.dumps(
                {"detail": "Internal server error", "request_id": rid}
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (_REQUEST_ID_HEADER.encode(), rid.encode("latin-1")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
            request_id_var.reset(token)


def _status_for(exc: CivexError) -> int:
    if isinstance(exc, NotFoundError):
        return 404
    if isinstance(exc, AlreadyExistsError):
        return 409
    if isinstance(exc, ValidationError):
        return 422
    if isinstance(exc, ConfigError):
        return 400
    if isinstance(exc, DatabaseUnavailableError):
        return 503
    return 500


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(CivexError)
    async def _civex_error(request: Request, exc: CivexError) -> JSONResponse:
        status = _status_for(exc)
        # Domain errors are expected control flow — log at info, not as an error.
        log.info(
            "domain_error",
            error_type=type(exc).__name__,
            status=status,
            path=request.url.path,
        )
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Strip `input` (may contain submitted secrets) and the unstable `url` field.
        clean = [
            {"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"detail": "Request validation failed", "errors": clean},
        )

    # NOTE: the catch-all for unhandled (non-CivexError) exceptions lives in
    # RequestContextMiddleware, not here — see that class's docstring for why.
