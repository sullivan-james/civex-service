from __future__ import annotations


class CivexError(Exception):
    """Base for all domain errors — catch this to handle any civex failure.

    `kind`/`retryable` are the same two fields the out-of-process wire
    protocol carries (civex_plugin_sdk.errors), declared here too so a step
    that failed in-process and one that failed in a subprocess produce an
    identical envelope on the job — the whole point of CIVEX-143 being that
    nothing downstream should be able to tell which tier a failure came
    from.

    `retryable` means: could running this again, unchanged, plausibly
    succeed? It defaults to False, and stays False for anything that's a
    fact about the code or config rather than about the world — those fail
    identically forever, and retrying them is how you burn a queue.
    """

    kind = "civex_error"
    retryable = False


class ConfigError(CivexError):
    """Raised when no civex project can be found or config is invalid."""

    kind = "config_error"


class NotFoundError(CivexError):
    kind = "not_found"


class AlreadyExistsError(CivexError):
    kind = "already_exists"


class ValidationError(CivexError):
    kind = "validation_error"


class VolumeUnavailableError(CivexError):
    # A volume that's offline now may well be back on the next attempt.
    kind = "volume_unavailable"
    retryable = True


class DatabaseUnavailableError(CivexError):
    """Raised when a docker-managed project's database can't be reached/recovered."""

    kind = "database_unavailable"
    retryable = True


class VolumeFullError(CivexError):
    kind = "volume_full"


class AllVolumesFull(CivexError):
    kind = "all_volumes_full"


class PluginExecutionError(CivexError):
    """Raised when a subprocess/container-tier plugin run fails: a non-zero
    exit, a malformed wire-protocol frame, or the plugin sending a top-level
    `error` frame back for its `run` request.

    When the failure came from the plugin's own error frame, `kind` and
    `retryable` are whatever the plugin declared -- passed straight through
    rather than re-classified, since the plugin is the only thing that knows
    whether its failure was transient."""

    kind = "plugin_error"

    def __init__(
        self,
        message: str,
        kind: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        if kind is not None:
            self.kind = kind
        if retryable is not None:
            self.retryable = retryable


class PluginTimeoutError(PluginExecutionError):
    """Raised when a plugin run exceeds its wall-clock timeout and the host
    had to kill the subprocess's process group."""

    # The one plugin failure that is genuinely about the world rather than
    # the code: a run that blew its budget on a slow filesystem or a
    # contended machine can succeed on the next attempt.
    kind = "timeout"
    retryable = True


class CapabilityDeniedError(PluginExecutionError):
    """Raised host-side when a subprocess/container-tier plugin issues an
    rpc_call for a method/tool it didn't declare in its `describe`
    capabilities list."""

    kind = "capability_denied"

    def __init__(self, method: str) -> None:
        self.method = method
        super().__init__(f"plugin is not declared to use capability '{method}'")


class CoercionError(ValidationError):
    def __init__(
        self, field_name: str, dtype: str, raw: str, extra: str | None = None
    ) -> None:
        self.field_name = field_name
        self.dtype = dtype
        self.raw = raw
        msg = f"Cannot coerce '{raw}' to {dtype} for field '{field_name}'"
        if extra:
            msg += f": {extra}"
        super().__init__(msg)
