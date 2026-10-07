"""The civex desktop app, for computers without Python.

This is the whole downloadable app: a small program carrying `uv`. It never
contains civex itself. On first start it installs civex (and a Python for it)
with uv into a folder of its own; then it starts the civex desktop app and
waits for it. When the app asks for an update (`civex.updates`: it writes a
request to the file named by CIVEX_UPDATE_REQUEST and closes), the launcher
upgrades civex with the same uv and starts it again. So the desktop app updates
the same way as every other install (`uv tool upgrade`), and civex is never
replaced while it is running.

Standard library only (tkinter for the progress window), and it must never
import civex. Built by desktop-launcher/launcher.spec.

    civex_launcher.py               start civex (installing it the first time)
    civex_launcher.py --install-only
                                    install civex if it isn't yet, print where
                                    its CLI is, and exit (for CI and
                                    troubleshooting)

Environment, for CI and testing only:
    CIVEX_APP_HOME         where to keep civex instead of the per-user folder
    CIVEX_LAUNCHER_SOURCE  what to install instead of civex[desktop] from PyPI
                           (e.g. "civex[desktop] @ file:///.../civex.whl")
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import traceback
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

REQUIREMENT = "civex[desktop]"
#: No windows at all (--install-only): a dialog in CI would wait forever.
HEADLESS = False
REQUEST_ENV = "CIVEX_UPDATE_REQUEST"  # civex.updates.REQUEST_ENV
EXE = ".exe" if sys.platform == "win32" else ""


# -- Where things are --------------------------------------------------------


def app_home() -> Path:
    """The launcher's own folder: civex, its Python, uv's cache, the log."""
    if override := os.environ.get("CIVEX_APP_HOME"):
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    return base / "civex" / "app"


def bundled_uv() -> Path:
    """The uv inside this app (or, run from source, the one on PATH)."""
    here = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    inside = here / "uv" / f"uv{EXE}"
    if inside.exists():
        return inside
    found = shutil.which("uv")
    if found:
        return Path(found)
    raise RuntimeError("This copy of the civex app is missing its uv.")


def desktop_app(home: Path) -> Path:
    return home / "bin" / f"civex-desktop{EXE}"


def environment(home: Path, uv: Path) -> dict[str, str]:
    """What uv and civex run with: everything in the launcher's own folder,
    and a Python uv downloads, never one already on the computer."""
    env = dict(os.environ)
    # A PyInstaller app changes the library path for itself; programs it
    # starts need the original (PyInstaller keeps it as *_ORIG).
    for name in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        original = env.pop(f"{name}_ORIG", None)
        if original is not None:
            env[name] = original
        elif getattr(sys, "frozen", False):
            env.pop(name, None)
    for name in ("VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH", "CONDA_PREFIX"):
        env.pop(name, None)
    env.update(
        {
            "UV_TOOL_DIR": str(home / "tools"),
            "UV_TOOL_BIN_DIR": str(home / "bin"),
            "UV_PYTHON_INSTALL_DIR": str(home / "python"),
            "UV_CACHE_DIR": str(home / "cache"),
            "UV_PYTHON_PREFERENCE": "only-managed",
            # civex runs custom plugins with uv (plugins/subprocess_runtime.py).
            "CIVEX_UV_BIN": str(uv),
        }
    )
    return env


# -- Installing and updating -------------------------------------------------


def install_command(uv: Path) -> list[str]:
    source = os.environ.get("CIVEX_LAUNCHER_SOURCE", REQUIREMENT)
    return [str(uv), "tool", "install", "--force", source]


def upgrade_command(uv: Path, pre: bool) -> list[str]:
    return [
        str(uv),
        "tool",
        "upgrade",
        *(["--prerelease", "allow"] if pre else []),
        "civex",
    ]


def civex_version(home: Path, env: dict[str, str]) -> str | None:
    result = subprocess.run(
        [str(home / "bin" / f"civex{EXE}"), "--version"],
        env=env,
        capture_output=True,
        text=True,
        **_no_window(),
    )
    out = result.stdout.strip().split()
    return out[-1] if result.returncode == 0 and out else None


def run_logged(cmd: list[str], env: dict[str, str], log: Path) -> int:
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"\n[{_now()}] {' '.join(cmd)}\n")
        f.flush()
        return subprocess.run(
            cmd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=f,
            stderr=subprocess.STDOUT,
            **_no_window(),
        ).returncode


def _no_window() -> dict:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tail(log: Path, lines: int = 15) -> str:
    try:
        return "\n".join(log.read_text("utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


def write_result(path: str, **outcome: object) -> None:
    """The same record `civex.updates.last_result` reads."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps({"at": _now(), **outcome}), "utf-8")
    os.replace(tmp, target)


