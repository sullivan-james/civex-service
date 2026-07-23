"""Host side of the Tier 2 (container) plugin runtime (CIVEX-147). Frame
parsing/RPC dispatch/the timeout watchdog are the exact same functions Tier
1 uses (civex.plugins.subprocess_runtime), imported and reused rather than
reimplemented -- see test_subprocess_runtime.py for coverage of that shared
machinery. What's new here -- command construction (`docker run -i --rm
--name ... [--memory][--cpus] <image> <mode>`) and the docker-kill
termination path -- is what these tests actually cover, using a plain
`sys.executable` child in place of a real docker container (this sandbox
has no docker daemon, matching docker_manager.py's own lack of test
coverage for the same reason) to prove the full describe/run path still
works end-to-end once `_spawn` is substituted.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from civex.domain.exceptions import ConfigError, PluginTimeoutError
from civex.plugins import container_runtime as rt

# -- command construction ------------------------------------------------


def test_build_command_without_limits() -> None:
    argv = rt._build_command("docker", "my-image:abc123", "run", "civex-plugin-x")
    assert argv == [
        "docker",
        "run",
        "-i",
        "--rm",
        "--name",
        "civex-plugin-x",
        "my-image:abc123",
        "run",
    ]


def test_build_command_with_memory_and_cpus() -> None:
    argv = rt._build_command(
        "docker",
        "my-image:abc123",
        "describe",
        "civex-plugin-x",
        memory="512m",
        cpus=1.5,
    )
    assert argv == [
        "docker",
        "run",
        "-i",
        "--rm",
        "--name",
        "civex-plugin-x",
        "--memory",
        "512m",
        "--cpus",
        "1.5",
        "my-image:abc123",
        "describe",
    ]


def test_build_command_with_memory_only() -> None:
    argv = rt._build_command(
        "docker", "img", "run", "civex-plugin-x", memory="1g", cpus=None
    )
    assert argv == [
        "docker",
        "run",
        "-i",
        "--rm",
        "--name",
        "civex-plugin-x",
        "--memory",
        "1g",
        "img",
        "run",
    ]


def test_build_command_with_cpus_only() -> None:
    argv = rt._build_command(
        "docker", "img", "run", "civex-plugin-x", memory=None, cpus=2.0
    )
    assert argv == [
        "docker",
        "run",
        "-i",
        "--rm",
        "--name",
        "civex-plugin-x",
        "--cpus",
        "2.0",
        "img",
        "run",
    ]


# -- docker binary resolution ----------------------------------------------


def test_find_docker_binary_returns_path_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rt.shutil, "which", lambda name: "/usr/bin/docker")
    assert rt.find_docker_binary() == "/usr/bin/docker"


def test_find_docker_binary_raises_when_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rt.shutil, "which", lambda name: None)
    with pytest.raises(ConfigError, match="No 'docker' binary found"):
        rt.find_docker_binary()


# -- kill / cleanup ----------------------------------------------------------


class _FakeStdin:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeProc:
    """Stands in for subprocess.Popen for _kill_container/_ensure_terminated
    tests that don't need a real process -- just wait()/poll()/stdin.
    `wait()` always succeeds (marks the proc dead) unless a test overrides
    it to raise subprocess.TimeoutExpired instead."""

    def __init__(self, dead: bool = False) -> None:
        self.stdin = _FakeStdin()
        self._dead = dead

    def poll(self):
        return 0 if self._dead else None

    def wait(self, timeout=None):
        self._dead = True
        return 0


def test_kill_container_sends_term_then_kill_on_grace_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(rt.subprocess, "run", fake_run)
    monkeypatch.setattr(rt.shutil, "which", lambda name: "/usr/bin/docker")

    proc = _FakeProc()  # wait() overridden below to never succeed

    def always_timeout(timeout=None):
        raise subprocess.TimeoutExpired(cmd="docker", timeout=timeout)

    proc.wait = always_timeout  # type: ignore[assignment]

    rt._kill_container(proc, "civex-plugin-x", grace_seconds=0.01)

    assert calls == [
        ["/usr/bin/docker", "kill", "--signal", "TERM", "civex-plugin-x"],
        ["/usr/bin/docker", "kill", "--signal", "KILL", "civex-plugin-x"],
    ]


def test_kill_container_stops_after_term_if_proc_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        rt.subprocess,
        "run",
        lambda argv, **kwargs: (
            calls.append(argv) or subprocess.CompletedProcess(argv, 0)
        ),
    )
    monkeypatch.setattr(rt.shutil, "which", lambda name: "/usr/bin/docker")

    proc = (
        _FakeProc()
    )  # wait() succeeds immediately -> exits on the first wait() after TERM

    rt._kill_container(proc, "civex-plugin-x", grace_seconds=0.01)

    assert calls == [["/usr/bin/docker", "kill", "--signal", "TERM", "civex-plugin-x"]]


def test_ensure_terminated_noop_when_already_dead() -> None:
    proc = _FakeProc(dead=True)
    rt._ensure_terminated(proc, "civex-plugin-x")
    assert proc.stdin.closed is False


def test_ensure_terminated_closes_stdin_and_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _FakeProc()  # wait() succeeds -> exits cleanly after stdin close
    killed = []
    monkeypatch.setattr(rt, "_kill_container", lambda *a, **k: killed.append(True))

    rt._ensure_terminated(proc, "civex-plugin-x", grace_seconds=0.01)

    assert proc.stdin.closed is True
    assert killed == []  # exited cleanly after stdin close, no kill needed


def test_ensure_terminated_falls_back_to_kill_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _FakeProc()

    def always_timeout(timeout=None):
        raise subprocess.TimeoutExpired(cmd="docker", timeout=timeout)

    proc.wait = always_timeout  # type: ignore[assignment]
    killed = []
    monkeypatch.setattr(rt, "_kill_container", lambda p, name, **k: killed.append(name))

    rt._ensure_terminated(proc, "civex-plugin-x", grace_seconds=0.01)

    assert killed == ["civex-plugin-x"]


# -- full describe/run path, docker substituted with a plain python child ---

_TEST_PLUGIN_SOURCE = """\
from pydantic import BaseModel
from civex_plugin_sdk import Ctx, Plugin, serve

