"""Finishes an update of `civex serve` after the server has exited.

    python -I civex_update_helper.py PLAN.json

Started by `civex.updates.begin` (or `civex update`, for the desktop app's copy
on Windows), from a copy outside the package, with the base interpreter.
Standard library only, and it never imports civex: civex is what it is
replacing. It waits for civex to stop, runs the upgrade command it was given
(the same one `civex update` runs, with the plan's `env` if it has one), writes
what happened to the plan's `result` file, and starts the server again whatever
the outcome, so a failed update leaves the old version running rather than
nothing. A plan with no `restart` (from `civex update`) only says how it went.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WAIT_SECONDS = 120


def _alive(pid: int) -> bool:
    """`civex.processes.pid_alive`, which can't be imported from here."""
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(ok) and code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _log_name(command: list[str]) -> str:
    """serve-<port>.log for a server started on a port, else serve.log: one
    log per server, so two started again don't write over each other."""
    for flag in ("--port", "-p"):
        if flag in command[:-1]:
            return f"serve-{command[command.index(flag) + 1]}.log"
    return "serve.log"


def _detached(plan: dict[str, Any], command: list[str]) -> dict[str, Any]:
    if sys.platform == "win32":
        # Its own console window, showing its output: a server people can see
        # and close.
        return {"creationflags": subprocess.CREATE_NEW_CONSOLE}
    # Its own log beside this one, started afresh each time, so a server left
    # running doesn't fill the update log.
    serve_log = open(Path(plan["log"]).with_name(_log_name(command)), "w")  # noqa: SIM115
    return {"start_new_session": True, "stdout": serve_log, "stderr": subprocess.STDOUT}


def _write_result(plan: dict[str, Any], **outcome: Any) -> None:
    path = Path(plan["result"])
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "from": plan["from"],
        **outcome,
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record), "utf-8")
    os.replace(tmp, path)


def _free(path: str) -> bool:
    """A file nothing has open to run (Windows won't let it be replaced)."""
    try:
        os.close(os.open(path, os.O_RDWR))
    except PermissionError:
        return False
    except OSError:
        return True  # not there: nothing holds it
    return True


def _start(command: list[str], cwd: str, plan: dict[str, Any]) -> None:
    print("starting: " + " ".join(command), flush=True)
    try:
        subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            **_detached(plan, command),
        )
    except OSError as e:
        print(f"couldn't start it: {e}", flush=True)


def _upgrade(plan: dict[str, Any]) -> tuple[str | None, str]:
    """Run the upgrade once its files are free: (the version now, what went
    wrong or "")."""
    deadline = time.monotonic() + WAIT_SECONDS
    while not all(_free(p) for p in plan.get("free") or []):
        if time.monotonic() > deadline:
            return None, (
                "Something else is still running civex from this copy (a "
                "`civex serve` in a terminal?): stop it, then update again."
            )
        time.sleep(0.5)
    print("running: " + " ".join(plan["upgrade"]), flush=True)
    upgrade = subprocess.run(
        plan["upgrade"], stdin=subprocess.DEVNULL, env=plan.get("env")
    )
    after = subprocess.run(plan["version"], capture_output=True, text=True)
    now = after.stdout.strip() if after.returncode == 0 else None
    if now and now != plan["from"]:
        # civex got there, whatever the exit code said (an entry point left
        # behind by a file in use is not worth calling the update failed).
        return now, ""
    if upgrade.returncode != 0:
        return (
            now,
            f"The upgrade failed (exit {upgrade.returncode}); see {plan['log']}.",
        )
    return now, (
        "The upgrade ran but civex is still the same version: a dependency "
        f"of the new one may not install here. See {plan['log']}."
    )


def main(plan_file: str) -> int:
    plan = json.loads(Path(plan_file).read_text("utf-8"))
    print(f"[{time.ctime()}] updating civex {plan['from']}", flush=True)

    deadline = time.monotonic() + WAIT_SECONDS
    while _alive(plan["wait_pid"]):
        if time.monotonic() > deadline:
            _write_result(plan, ok=False, to=None, message="civex didn't stop.")
            return 1
        time.sleep(0.2)

    now, message = _upgrade(plan)
    _write_result(plan, ok=not message, to=now, message=message)

    # The servers stopped for this, started again whatever happened.
    for other in plan.get("also_start") or []:
        _start(other["command"], other["cwd"], plan)
    if not plan.get("restart"):
        # `civex update` from a terminal: say how it went there, and stop.
        if message:
            print(f"Update failed: {message}", flush=True)
            return 1
        print(f"Updated civex {plan['from']} -> {now}.", flush=True)
        return 0
    _start(plan["restart"], plan["cwd"], plan)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
