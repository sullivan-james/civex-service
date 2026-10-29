"""Running any plugin: one driver for every tier.

A plugin is something that speaks the civex-plugin-sdk wire protocol over a
`Connection` (a pair of frame streams). How that connection comes about is
a `Launcher`'s business (`civex.plugins.launchers`: a uv subprocess, a
Docker container, a thread in this process for the built-ins); everything
after it is here, the same for all of them:

- `describe(launcher)` and `run(launcher, ...)` send one request and read
  frames until the answer, answering the plugin's `rpc_call`s from the one
  table of host functions (`host_api`), checked against the capabilities
  found at discovery (never what the live plugin claims), writing its `log`
  frames to the run's log and its `progress` frames to the run's progress.
- A launcher whose connections answer many requests (`reusable`) is used
  through the pool of kept workers (`workers`); one that answers one request
  (a container) is started for each and stopped after.
- A wall-clock timeout stops the connection (`run_with_timeout`), for
  launchers whose plugins can be stopped (`bounded`).

Any failure (a top-level error frame, a malformed frame, a connection that
ends, a timeout) raises PluginExecutionError/PluginTimeoutError, so the
executor needs no tier-specific branch to abort a workflow on a failed step.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Hashable, Iterator
from pathlib import Path
from typing import Any

from civex_plugin_sdk.io import FrameReader, FrameWriter
from civex_plugin_sdk.io_convert import convert_outputs
from civex_plugin_sdk.plugin_base import IOSpec
from civex_plugin_sdk.protocol import (
    PROTOCOL_VERSION,
    DescribeRequest,
    DescribeResult,
    ErrorFrame,
    ErrorPayload,
    LogFrame,
    ProgressFrame,
    RpcCall,
    RpcResult,
    RunRequest,
    RunResult,
    parse_frame,
)

from civex.domain.dtos import ErrorEnvelope
from civex.domain.exceptions import PluginExecutionError, PluginTimeoutError
from civex.plugins import host_api, workers
from civex.plugins.base import PluginTier, StepResult, WorkflowContext

#: Where a plugin's own output goes: its print()s and its stderr, one log
#: line each, into whatever log the run is captured in.
plugin_output = logging.getLogger("civex.plugins.output")

#: The wire protocol versions this host speaks: everything up to the SDK's
#: own. A newer one only adds what a plugin *may* send (2: `progress`), so a
#: plugin built on an older SDK still runs.
PROTOCOL_MIN = 1


def runs_folder() -> Path:
    """Where run folders are made: `CIVEX_RUNS_DIR`, else civex's folder in
    the user's cache (on disk: files a plugin asks for can be large, and
    `/tmp` is often memory), never the project."""
    if override := os.environ.get("CIVEX_RUNS_DIR"):
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "civex" / "runs"


#: A run folder left by a process that died is removed by the next one made
#: after this long.
STALE_RUN_SECONDS = 24 * 3600


def new_run_dir() -> Path:
    """A new, empty run folder (`runs_folder`). Folders left there by a
    process that crashed are removed once a day old."""
    root = runs_folder()
    root.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - STALE_RUN_SECONDS
    for old in root.iterdir():
        try:
            if old.stat().st_mtime < cutoff:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass
    return Path(tempfile.mkdtemp(prefix="run-", dir=root))


class Connection(ABC):
    """One running plugin, as frames: write requests to `writer`, read its
    frames from `reader` (which ends when the plugin does)."""

    writer: FrameWriter
    reader: FrameReader
    #: Where values too large to inline are written (`encode_binary`); None
    #: inlines everything.
    scratch_dir: Path | None = None

    @abstractmethod
    def alive(self) -> bool: ...

    @abstractmethod
    def stop(self) -> None:
        """End it now (a timeout): afterwards `reader` ends."""

    @abstractmethod
    def close(self) -> None:
        """Ask it to finish (end of input), stopping it if it doesn't; and
        remove what it kept (its scratch folder)."""

    def death_message(self) -> str:
        """Why it ended without answering, in words for the run's error."""
        return "plugin exited without a response"

    @contextlib.contextmanager
    def relaying(self) -> Iterator[None]:
        """While a run lasts, whatever the plugin writes outside the protocol
        (a process's stderr) goes to the run's log. Nothing by default."""
        yield


class Launcher(ABC):
    """How a plugin is started. `key` says which running ones are the same
    plugin (a kept worker is only handed requests for its own key)."""

    tier: PluginTier
    #: Its connections answer any number of requests (`serve_loop`), so they
    #: are kept between runs; else one is started per request.
    reusable: bool = True
    #: A step's timeout stops it. A trusted built-in running in this process
    #: can't be stopped, and runs to the end as it always did.
    bounded: bool = True

    @property
    @abstractmethod
    def key(self) -> Hashable: ...

    @property
    def label(self) -> str:
        return str(self.key)

    @abstractmethod
    def start(self, mode: str, run_dir: Path | None = None) -> Connection:
        """A new connection. `mode` is the request it is started for
        ("describe" or "run") and `run_dir` the run's folder, for a launcher
        that starts one per request (a container mounts it); a reusable
        launcher ignores both."""

    def check(self, conn: Connection) -> None:
        """Asked of a newly started connection before it is handed any
        request: raise PluginExecutionError to refuse it. Nothing by default;
        a script with a declared header checks its code agrees with it."""


