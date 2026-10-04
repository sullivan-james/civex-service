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


def new_group_kwargs() -> dict[str, Any]:
    """`Popen` arguments that put the child (and anything it starts) in its own
    process group, so `terminate_tree` can stop them as one."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
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
