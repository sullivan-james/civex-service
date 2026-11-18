"""Host side of the container (Tier 2) plugin runtime: spawns
`docker run -i --rm --name <n> [--memory M] [--cpus C] <image> <mode>` and
is the process side of `launchers.DockerLauncher` (CIVEX-133: the same
describe/run frames and fd-dup stdout isolation on the plugin side -- see
plugin-templates/{r,java}/entrypoint.sh). Frame parsing, RPC dispatch and
the timeout are `runtime`'s, the same for every tier.

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
from pathlib import Path
from typing import Any

from civex_plugin_sdk.protocol import DescribeResult

from civex.domain.exceptions import ConfigError
from civex.plugins import runtime
from civex.plugins.base import StepResult, WorkflowContext
from civex.processes import no_window_kwargs

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
    mounts: list[Path] | None = None,
) -> list[str]:
    argv = [docker_bin, "run", "-i", "--rm", "--name", container_name]
    for folder in mounts or []:
        argv += ["--volume", f"{folder}:{folder}"]
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
        **no_window_kwargs(),
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
        **no_window_kwargs(),
    )
    try:
        proc.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    subprocess.run(
        [docker_bin, "kill", "--signal", "KILL", container_name],
        capture_output=True,
        **no_window_kwargs(),
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


# -- entry points ----------------------------------------------------------------


def describe_container(image: str, timeout: float = 20.0) -> DescribeResult:
    """Run the image in "describe" mode and ask it to describe itself
    (`runtime.describe` with a `DockerLauncher`)."""
    from civex.plugins.launchers import DockerLauncher

    return runtime.describe(DockerLauncher(image), timeout)


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
    """Run one step in a fresh container (`runtime.run` with a
    `DockerLauncher`). `memory`/`cpus` are docker's own --memory/--cpus
    values; None passes no limit."""
    from civex.plugins.launchers import DockerLauncher

    return runtime.run(
        DockerLauncher(image, memory=memory, cpus=cpus),
        inputs,
        config,
        ctx,
        capabilities,
        timeout,
    )
