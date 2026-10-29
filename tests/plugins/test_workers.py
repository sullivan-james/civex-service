"""Plugin processes kept between steps (`civex.plugins.workers`) and the
subprocess runtime's use of them. Plugins here are plain `sys.executable`
children speaking the SDK protocol, as in test_subprocess_runtime.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from civex.domain.exceptions import PluginExecutionError, PluginTimeoutError
from civex.plugins import subprocess_runtime as rt
from civex.plugins import workers
from civex.plugins.workers import Worker, WorkerPool

_PLUGIN = """\
import os
from pydantic import BaseModel
from civex_plugin_sdk import Ctx, Plugin, PluginError, serve

class P(Plugin):
    id = "test.pid"
    name = "Pid"

    class Config(BaseModel):
        pass

    def invoke(self, inputs, config, ctx: Ctx) -> dict:
        if inputs.get("fail"):
            raise PluginError("asked to fail", kind="bad_input")
        if inputs.get("sleep"):
            import time
            time.sleep(inputs["sleep"])
        left = sorted(os.listdir("."))
        open("made-by-run.txt", "w").write("x")
        return {"pid": os.getpid(), "left": left}

if __name__ == "__main__":
    serve(P)
"""


@pytest.fixture
def plugin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A plugin started with this venv's Python instead of `uv run`."""
    path = tmp_path / "pid_plugin.py"
    path.write_text(_PLUGIN)
    monkeypatch.setattr(rt, "_build_command", lambda uv, p: [sys.executable, str(p)])
    monkeypatch.setattr(rt, "find_uv_binary", lambda: "uv")
    return path


def _run(plugin: Path, timeout: float = 20.0, **inputs) -> dict:
    return rt.run_plugin(
        plugin, inputs, {}, ctx=None, capabilities=[], timeout=timeout
    ).outputs  # type: ignore[arg-type]


def test_a_second_run_uses_the_same_process(plugin: Path) -> None:
    first = _run(plugin)
    second = _run(plugin)
    assert first["pid"] == second["pid"]
    assert workers.POOL.idle_count() == 1


def test_describing_leaves_the_process_for_the_first_run(plugin: Path) -> None:
    rt.describe_plugin(plugin)
    pid = _run(plugin)["pid"]
    assert _run(plugin)["pid"] == pid


def test_each_run_starts_in_an_empty_folder(plugin: Path) -> None:
    assert _run(plugin)["left"] == []
    assert _run(plugin)["left"] == []  # what the first run wrote is gone


def test_an_edited_plugin_gets_a_new_process(plugin: Path) -> None:
    pid = _run(plugin)["pid"]
    plugin.write_text(_PLUGIN + "\n# edited\n")
    assert _run(plugin)["pid"] != pid


def test_the_plugins_own_error_keeps_the_process(plugin: Path) -> None:
    pid = _run(plugin)["pid"]
    with pytest.raises(PluginExecutionError) as e:
        _run(plugin, fail=True)
    assert e.value.kind == "bad_input"
    assert _run(plugin)["pid"] == pid


def test_a_timed_out_process_is_not_kept(plugin: Path) -> None:
    pid = _run(plugin)["pid"]
    with pytest.raises(PluginTimeoutError):
        _run(plugin, timeout=0.5, sleep=30)
    assert workers.POOL.idle_count() == 0
    assert _run(plugin)["pid"] != pid


def test_a_kept_process_that_died_is_replaced(plugin: Path) -> None:
    _run(plugin)
    (worker,) = [w for ws in workers.POOL._idle.values() for w in ws]
    worker.proc.kill()
    worker.proc.wait()
    outputs = _run(plugin)
    assert outputs["pid"] != worker.proc.pid


def test_a_kept_process_whose_pipe_broke_is_replaced_once(
    plugin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gone between the liveness check and the request: the request is
    written to a closed pipe, and a fresh process is asked instead."""
    _run(plugin)
    (worker,) = [w for ws in workers.POOL._idle.values() for w in ws]
    worker.proc.kill()
    worker.proc.wait()
    monkeypatch.setattr(Worker, "alive", lambda self: True)  # it looks alive
    assert _run(plugin)["pid"] != worker.proc.pid


def test_stderr_is_read_while_the_process_runs(tmp_path: Path) -> None:
    """A long-lived process writing lots to stderr must not block on a full
    pipe; the last lines are kept for the message if it dies."""
    script = tmp_path / "noisy.py"
    script.write_text(
        "import sys\n"
        "for i in range(20000): sys.stderr.write(f'line {i} ' + 'x' * 40 + '\\n')\n"
        "sys.exit(3)\n"
    )
    proc = rt._spawn([sys.executable, str(script)], tmp_path)
    assert proc.wait(timeout=20) == 3
    message = rt._dead_process_message(proc)
    assert "line 19999" in message and "line 0 " not in message


# -- the pool by itself --------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _sleeper(tmp_path: Path, key: str = "k") -> Worker:
    proc = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.read()"],
        stdin=subprocess.PIPE,
    )
    scratch = tmp_path / f"scratch-{proc.pid}"
    scratch.mkdir()

    def stop(w: Worker) -> None:
        if w.proc.stdin:
            w.proc.stdin.close()
        w.proc.wait(timeout=5)

    return Worker(key=key, proc=proc, scratch_dir=scratch, stop=stop)


def test_idle_workers_are_stopped_after_the_idle_time(tmp_path: Path) -> None:
    clock = _Clock()
    pool = WorkerPool(idle_seconds=60, clock=clock)
    worker = _sleeper(tmp_path)
    pool.checkin(worker, healthy=True)
    clock.now = 59
    assert pool.reap() == 0
    clock.now = 60
    assert pool.reap() == 1
    assert not worker.alive()
    assert not worker.scratch_dir.exists()
    pool.close()


def test_an_unhealthy_worker_is_stopped_not_kept(tmp_path: Path) -> None:
    pool = WorkerPool()
    worker = _sleeper(tmp_path)
    pool.checkin(worker, healthy=False)
    assert pool.idle_count() == 0
    assert not worker.alive()


def test_no_more_than_the_limit_are_kept_per_plugin(tmp_path: Path) -> None:
    pool = WorkerPool(max_idle_per_key=1)
    first, second = _sleeper(tmp_path), _sleeper(tmp_path)
    pool.checkin(first, healthy=True)
    pool.checkin(second, healthy=True)
    assert pool.idle_count() == 1
    assert not second.alive()
    pool.close()
    assert not first.alive()


def test_idle_seconds_zero_keeps_nothing(tmp_path: Path) -> None:
    pool = WorkerPool(idle_seconds=0)
    worker = _sleeper(tmp_path)
    pool.checkin(worker, healthy=True)
    assert pool.idle_count() == 0


def test_checkout_starts_one_when_none_is_idle_for_that_key(tmp_path: Path) -> None:
    pool = WorkerPool()
    kept = _sleeper(tmp_path, key="a")
    pool.checkin(kept, healthy=True)
    started = []

    def start() -> Worker:
        started.append(_sleeper(tmp_path, key="b"))
        return started[-1]

    assert pool.checkout("b", start) is started[0]
    assert pool.checkout("a", start) is kept
    for w in (kept, *started):
        w.close()
