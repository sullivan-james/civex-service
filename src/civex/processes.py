"""Starting, stopping and checking processes, the same way on every OS."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from typing import Any


def pid_alive(pid: int) -> bool:
    """True if a process with this id exists. A process we may not signal still
    exists, so that counts as alive."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
            process_query_limited_information, False, pid
        )
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(  # type: ignore[attr-defined]
                handle, ctypes.byref(code)
            )
            return bool(ok) and code.value == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_start_token(pid: int) -> str | None:
    """Tells one run of a process from another that has the same id (ids are
    reused: in a container a restarted server is pid 1 again): the time it
    started (and, on Linux, the boot). None where it cannot be read."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
                0x1000, False, pid
            )
            if not handle:
                return None
            try:
                created, a, b, c = (wintypes.FILETIME() for _ in range(4))
                ok = ctypes.windll.kernel32.GetProcessTimes(  # type: ignore[attr-defined]
                    handle,
                    ctypes.byref(created),
                    ctypes.byref(a),
                    ctypes.byref(b),
                    ctypes.byref(c),
                )
                if not ok:
                    return None
                return str((created.dwHighDateTime << 32) | created.dwLowDateTime)
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
        if sys.platform.startswith("linux"):
            with open(f"/proc/{pid}/stat") as f:
                fields = f.read().rsplit(")", 1)[1].split()
            with open("/proc/sys/kernel/random/boot_id") as f:
                boot = f.read().strip()
            return f"{boot}:{fields[19]}"  # field 22: start time, in ticks since boot
        out = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
        return out or None
    except (OSError, IndexError, ValueError, subprocess.SubprocessError):
        return None


def process_namespace() -> str:
    """Where process ids mean something: containers that share a volume each
    have their own (all run pid 1), so a process id found in a lock on it says
    nothing about a process of another. Linux: the pid namespace and the boot;
    elsewhere the host name."""
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/sys/kernel/random/boot_id") as f:
                boot = f.read().strip()
            return f"{os.stat('/proc/self/ns/pid').st_ino}-{boot}"
    except OSError:
        pass
    import socket

    return socket.gethostname()


def no_window_kwargs() -> dict[str, Any]:
    """`Popen` arguments that keep a console program from opening a window of
    its own on Windows. A program started from one with no console (the
    desktop app runs under `pythonw`) otherwise gets a new console window,
    which shows for as long as it runs and takes time to open."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def new_group_kwargs() -> dict[str, Any]:
    """`Popen` arguments that put the child (and anything it starts) in its own
    process group, so `terminate_tree` can stop them as one, without a window
    of its own on Windows (`no_window_kwargs`)."""
    if sys.platform == "win32":
        return {
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        }
    return {"start_new_session": True}


def terminate_tree(proc: subprocess.Popen, grace_seconds: float = 2.0) -> None:
    """Stop `proc` and everything it started. POSIX asks politely (SIGTERM to
    the group), waits `grace_seconds`, then kills; Windows has no polite
    signal for a console child, so `taskkill /T /F` ends the whole tree."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            check=False,
            **no_window_kwargs(),
        )
        try:
            proc.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            pass
        return
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
