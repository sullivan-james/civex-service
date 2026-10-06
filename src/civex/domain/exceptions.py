from __future__ import annotations

from typing import Any


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


class FieldValueError(ValidationError):
    """A value its field doesn't allow. `path` names the field as a history
    entry does (`data.<field id>`), so whoever shows the refusal can show the
    field itself, to be fixed, rather than only a sentence about it."""

    def __init__(self, message: str, path: str) -> None:
        super().__init__(message)
        self.path = path


class ConflictMovedError(CivexError):
    """The value being put back has changed since the conflict was recorded, so
    what a person was shown is no longer what is there. `current` is what is
    there now: show it and ask again."""

    kind = "conflict_moved"

    def __init__(self, message: str, current: Any = None) -> None:
        super().__init__(message)
        self.current = current


class DuplicateRecordError(ValidationError):
    """A write would give two records the same values for a schema's unique
    key. A ValidationError, so every caller that skips or reports a bad row
    already handles it. `existing_id`/`existing_name` name the record that
    already holds the values and `fields` the key's field names."""

    kind = "duplicate_record"

    def __init__(
        self,
        message: str,
        existing_id: str | None = None,
        fields: list[str] | None = None,
        existing_name: str | None = None,
    ) -> None:
        super().__init__(message)
        self.existing_id = existing_id
        self.existing_name = existing_name
        self.fields = fields or []


class WorkflowValidationError(ValidationError):
    """A workflow's steps violate their plugins' declared contracts.

    Carries `errors` -- a list of `{"step": str | None, "message": str}` --
    alongside the flattened message every `ValidationError` has, so a caller
    that wants to point a user at the specific offending step (e.g. the
    workflows API, CIVEX-109) doesn't have to parse one back out of a
    newline-joined string.
    """

    def __init__(self, errors: list[dict[str, Any]]) -> None:
        self.errors = errors
        super().__init__("\n".join(e["message"] for e in errors))


class VolumeUnavailableError(CivexError):
    # A volume that's offline now may well be back on the next attempt.
    kind = "volume_unavailable"
    retryable = True


class DatabaseUnavailableError(CivexError):
    """Raised when a docker-managed project's database can't be reached/recovered."""

    kind = "database_unavailable"
    retryable = True


class DatabaseTooNewError(CivexError):
    """The project's database was migrated by a newer civex than this one, so
    it holds a schema revision this civex has never heard of.

    Carries the facts a person needs (which database, which revisions, which
    civex) as fields, so the CLI can lay them out and the API can return them
    without either parsing the message. `str(error)` is the one-paragraph
    summary for logs and plain output."""

    kind = "database_too_new"

    def __init__(
        self,
        message: str,
        *,
        database: str = "",
        revisions: list[str] | None = None,
        civex_version: str = "",
        known_head: str | None = None,
    ) -> None:
        super().__init__(message)
        self.database = database
        self.revisions = revisions or []
        self.civex_version = civex_version
        self.known_head = known_head


class JobCancelled(CivexError):
    """A workflow run was stopped by a person (or by Stop automation) while it
    was running. Raised between steps; the steps that already ran are attached
    as `.step_executions`, as for a failure."""


class GCAlreadyRunningError(CivexError):
    """Raised when a garbage-collection pass is requested while another is
    already in progress. Two concurrent sweeps over the same object store
    would race on delete()'s exists-then-unlink check and could disagree
    about what's collectible if a reference is written mid-sweep; safe to
    just retry once the other run finishes."""

    kind = "gc_already_running"
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


class PluginContractError(CivexError):
    """Raised when a step's outputs violate the one contract every tier is
    held to: they must be JSON-serializable, so a workflow behaves the same
    regardless of which tier a step happens to run on.

    Declared `table`/`bytes` IOSpec values are converted for the author
    automatically (civex_plugin_sdk.io_convert, wired into both
    registry._registration_for_tier0 and civex_plugin_sdk.serve._handle_run),
    so this only fires for a BUILTIN plugin returning some *other*
    non-serializable value -- caught at the step that produced it rather than
    later and further away, when a downstream subprocess step tried to send it
    in a RunRequest or the job record was written.
    """

    kind = "plugin_contract_error"


class ContainerBuildError(CivexError):
    """Raised when `docker build` fails for a Tier 2 (container) plugin's
    Dockerfile + source directory (CIVEX-148)."""

    kind = "container_build_error"


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
