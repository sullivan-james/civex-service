"""Host side of the subprocess (Tier 1) plugin runtime: spawns
`uv run --no-project <plugin>.py`, drives the civex-plugin-sdk wire protocol
over its stdin/stdout, and dispatches rpc_call frames against the real
(trusted) WorkflowContext.

Capability enforcement: the allowlist checked against an incoming rpc_call
must be the one captured at *discovery* time (this plugin's `describe`
response, cached on its PluginRegistration when it was first found), never
anything the run's own live subprocess claims about itself -- a plugin that
lied in `describe` but tried to use an undeclared capability at run time is
exactly the thing this is meant to catch, so `run_plugin()` takes
`capabilities` as a parameter rather than re-describing.

Any failure (a top-level error frame, a malformed frame, a dead process, a
timeout) raises PluginExecutionError/PluginTimeoutError -- the same shape as
an exception raised from a tier-BUILTIN plugin's invoke() -- so
workflows/executor.py needs no tier-specific branch to abort a workflow on a
failed step.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from civex_plugin_sdk.io import FrameReader, FrameWriter
from civex_plugin_sdk.protocol import (
    DescribeRequest,
    DescribeResult,
    ErrorFrame,
    ErrorPayload,
    LogFrame,
    RpcCall,
    RpcResult,
    RunRequest,
    RunResult,
    decode_binary,
    encode_binary,
    parse_frame,
)

from civex.domain.dtos import ErrorEnvelope
from civex.domain.exceptions import (
    CapabilityDeniedError,
    ConfigError,
    PluginExecutionError,
    PluginTimeoutError,
)
from civex.plugins.base import StepResult, WorkflowContext

# -- uv / SDK resolution ------------------------------------------------------


def find_uv_binary() -> str:
    """CIVEX_UV_BIN env var -> a vendored binary next to a frozen desktop
    bundle (see desktop/tray.py's own `sys.frozen` check -- there's no `uv`
    on PATH, or even a Python interpreter to pip-install into, inside a
    frozen app) -> `uv` on PATH. Raises ConfigError with an actionable
    message if none is found."""
    env_override = os.environ.get("CIVEX_UV_BIN")
    if env_override:
        return env_override
    if getattr(sys, "frozen", False):
        vendored = Path(sys.executable).parent / "civex-vendor" / _uv_binary_name()
        if vendored.is_file():
            return str(vendored)
    found = shutil.which("uv")
    if found:
        return found
    raise ConfigError(
        "No 'uv' binary found. Install uv (https://docs.astral.sh/uv/) or set "
        "CIVEX_UV_BIN to its path -- required to run custom (subprocess-tier) "
        "plugins."
    )


def _uv_binary_name() -> str:
    return "uv.exe" if sys.platform == "win32" else "uv"


def _find_sdk_source() -> Path | None:
    """Walk up from this file looking for a sibling civex-plugin-sdk/ source
    directory -- true in this repo's own uv workspace checkout, absent in a
    real install."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "civex-plugin-sdk"
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return None


@lru_cache(maxsize=1)
def _sdk_find_links_dir() -> Path | None:
    """civex-plugin-sdk isn't published to PyPI yet, so `uv run --no-project`
    can't resolve a script's plain `dependencies = ["civex-plugin-sdk"]` PEP
    723 header on its own -- `--with-editable`/`--with` only *add* a
    requirement, they don't substitute a source for one the script's own
    metadata already declares by name. The fix: build a real wheel from the
    local source (once per process, memoized -- `uv build` takes ~1s) into a
    scratch dir and pass that as `--find-links`, so uv's resolver finds
    `civex-plugin-sdk` locally under the exact name the script asks for.

    Returns None when no local SDK source is found (a real install, SDK
    published to PyPI) -- resolution then proceeds against a real index with
    no override at all. This whole function is a pre-launch/dev-only hook,
    not a permanent mechanism."""
    sdk_source = _find_sdk_source()
    if sdk_source is None:
        return None
    wheel_dir = Path(tempfile.mkdtemp(prefix="civex-plugin-sdk-wheel-"))
    subprocess.run(
        [find_uv_binary(), "build", "--wheel", "-o", str(wheel_dir), str(sdk_source)],
        check=True,
        capture_output=True,
        text=True,
    )
    return wheel_dir


