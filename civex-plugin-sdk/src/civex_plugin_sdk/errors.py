"""Structured error envelope for the wire protocol.

Any exception raised inside a plugin's `invoke()`, or returned by the host
in response to an `rpc_call`, is represented as
{"kind", "message", "retryable"} so both sides can distinguish known failure
classes from arbitrary crashes without parsing prose.

`kind` names the failure class. `retryable` answers the one question a
caller actually acts on: could running this again, unchanged, plausibly
succeed? It's False for everything here, because every failure class the SDK
defines is a fact about the plugin or its config -- a denied capability or a
malformed config fails identically forever. A plugin that hits a genuinely
transient failure (a rate limit, a flaky upstream) says so explicitly with
`PluginError(msg, retryable=True)`; nothing infers it.

Nothing consumes `retryable` automatically yet -- there is no retry policy,
and adding one is deliberately not this change. It is recorded on the job so
that policy has something truthful to read when it arrives, rather than
having to guess from message text after the fact.
"""

from __future__ import annotations


class PluginError(Exception):
    """Base class for every error this SDK raises. Carries the `{kind, message, retryable}` envelope this module documents above.

    Raise this directly (with a custom `kind`) from `invoke()` for a failure
    that doesn't fit one of the more specific subclasses below.
    """

    kind = "plugin_error"
    retryable = False

    def __init__(
        self,
        message: str,
        kind: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        """Build the error, optionally overriding the class-level `kind`/`retryable` defaults.

        Args:
            message: Human-readable failure description.
            kind: Overrides the class's default `kind`, if given.
            retryable: Overrides the class's default `retryable`, if given.
        """
        super().__init__(message)
        self.message = message
        if kind is not None:
            self.kind = kind
        if retryable is not None:
            self.retryable = retryable

    def to_envelope(self) -> dict[str, object]:
        """Return the `{kind, message, retryable}` dict this error sends over the wire."""
        return {
            "kind": self.kind,
            "message": self.message,
            "retryable": self.retryable,
        }


class CapabilityDeniedError(PluginError):
    """Raised host-side when a plugin issues an rpc_call for a method it didn't declare in its `describe` capabilities list."""

    kind = "capability_denied"

    def __init__(self, method: str) -> None:
        """Build the error for the specific `method` the plugin wasn't declared to use."""
        super().__init__(f"plugin is not declared to use capability '{method}'")
        self.method = method


class ConfigValidationError(PluginError):
    """Raised when incoming `run` config fails validation against the plugin's declared Config model."""

    kind = "config_validation_error"


class RpcError(PluginError):
    """Raised plugin-side when the host responds to an rpc_call with an error frame."""

    kind = "rpc_error"