# -- one exchange ------------------------------------------------------------


class _HostRpcDispatcher:
    """Answers a run's rpc_call frames from the one table of host functions
    (`host_api`), allowing what the capabilities captured at discovery grant.
    A direct method (`get_file`, `update_record`, ...) and a `call_tool` tool
    are the same thing: a name and its args."""

    def __init__(
        self, ctx: WorkflowContext, capabilities: list[str], scratch_dir: Path | None
    ) -> None:
        self._ctx = ctx
        self._allowed = host_api.granted(capabilities)
        self._scratch_dir = scratch_dir

    def dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "call_tool":
            tool = params.get("tool")
            if not tool:
                raise PluginExecutionError("call_tool rpc_call missing 'tool' param")
            return host_api.dispatch(
                self._ctx,
                self._allowed,
                tool,
                params.get("args") or {},
                self._scratch_dir,
            )
        return host_api.dispatch(
            self._ctx, self._allowed, method, params, self._scratch_dir
        )

    def progress(self, done: float, total: float | None, message: str) -> None:
        """A plugin's `progress` frame: no capability needed (it reads and
        changes nothing), and a context that can't show it ignores it."""
        report = getattr(self._ctx, "progress", None)
        if callable(report):
            report(done, total, message)


def check_protocol_version(described: DescribeResult) -> DescribeResult:
    """Refuse a plugin whose SDK speaks a wire protocol this host doesn't,
    naming the side that needs upgrading -- instead of letting the two
    disagree mid-run with an opaque parse error."""
    theirs = described.protocol_version
    if PROTOCOL_MIN <= theirs <= PROTOCOL_VERSION:
        return described
    if theirs > PROTOCOL_VERSION:
        fix = "update civex (`civex update`)"
    else:
        fix = "upgrade the plugin's civex-plugin-sdk (or rebuild its image)"
    raise PluginExecutionError(
        f"plugin '{described.id}' speaks civex-plugin-sdk wire protocol v{theirs}, "
        f"but this civex speaks v{PROTOCOL_MIN} to v{PROTOCOL_VERSION}: {fix}",
        kind="protocol_mismatch",
    )


def _log_line(frame: LogFrame) -> None:
    """A line the plugin wrote, into the run's log (stderr as a warning)."""
    if frame.stream == "stderr":
        plugin_output.warning("│ %s", frame.text)
    else:
        plugin_output.info("│ %s", frame.text)


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


def _next_frame(conn: Connection) -> tuple[dict[str, Any], Any]:
    try:
        raw = next(conn.reader)
    except StopIteration:
        raise PluginExecutionError(conn.death_message(), kind="process_exit") from None
    return raw, parse_frame(raw)


def drive_describe(conn: Connection) -> DescribeResult:
    conn.writer.send(DescribeRequest().model_dump())
    while True:
        raw, frame = _next_frame(conn)
        if isinstance(frame, LogFrame):
            _log_line(frame)
            continue
        break
    if isinstance(frame, DescribeResult):
        return check_protocol_version(frame)
    if isinstance(frame, ErrorFrame):
        raise _error_from_frame(frame)
    raise PluginExecutionError(
        f"unexpected frame in response to describe: {raw!r}", kind="protocol_error"
    )


def _handle_rpc_call(
    writer: FrameWriter, frame: RpcCall, dispatcher: _HostRpcDispatcher
) -> None:
    try:
        result = dispatcher.dispatch(frame.method, frame.params)
    except Exception as e:
        # The host's own classification of a failed call, sent back in the
        # envelope the plugin uses for its own failures. A CivexError keeps
        # its kind (not_found, validation_error, duplicate_record, ...), which
        # is what lets a plugin tell a refused row from a broken run.
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


def drive_run(
    conn: Connection,
    inputs: dict[str, Any],
    config: dict[str, Any],
    dispatcher: _HostRpcDispatcher,
    run_dir: Path | None = None,
) -> dict[str, Any]:
    conn.writer.send(
        RunRequest(
            inputs=inputs,
            config=config,
            run_dir=None if run_dir is None else str(run_dir),
        ).model_dump()
    )
    while True:
        raw, frame = _next_frame(conn)
        if isinstance(frame, RunResult):
            return frame.outputs
        if isinstance(frame, ErrorFrame) and frame.call_id is None:
            raise _error_from_frame(frame)
        if isinstance(frame, RpcCall):
            _handle_rpc_call(conn.writer, frame, dispatcher)
            continue
        if isinstance(frame, LogFrame):
            _log_line(frame)
            continue
        if isinstance(frame, ProgressFrame):
            dispatcher.progress(frame.done, frame.total, frame.message)
            continue
        raise PluginExecutionError(
            f"unexpected frame during run: {raw!r}", kind="protocol_error"
        )