class TestPlugin(Plugin):
    id = "test.container_plugin"
    name = "Test Container Plugin"
    capabilities = ["commit"]

    class Config(BaseModel):
        pass

    def invoke(self, inputs, config, ctx: Ctx) -> dict:
        if inputs.get("call_commit"):
            ctx.commit()
        return {"saw": inputs.get("value")}

if __name__ == "__main__":
    serve(TestPlugin)
"""

_HANG_PLUGIN_SOURCE = """\
import time
from pydantic import BaseModel
from civex_plugin_sdk import Ctx, Plugin, serve

class HangPlugin(Plugin):
    id = "test.container_hang"
    name = "Hang"
    capabilities = []

    class Config(BaseModel):
        pass

    def invoke(self, inputs, config, ctx: Ctx) -> dict:
        time.sleep(30)
        return {}

if __name__ == "__main__":
    serve(HangPlugin)
"""


class _FakeWorkflowContext:
    def __init__(self) -> None:
        self.committed = False

    def commit(self) -> None:
        self.committed = True


def _patch_spawn_to_plain_python(
    monkeypatch: pytest.MonkeyPatch, script_path: Path
) -> None:
    """describe_container/run_container build a `docker run ...` argv and
    hand it to _spawn(); substitute a plain python child for the trailing
    `<image> <mode>` positional args so the full call path (command
    construction through frame driving through kill-on-timeout) runs
    without a real docker daemon, exactly like
    test_subprocess_runtime.py's `_spawn_plain` helper does for `uv run`."""
    monkeypatch.setattr(rt, "find_docker_binary", lambda: "docker")

    real_spawn = rt._spawn

    def fake_spawn(argv: list[str]) -> subprocess.Popen:
        # argv is [docker, run, -i, --rm, --name, N, (--memory M) (--cpus C), image, mode]
        mode = argv[-1]
        return real_spawn([sys.executable, str(script_path), mode])

    monkeypatch.setattr(rt, "_spawn", fake_spawn)


def test_describe_container_returns_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "plugin.py"
    script.write_text(_TEST_PLUGIN_SOURCE)
    _patch_spawn_to_plain_python(monkeypatch, script)

    result = rt.describe_container("fake-image:latest")

    assert result.id == "test.container_plugin"
    assert result.capabilities == ["commit"]


def test_run_container_dispatches_and_respects_memory_cpus_args(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "plugin.py"
    script.write_text(_TEST_PLUGIN_SOURCE)

    monkeypatch.setattr(rt, "find_docker_binary", lambda: "docker")
    seen_argv: list[list[str]] = []
    real_spawn = rt._spawn

    def fake_spawn(argv: list[str]) -> subprocess.Popen:
        seen_argv.append(argv)
        mode = argv[-1]
        return real_spawn([sys.executable, str(script), mode])

    monkeypatch.setattr(rt, "_spawn", fake_spawn)

    ctx = _FakeWorkflowContext()
    result = rt.run_container(
        "fake-image:latest",
        {"call_commit": True, "value": "x"},
        {},
        ctx,
        ["commit"],
        timeout=20.0,
        memory="256m",
        cpus=0.5,
    )

    assert result.outputs == {"saw": "x"}
    assert ctx.committed is True
    assert "--memory" in seen_argv[0]
    assert seen_argv[0][seen_argv[0].index("--memory") + 1] == "256m"
    assert "--cpus" in seen_argv[0]
    assert seen_argv[0][seen_argv[0].index("--cpus") + 1] == "0.5"
    assert seen_argv[0][:5] == ["docker", "run", "-i", "--rm", "--name"]


def test_run_container_timeout_kills_via_docker_kill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "hang.py"
    script.write_text(_HANG_PLUGIN_SOURCE)
    _patch_spawn_to_plain_python(monkeypatch, script)

    killed: list[str] = []

    def spy_kill(proc, name, **kwargs):
        # Records that the docker-kill path (not a process-group kill) was
        # used, but still actually ends the real child -- a no-op mock would
        # leave the 30s sleep running past the end of the test.
        killed.append(name)
        proc.kill()

    monkeypatch.setattr(rt, "_kill_container", spy_kill)

    ctx = _FakeWorkflowContext()
    start = time.monotonic()
    with pytest.raises(PluginTimeoutError):
        rt.run_container("fake-image:latest", {}, {}, ctx, [], timeout=1.0)
    elapsed = time.monotonic() - start

    assert elapsed < 10.0  # killed promptly, not left to run its full 30s sleep
    assert killed  # docker kill (not process-group kill) was used to stop it
