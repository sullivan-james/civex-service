"""
Local-only security guard for the civex HTTP server.

civex serve is designed to run on loopback for a single trusted OS user (like
`git instaweb` or a Jupyter server). It has no authentication by design. This
middleware closes the two attack classes that still apply to a localhost server
opened in a browser:

  1. DNS rebinding — a malicious web page rebinds its hostname to 127.0.0.1 and
     talks to the API. Defence: the Host header the browser connected to must be
     a loopback name.
  2. CSRF — a cross-origin page issues state-changing requests to the local API.
     Defence: mutating requests carrying a non-loopback Origin are rejected. The
     Origin header is set by the browser and cannot be forged by page scripts.

Both checks are skipped when CIVEX_ALLOW_REMOTE=1 — the operator has explicitly
opted into remote exposure via `civex serve --allow-remote` and is responsible
for network-level protection (reverse proxy, firewall, VPN).
"""
from __future__ import annotations

import json
import os
from urllib.parse import urlparse

# "testserver" is Starlette's TestClient default Host — harmless to allow (not
# routable) and it keeps the test suite working without per-test overrides.
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "testserver"}
_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _hostname(value: str) -> str:
    """Extract the bare hostname from a Host header or an Origin URL."""
    value = value.strip()
    if not value:
        return ""
    if "://" in value:
        return (urlparse(value).hostname or "").lower()
    # Bare Host header: strip the port, handling IPv6 literals like [::1]:8000.
    if value.startswith("["):
        return value[1:].split("]", 1)[0].lower()
    if ":" in value:
        return value.rsplit(":", 1)[0].lower()
    return value.lower()


class LocalGuardMiddleware:
    """Pure-ASGI middleware — inspects request headers only, never touches the
    response body, so it is transparent to SSE/streaming responses."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or os.environ.get("CIVEX_ALLOW_REMOTE") == "1":
            await self.app(scope, receive, send)
            return

        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }

        # 1. DNS-rebinding guard.
        host = _hostname(headers.get("host", ""))
        if host and host not in _LOOPBACK_HOSTS:
            await self._deny(
                send,
                f"Refused request with non-local Host header '{headers.get('host')}'. "
                "civex serve is local-only; run with --allow-remote to expose it.",
            )
            return

        # 2. CSRF guard on state-changing requests.
        if scope.get("method", "GET") in _MUTATING_METHODS:
            origin = headers.get("origin")
            if origin and _hostname(origin) not in _LOOPBACK_HOSTS:
                await self._deny(send, "Cross-origin request blocked by civex local guard.")
                return

        await self.app(scope, receive, send)

    @staticmethod
    async def _deny(send, detail: str) -> None:
        body = json.dumps({"detail": detail}).encode()
        await send({
            "type": "http.response.start",
            "status": 403,
            "headers": [(b"content-type", b"application/json")],
        })
        await send({"type": "http.response.body", "body": body})