def run_with_timeout(
    conn: Connection,
    driver_fn: Callable[[], Any],
    timeout: float | None,
    *,
    label: str,
) -> Any:
    """Runs driver_fn() (the blocking frame exchange) on a daemon thread so
    the calling thread can enforce a real wall-clock deadline -- a blocking
    `next(reader)` has no timeout of its own. On timeout the connection is
    stopped (`Connection.stop`), its reader ends, and the thread exits on its
    own (never joined past a short grace period). `timeout` None waits for
    the answer however long it takes."""
    if timeout is None:
        return driver_fn()
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
        conn.stop()
        thread.join(timeout=5.0)
        raise PluginTimeoutError(f"plugin '{label}' exceeded {timeout}s timeout")
    if "exc" in box:
        raise box["exc"]
    return box["result"]


# -- with a launcher ----------------------------------------------------------

#: Failures that leave the plugin in an unknown state: it is stopped rather
#: than handed the next request. Anything else came back as the plugin's own
#: error frame, after which `serve_loop` is waiting for the next request.
_BROKEN_KINDS = frozenset({"process_exit", "protocol_error", "timeout"})


def _start(launcher: Launcher, mode: str) -> workers.Worker:
    conn = launcher.start(mode)
    try:
        launcher.check(conn)
    except BaseException:
        conn.close()
        raise
    return workers.Worker(key=launcher.key, conn=conn)


def _use(
    launcher: Launcher,
    mode: str,
    exchange: Callable[[Connection], Any],
    run_dir: Path | None = None,
) -> Any:
    """Run `exchange` against a connection from `launcher`: a kept worker
    (starting one if none is idle) given back afterwards, or stopped if the
    exchange broke it; or, for a launcher that isn't reusable, a new one,
    closed after. A kept worker that has gone away since (the pipe is closed
    when the request is written) is replaced once by a new one: nothing was
    asked of it, so nothing is repeated."""
    if not launcher.reusable:
        conn = launcher.start(mode, run_dir)
        try:
            return exchange(conn)
        finally:
            conn.close()
    key = launcher.key
    for attempt in (1, 2):
        worker = workers.POOL.checkout(key, lambda: _start(launcher, mode))
        healthy = False
        try:
            result = exchange(worker.conn)
            healthy = True
            return result
        except PluginExecutionError as e:
            healthy = e.kind not in _BROKEN_KINDS
            raise
        except OSError:
            if attempt == 1 and worker.runs > 0:
                continue
            raise
        finally:
            workers.POOL.checkin(worker, healthy)
    raise AssertionError("unreachable")


def describe(launcher: Launcher, timeout: float = 20.0) -> DescribeResult:
    """Ask the plugin to describe itself -- used by discovery to learn a
    plugin's id/name/category/capabilities/config_schema without running it.
    A reusable plugin is kept, so the first run after discovery finds it
    started."""
    return _use(
        launcher,
        "describe",
        lambda conn: run_with_timeout(
            conn,
            lambda: drive_describe(conn),
            timeout if launcher.bounded else None,
            label=launcher.label,
        ),
    )


def run(
    launcher: Launcher,
    inputs: dict[str, Any],
    config: dict[str, Any],
    ctx: WorkflowContext,
    capabilities: list[str],
    timeout: float,
    input_specs: list[IOSpec] | None = None,
) -> StepResult:
    """Run one step: send `run` and answer the plugin until it answers.
    `capabilities` is what discovery learned, never re-asked. Declared
    `table`/`bytes` inputs still in their in-process form (a DataFrame a
    caller passed) are put in wire form first (`input_specs`).

    Files and large values go by path, in the run's folder (`ctx.run_dir`,
    made by the executor for the whole run; a step run on its own gets one
    for the step). Every file the plugin's answer points at must be inside
    it (or its own working folder): the next step, maybe in this process,
    reads what they name."""
    own = getattr(ctx, "run_dir", None)
    run_dir = Path(own) if own else new_run_dir()
    try:
        wire_inputs = convert_outputs(input_specs, inputs, scratch_dir=run_dir)

        def exchange(conn: Connection) -> StepResult:
            dispatcher = _HostRpcDispatcher(ctx, capabilities, run_dir)
            with conn.relaying():
                outputs = run_with_timeout(
                    conn,
                    lambda: drive_run(conn, wire_inputs, config, dispatcher, run_dir),
                    timeout if launcher.bounded else None,
                    label=launcher.label,
                )
            host_api.inside_run(outputs, run_dir, conn.scratch_dir)
            return StepResult(outputs=outputs)

        return _use(launcher, "run", exchange, run_dir)
    finally:
        if not own:
            shutil.rmtree(run_dir, ignore_errors=True)
