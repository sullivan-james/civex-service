"""Starting and stopping processes, on every OS."""

from __future__ import annotations

import subprocess
import sys

from civex.processes import new_group_kwargs, pid_alive, terminate_tree

_SLEEP = [sys.executable, "-c", "import time; time.sleep(60)"]


def test_a_running_process_is_alive_and_a_finished_one_is_not() -> None:
    import os

    assert pid_alive(os.getpid())
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    done.wait()
    assert not pid_alive(done.pid)
    assert not pid_alive(0)


def test_terminate_tree_stops_a_child_started_in_its_own_group() -> None:
    proc = subprocess.Popen(_SLEEP, **new_group_kwargs())
    try:
        assert pid_alive(proc.pid)
        terminate_tree(proc, grace_seconds=5.0)
        assert proc.poll() is not None
        assert not pid_alive(proc.pid)
    finally:
        if proc.poll() is None:
            proc.kill()


def test_terminate_tree_on_an_already_finished_process_is_harmless() -> None:
    proc = subprocess.Popen([sys.executable, "-c", "pass"], **new_group_kwargs())
    proc.wait()
    terminate_tree(proc)