def take_request(path: Path) -> dict | None:
    """The update the app asked for when it closed, if it did."""
    try:
        request = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    finally:
        path.unlink(missing_ok=True)
    return request if isinstance(request, dict) else None


# -- The progress window -----------------------------------------------------


def with_progress(title: str, message: str, work: Callable[[], None]) -> None:
    """Run `work` with a small window saying what is happening; without a
    display (CI, a terminal), just run it."""
    if HEADLESS:
        print(message, flush=True)
        work()
        return
    try:
        import tkinter as tk
        from tkinter import ttk

        root = tk.Tk()
    except Exception:  # no tkinter or no display
        print(message, flush=True)
        work()
        return

    root.title(title)
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=message, wraplength=360).pack(anchor="w")
    bar = ttk.Progressbar(frame, mode="indeterminate", length=360)
    bar.pack(pady=(12, 0))
    bar.start(12)
    root.protocol("WM_DELETE_WINDOW", lambda: None)  # finish what was started
    failure: list[BaseException] = []

    def _run() -> None:
        try:
            work()
        except BaseException as e:  # reported once the window is gone
            failure.append(e)
        finally:
            root.after(0, root.destroy)

    threading.Thread(target=_run, daemon=True).start()
    root.mainloop()
    if failure:
        raise failure[0]


def show_error(title: str, message: str) -> None:
    if HEADLESS:
        print(f"{title}: {message}", file=sys.stderr)
        return
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        print(f"{title}: {message}", file=sys.stderr)


# -- Starting civex ----------------------------------------------------------


class SetupFailed(Exception):
    pass


def ensure_installed(home: Path, uv: Path, env: dict[str, str], log: Path) -> None:
    if desktop_app(home).exists() and civex_version(home, env):
        return

    def _install() -> None:
        if run_logged(install_command(uv), env, log) != 0:
            raise SetupFailed(
                "civex couldn't be installed. It needs an internet connection "
                "the first time it starts.\n\n" + _tail(log)
            )

    with_progress(
        "Setting up civex",
        "Setting up civex for the first time. This downloads civex and the "
        "Python it runs on, once, and can take a minute or two.",
        _install,
    )


def update(home: Path, uv: Path, env: dict[str, str], log: Path, request: dict) -> None:
    """Upgrade as the app asked, and record what happened for it to show."""
    before = request.get("from") or civex_version(home, env)
    code: list[int] = []
    with_progress(
        "Updating civex",
        "Updating civex. It will open again when it's done.",
        lambda: code.append(
            run_logged(upgrade_command(uv, bool(request.get("pre"))), env, log)
        ),
    )
    after = civex_version(home, env)
    if code and code[0] != 0:
        ok, message = False, f"The update failed; see {log}."
    elif after == before:
        ok, message = False, "There was nothing newer to install."
    else:
        ok, message = True, ""
    if request.get("result"):
        write_result(
            request["result"],
            **{"from": before, "to": after, "ok": ok, "message": message},
        )


def run_app(home: Path, args: list[str], env: dict[str, str]) -> None:
    """Start the civex desktop app and wait until it closes."""
    subprocess.run([str(desktop_app(home)), *args], env=env)


def main(argv: list[str]) -> int:
    global HEADLESS
    HEADLESS = "--install-only" in argv
    home = app_home()
    home.mkdir(parents=True, exist_ok=True)
    log = home / "launcher.log"
    try:
        uv = bundled_uv()
        env = environment(home, uv)
        ensure_installed(home, uv, env, log)
        if "--install-only" in argv:
            print(home / "bin" / f"civex{EXE}")
            return 0

        request_file = home / "update-request.json"
        args: list[str] = []
        while True:
            request_file.unlink(missing_ok=True)
            run_app(home, args, {**env, REQUEST_ENV: str(request_file)})
            request = take_request(request_file)
            if request is None:
                return 0  # closed by the person, not for an update
            update(home, uv, env, log, request)
            project = request.get("project")
            args = ["--project", project] if project else []
    except SetupFailed as e:
        show_error("civex", str(e))
        return 1
    except Exception:
        with open(log, "a", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        show_error(
            "civex", f"Something went wrong starting civex. Details are in {log}."
        )
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
