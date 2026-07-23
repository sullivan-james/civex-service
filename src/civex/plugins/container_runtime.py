"""Host side of the container (Tier 2) plugin runtime: spawns
`docker run -i --rm --name <n> [--memory M] [--cpus C] <image> <mode>` and
drives the identical civex-plugin-sdk wire protocol over its stdin/stdout
that subprocess_runtime.py drives for Tier 1 (CIVEX-133: same describe/run
frames, same fd-dup stdout isolation on the plugin side -- see
plugin-templates/{r,java}/entrypoint.sh). Frame parsing, RPC dispatch, and
the wall-clock timeout watchdog are the exact same functions
(civex.plugins.subprocess_runtime), reused rather than reimplemented, so
the two tiers can never drift in how they interpret a frame.

The one thing that has to be tier-specific is how a stuck run gets killed:
Tier 1 kills the subprocess's own process group directly. Here, the local
`docker run` client is not the container itself -- killing it (or its
process group) does not reliably stop a container still running
server-side (SIGKILL in particular is never proxied through the Docker CLI
to the container it's attached to, only SIGTERM is, and only when attached
without a pseudo-tty). Termination instead goes through `docker kill`
against this run's own `--name`, which reaches the container directly
regardless of what happens to the local client process.

`describe_container`/`run_container` take an already-built `image`
reference (a tag or digest); building/caching that image from a plugin's
Dockerfile + source directory is CIVEX-148, not this module's job.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from civex_plugin_sdk.protocol import DescribeResult

from civex.domain.exceptions import ConfigError
from civex.plugins.base import StepResult, WorkflowContext
from civex.plugins.subprocess_runtime import (
    _drive_describe,
    _drive_run,
    _HostRpcDispatcher,
    _run_with_timeout,
)

# -- docker resolution ---------------------------------------------------


def find_docker_binary() -> str:
    """`docker` on PATH, or a ConfigError with an actionable message --
    required to run container-tier plugins. Whether the daemon itself is
    reachable is not checked here; a daemon that's down surfaces the same
    way any other docker-run failure does, through the container's non-zero
    exit / stderr, exactly like a broken `uv run` does for Tier 1."""
    found = shutil.which("docker")
    if found:
        return found
    raise ConfigError(
        "No 'docker' binary found. Install Docker "
        "(https://www.docker.com/products/docker-desktop) -- required to run "
        "container-tier plugins."
    )


def _build_command(
    docker_bin: str,
    image: str,
    mode: str,
    container_name: str,
    *,
    memory: str | None = None,
    cpus: float | None = None,
) -> list[str]:
    argv = [docker_bin, "run", "-i", "--rm", "--name", container_name]
    if memory is not None:
        argv += ["--memory", memory]
    if cpus is not None:
        argv += ["--cpus", str(cpus)]
    argv += [image, mode]
    return argv


# -- spawn / kill / cleanup ------------------------------------------------


def _spawn(argv: list[str]) -> subprocess.Popen:
    """No cwd/env sandboxing to do here (unlike subprocess_runtime._spawn) --
    the container itself is the isolation boundary; the local `docker run`
    client just proxies stdin/stdout/stderr."""
    return subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


def _kill_container(
    proc: subprocess.Popen, container_name: str, grace_seconds: float = 2.0
) -> None:
    """SIGTERM the container by name, wait a grace period, then SIGKILL it --
    same two-phase shape as subprocess_runtime._kill_process_group, but
    aimed at the container itself via `docker kill` rather than at the
    local client's process group (see module docstring for why)."""
    docker_bin = shutil.which("docker") or "docker"
    subprocess.run(
        [docker_bin, "kill", "--signal", "TERM", container_name],
        capture_output=True,
    )
    try:
        proc.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    subprocess.run(
        [docker_bin, "kill", "--signal", "KILL", container_name],
        capture_output=True,
    )
    try:
        proc.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass


def _ensure_terminated(
    proc: subprocess.Popen, container_name: str, grace_seconds: float = 2.0
) -> None:
    """Best-effort cleanup after a run that already finished normally: close
    stdin so a still-running container's read on stdin sees EOF and its
    entrypoint exits (and, with --rm, is removed) on its own, falling back
    to `docker kill` if it doesn't. In practice the container-tier shims
    (unlike civex_plugin_sdk.serve()'s loop) read exactly one frame and
    exit, so proc has almost always already exited by the time this runs --
    this is a safety net, not the primary termination path."""
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
    _kill_container(proc, container_name, grace_seconds=grace_seconds)


# -- public entrypoints ---------------------------------------------------


def _container_name() -> str:
    return f"civex-plugin-{uuid.uuid4().hex}"


def describe_container(image: str, timeout: float = 20.0) -> DescribeResult:
    """Spawn the image in "describe" mode and ask it to describe itself --
    used by discovery to learn a plugin's id/name/category/capabilities/
    config_schema without running it. Mirrors
    subprocess_runtime.describe_plugin()."""
    docker_bin = find_docker_binary()
    name = _container_name()
    proc: subprocess.Popen | None = None
    try:
        argv = _build_command(docker_bin, image, "describe", name)
        proc = _spawn(argv)
        return _run_with_timeout(
            proc,
            lambda: _drive_describe(proc),
            timeout,
            label=image,
            kill_fn=lambda: _kill_container(proc, name),
        )
    finally:
        if proc is not None:
            _ensure_terminated(proc, name)


def run_container(
    image: str,
    inputs: dict[str, Any],
    config: dict[str, Any],
    ctx: WorkflowContext,
    capabilities: list[str],
    timeout: float,
    *,
    memory: str | None = None,
    cpus: float | None = None,
) -> StepResult:
    """Spawn a fresh container and send `run` directly -- no redundant
    `describe` round-trip, exactly like subprocess_runtime.run_plugin().
    `capabilities` is what discovery already learned and cached on this
    plugin's PluginRegistration. `memory`/`cpus` are docker's own
    --memory/--cpus values (already resolved by the caller from a step's
    override or [plugins]'s global default -- same global-default +
    per-step-override mechanism as `timeout`, CIVEX-137); None means no
    limit is passed, i.e. docker's own default. Raises
    PluginExecutionError/PluginTimeoutError on any failure, exactly like a
    tier-BUILTIN or tier-SUBPROCESS plugin failing -- executor.py needs no
    tier-specific branch to abort the workflow on a failed step."""
    docker_bin = find_docker_binary()
    name = _container_name()
    scratch_dir = Path(tempfile.mkdtemp(prefix="civex-plugin-container-"))
    proc: subprocess.Popen | None = None
    try:
        argv = _build_command(docker_bin, image, "run", name, memory=memory, cpus=cpus)
        proc = _spawn(argv)
        dispatcher = _HostRpcDispatcher(ctx, capabilities, scratch_dir)
        outputs = _run_with_timeout(
            proc,
            lambda: _drive_run(proc, inputs, config, dispatcher),
            timeout,
            label=image,
            kill_fn=lambda: _kill_container(proc, name),
        )
        return StepResult(outputs=outputs)
    finally:
        if proc is not None:
            _ensure_terminated(proc, name)
        shutil.rmtree(scratch_dir, ignore_errors=True)