def _build_command(uv_bin: str, plugin_path: Path) -> list[str]:
    argv = [uv_bin, "run", "--no-project"]
    find_links = _sdk_find_links_dir()
    if find_links is not None:
        argv += ["--find-links", str(find_links)]
    argv.append(str(plugin_path))
    return argv


# -- sandboxed spawn (CIVEX-139) ----------------------------------------------


def _sandboxed_env() -> dict[str, str]:
    """Minimal environment for a plugin subprocess: PATH/HOME plus whatever a
    few uv/Python variables it needs, deliberately excluding the rest of
    civex-service's own process environment (DB URL, AI API keys, ...) so a
    plugin can't read ambient secrets it was never granted a capability
    for -- the same "no ambient access" principle as the sandboxed cwd
    below, just applied to env instead of the filesystem."""
    allowed = ("PATH", "HOME", "UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR", "TMPDIR")
    env = {k: os.environ[k] for k in allowed if k in os.environ}
    if sys.platform == "win32":
        for k in ("SYSTEMROOT", "TEMP", "TMP", "USERPROFILE"):
            if k in os.environ:
                env[k] = os.environ[k]
    return env


def _spawn(argv: list[str], scratch_dir: Path) -> subprocess.Popen:
    """cwd is a throwaway scratch dir, never `_civex/` or the project root --
    a plugin gets no ambient filesystem path into real project data, only
    what it fetches over the RPC capability calls it declared. `start_new_
    session=True` gives the process (and anything uv itself spawns under it)
    its own process group, so a runaway/forked plugin can be killed as a
    unit (CIVEX-138) rather than leaving orphans behind."""
    return subprocess.Popen(
        argv,
        cwd=str(scratch_dir),
        env=_sandboxed_env(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        start_new_session=True,
    )


def _kill_process_group(proc: subprocess.Popen, grace_seconds: float = 2.0) -> None:
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass


def _ensure_terminated(proc: subprocess.Popen, grace_seconds: float = 2.0) -> None:
    """Best-effort cleanup after a run that already finished normally: close
    stdin so the plugin's serve_loop sees EOF and exits on its own, falling
    back to a process-group kill if it doesn't."""
    if proc.poll() is not None:
        return
    try:
        if proc.stdin:
            proc.stdin.close()
    except Exception:
        pass
    try:
        proc.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    _kill_process_group(proc, grace_seconds=grace_seconds)


def _dead_process_message(proc: subprocess.Popen) -> str:
    stderr = ""
    if proc.stderr is not None:
        try:
            stderr = proc.stderr.read()
        except Exception:
            stderr = ""
    detail = f": {stderr.strip()}" if stderr.strip() else ""
    return f"plugin process exited without a response (exit code {proc.poll()}){detail}"


# -- wall-clock timeout (CIVEX-138) -------------------------------------------


def _run_with_timeout(
    proc: subprocess.Popen,
    driver_fn: Callable[[], Any],
    timeout: float,
    *,
    label: str,
    kill_fn: Callable[[], None] | None = None,
) -> Any:
    """Runs driver_fn() (the blocking frame-exchange loop) on a daemon thread
    so the calling thread can enforce a real wall-clock deadline with
    Event.wait() -- a blocking `next(reader)` read has no timeout parameter
    of its own. On timeout, calls kill_fn() (default: kill proc's whole
    process group -- right for a Tier 1 subprocess; container_runtime.py
    passes a `docker kill` closure instead, since killing the local `docker
    run` client doesn't reliably stop the container itself). The daemon
    thread then unblocks on EOF and exits on its own (never joined past a
    short grace period, so a stuck kill can't hang the caller)."""
    box: dict[str, Any] = {}
    done = threading.Event()

    def worker() -> None:
        try:
            box["result"] = driver_fn()
        except BaseException as e:  # noqa: BLE001 -- re-raised on the caller's thread
            box["exc"] = e
        finally:
            done.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    if not done.wait(timeout):
        (kill_fn or (lambda: _kill_process_group(proc)))()
        thread.join(timeout=5.0)
        raise PluginTimeoutError(f"plugin '{label}' exceeded {timeout}s timeout")
    if "exc" in box:
        raise box["exc"]
    return box["result"]


# -- host-side RPC dispatch ----------------------------------------------------


class _HostRpcDispatcher:
    """Maps incoming rpc_call frames to the real WorkflowContext, checking
    each call against the capabilities captured at discovery time before
    doing anything (see module docstring)."""

    def __init__(
        self, ctx: WorkflowContext, capabilities: list[str], scratch_dir: Path
    ) -> None:
        self._ctx = ctx
        self._capabilities = set(capabilities)
        self._scratch_dir = scratch_dir

    def dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "call_tool":
            tool = params.get("tool")
            if not tool:
                raise PluginExecutionError("call_tool rpc_call missing 'tool' param")
            self._check(tool)
            handler = getattr(self, f"_tool_{tool}", None)
            if handler is None:
                raise PluginExecutionError(f"unknown tool '{tool}'")
            return handler(params.get("args") or {})

        self._check(method)
        handler = getattr(self, f"_rpc_{method}", None)
        if handler is None:
            raise PluginExecutionError(f"unknown rpc method '{method}'")
        return handler(params)

    def _check(self, name: str) -> None:
        if name not in self._capabilities:
            raise CapabilityDeniedError(name)

    # -- direct RpcMethod handlers ---------------------------------------

    def _rpc_get_file(self, params: dict[str, Any]) -> dict[str, Any]:
        data = self._ctx.get_file(params["sha256"])
        return encode_binary(data, self._scratch_dir)

    def _rpc_update_record(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._ctx.update_record(params["record_id"], params["data"]).to_dict()

    def _rpc_create_record(self, params: dict[str, Any]) -> dict[str, Any]:
        record = self._ctx.create_record(
            params["dataset_name"],
            params["schema_name"],
            params["data"],
            context_record_id=params.get("context_record_id"),
        )
        return record.to_dict()

    def _rpc_commit(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ctx.commit()
        return {}

    # -- call_tool-routed handlers ----------------------------------------

    def _tool_get_context_record(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"record": self._ctx.get_context_record().to_dict()}

    def _tool_get_context_dataset(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"dataset": self._ctx.get_context_dataset().to_dict()}

    def _tool_store_file(self, args: dict[str, Any]) -> dict[str, Any]:
        data = decode_binary(args["data"])
        return {"file": self._ctx.store_file(data, args["filename"]).to_dict()}

    def _tool_get_record(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"record": self._ctx.get_record(args["record_id"]).to_dict()}

    def _tool_find_records(self, args: dict[str, Any]) -> dict[str, Any]:
        records = self._ctx.find_records(
            args["dataset_name"],
            schema_name=args.get("schema_name"),
            parent_record_id=args.get("parent_record_id"),
            filters=args.get("filters"),
            search=args.get("search"),
            limit=args.get("limit", 50),
            offset=args.get("offset", 0),
        )
        return {"records": [r.to_dict() for r in records]}

    def _tool_delete_record(self, args: dict[str, Any]) -> dict[str, Any]:
        self._ctx.delete_record(args["record_id"])
        return {}

    def _tool_get_schema(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"schema": self._ctx.get_schema(args["name"]).to_dict()}

    def _tool_list_schemas(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"schemas": [s.to_dict() for s in self._ctx.list_schemas()]}

    def _tool_get_collection(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"collection": self._ctx.get_collection(args["name"]).to_dict()}

    def _tool_list_collections(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"collections": [c.to_dict() for c in self._ctx.list_collections()]}


# -- frame-exchange drivers ----------------------------------------------------


def _drive_describe(proc: subprocess.Popen) -> DescribeResult:
    writer = FrameWriter.for_stream(proc.stdin)
    reader = FrameReader.for_stream(proc.stdout)
    writer.send(DescribeRequest().model_dump())
    try:
        raw = next(reader)
    except StopIteration:
        raise PluginExecutionError(
            _dead_process_message(proc), kind="process_exit"
        ) from None
    frame = parse_frame(raw)
    if isinstance(frame, DescribeResult):
        return frame
    if isinstance(frame, ErrorFrame):
        raise _error_from_frame(frame)
    raise PluginExecutionError(
        f"unexpected frame in response to describe: {raw!r}", kind="protocol_error"
    )


def _error_from_frame(frame: ErrorFrame) -> PluginExecutionError:
    """Rebuild a plugin's own error envelope host-side, preserving the kind
    and retryable flag it declared rather than re-deriving them. The plugin
    is the only thing that knows whether its failure was transient, so a
    plugin that says `retryable=True` is believed."""
    return PluginExecutionError(
        frame.error.message,
        kind=frame.error.kind,
        retryable=frame.error.retryable,
    )


def _handle_rpc_call(
    writer: FrameWriter, frame: RpcCall, dispatcher: _HostRpcDispatcher
) -> None:
    try:
        result = dispatcher.dispatch(frame.method, frame.params)
    except Exception as e:
        # The host's own classification of a failed capability call, sent
        # back in the same envelope shape the plugin uses for its own
        # failures. A CivexError raised by the service layer (NotFoundError
        # from get_record, ValidationError from create_record, ...) keeps its
        # own kind rather than being flattened to "rpc_error" -- that
        # distinction is exactly what makes a job error readable later.
        envelope = ErrorEnvelope.from_exception(e)
        writer.send(
            ErrorFrame(
                call_id=frame.call_id,
                error=ErrorPayload(
                    kind=envelope.kind,
                    message=envelope.message,
                    retryable=envelope.retryable,
                ),
            ).model_dump()
        )
        return
    writer.send(RpcResult(call_id=frame.call_id, result=result).model_dump())


def _drive_run(
    proc: subprocess.Popen,
    inputs: dict[str, Any],
    config: dict[str, Any],
    dispatcher: _HostRpcDispatcher,
) -> dict[str, Any]:
    writer = FrameWriter.for_stream(proc.stdin)
    reader = FrameReader.for_stream(proc.stdout)
    writer.send(RunRequest(inputs=inputs, config=config).model_dump())
    while True:
        try:
            raw = next(reader)
        except StopIteration:
            raise PluginExecutionError(
                _dead_process_message(proc), kind="process_exit"
            ) from None
        frame = parse_frame(raw)
        if isinstance(frame, RunResult):
            return frame.outputs
        if isinstance(frame, ErrorFrame) and frame.call_id is None:
            raise _error_from_frame(frame)
        if isinstance(frame, RpcCall):
            _handle_rpc_call(writer, frame, dispatcher)
            continue
        if isinstance(frame, LogFrame):
            continue
        raise PluginExecutionError(
            f"unexpected frame during run: {raw!r}", kind="protocol_error"
        )


# -- public entrypoints ---------------------------------------------------------


def describe_plugin(plugin_path: Path, timeout: float = 20.0) -> DescribeResult:
    """Spawn the plugin and ask it to describe itself -- used by discovery to
    learn a plugin's id/name/category/capabilities/config_schema without
    running it."""
    scratch_dir = Path(tempfile.mkdtemp(prefix="civex-plugin-describe-"))
    proc: subprocess.Popen | None = None
    try:
        argv = _build_command(find_uv_binary(), plugin_path)
        proc = _spawn(argv, scratch_dir)
        return _run_with_timeout(
            proc, lambda: _drive_describe(proc), timeout, label=str(plugin_path)
        )
    finally:
        if proc is not None:
            _ensure_terminated(proc)
        shutil.rmtree(scratch_dir, ignore_errors=True)


def run_plugin(
    plugin_path: Path,
    inputs: dict[str, Any],
    config: dict[str, Any],
    ctx: WorkflowContext,
    capabilities: list[str],
    timeout: float,
) -> StepResult:
    """Spawn a fresh subprocess and send `run` directly -- no redundant
    `describe` round-trip; `capabilities` is what discovery already learned
    and cached on this plugin's PluginRegistration. Raises
    PluginExecutionError/PluginTimeoutError on any failure, exactly like a
    tier-BUILTIN plugin raising from invoke() -- executor.py needs no
    tier-specific branch to abort the workflow on a failed step."""
    scratch_dir = Path(tempfile.mkdtemp(prefix="civex-plugin-"))
    proc: subprocess.Popen | None = None
    try:
        argv = _build_command(find_uv_binary(), plugin_path)
        proc = _spawn(argv, scratch_dir)
        dispatcher = _HostRpcDispatcher(ctx, capabilities, scratch_dir)
        outputs = _run_with_timeout(
            proc,
            lambda: _drive_run(proc, inputs, config, dispatcher),
            timeout,
            label=str(plugin_path),
        )
        return StepResult(outputs=outputs)
    finally:
        if proc is not None:
            _ensure_terminated(proc)
        shutil.rmtree(scratch_dir, ignore_errors=True)
