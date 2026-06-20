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


class VolumeFullError(CivexError):
    pass


class AllVolumesFull(CivexError):
    pass


class CoercionError(ValidationError):
    def __init__(self, field_name: str, dtype: str, raw: str, extra: str | None = None) -> None:
        self.field_name = field_name
        self.dtype = dtype
        self.raw = raw
        msg = f"Cannot coerce '{raw}' to {dtype} for field '{field_name}'"
        if extra:
            msg += f": {extra}"
        super().__init__(msg)
