"""Structured error envelope for the wire protocol.

Any exception raised inside a plugin's `invoke()`, or returned by the host
in response to an `rpc_call`, is represented as {"code", "message"} so both
sides can distinguish known failure classes from arbitrary crashes.
"""

from __future__ import annotations


class PluginError(Exception):
    code = "plugin_error"

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code

    def to_envelope(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class CapabilityDeniedError(PluginError):
    """Raised host-side when a plugin issues an rpc_call for a method it
    didn't declare in its `describe` capabilities list."""

    code = "capability_denied"

    def __init__(self, method: str) -> None:
        super().__init__(f"plugin is not declared to use capability '{method}'")
        self.method = method


class ConfigValidationError(PluginError):
    """Raised when incoming `run` config fails validation against the
    plugin's declared Config model."""

    code = "config_validation_error"


class RpcError(PluginError):
    """Raised plugin-side when the host responds to an rpc_call with an
    error frame."""

    code = "rpc_error"
