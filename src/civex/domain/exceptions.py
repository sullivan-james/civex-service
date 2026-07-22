from __future__ import annotations


class CivexError(Exception):
    """Base for all domain errors — catch this to handle any civex failure."""


class ConfigError(CivexError):
    """Raised when no civex project can be found or config is invalid."""


class NotFoundError(CivexError):
    pass


class AlreadyExistsError(CivexError):
    pass


class ValidationError(CivexError):
    pass


class VolumeUnavailableError(CivexError):
    pass


class DatabaseUnavailableError(CivexError):
    """Raised when a docker-managed project's database can't be reached/recovered."""


class VolumeFullError(CivexError):
    pass


class AllVolumesFull(CivexError):
    pass


class PluginExecutionError(CivexError):
    """Raised when a subprocess/container-tier plugin run fails: a non-zero
    exit, a malformed wire-protocol frame, or the plugin sending a top-level
    `error` frame back for its `run` request."""


class PluginTimeoutError(PluginExecutionError):
    """Raised when a plugin run exceeds its wall-clock timeout and the host
    had to kill the subprocess's process group."""


class CapabilityDeniedError(PluginExecutionError):
    """Raised host-side when a subprocess/container-tier plugin issues an
    rpc_call for a method/tool it didn't declare in its `describe`
    capabilities list."""

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
