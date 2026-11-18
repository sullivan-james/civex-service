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


def test_on_windows_a_child_gets_no_console_window(monkeypatch) -> None:
    """The desktop app runs under pythonw: a console child (uv, a plugin's
    python) would otherwise open a window of its own for each step."""
    from civex.processes import no_window_kwargs

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False
    )
    assert no_window_kwargs() == {"creationflags": 0x08000000}
    assert new_group_kwargs()["creationflags"] & 0x08000000
    assert new_group_kwargs()["creationflags"] & 0x00000200
