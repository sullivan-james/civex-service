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
                           (e.g. "civex[desktop] @ file:///.../civex.whl"),
                           every time it starts: how a test build's own wheel
                           is tried in its app
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


def log_dir() -> Path:
    """Where the launcher and the desktop app keep their logs: inside the
    launcher's own folder (in AppData on Windows)."""
    return app_home() / "logs"


def bundled_uv() -> Path:
    """The uv inside this app (or, run from source, the one on PATH).

    A built app never falls back to PATH: a uv missing from the app would
    then go unnoticed wherever one happens to be installed (CI runners have
    one), and fail only on the computers that don't."""
    here = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    inside = here / "uv" / f"uv{EXE}"
    if inside.exists():
        return inside
    if not getattr(sys, "frozen", False) and (found := shutil.which("uv")):
        return Path(found)
    raise RuntimeError(f"This copy of the civex app is missing its uv ({inside}).")


def record_where(home: Path, uv: Path) -> None:
    """Say where this app and its uv are, in its own folder, each time it
    starts: so `civex update` run from a terminal can update the app's copy
    with the app's uv (`civex.updates.app_uv`) wherever the app was put."""
    try:
        (home / "launcher.json").write_text(
            json.dumps({"uv": str(uv), "app": sys.executable}), "utf-8"
        )
    except OSError:
        pass  # only a convenience: civex also looks in the standard places


def tool_python(home: Path, windowed: bool = False) -> Path:
    """The Python civex is installed in. `windowed`: on Windows the one that
    never opens a console window (pythonw), for the desktop window."""
    tool = home / "tools" / "civex"
    if sys.platform == "win32":
        return tool / "Scripts" / ("pythonw.exe" if windowed else "python.exe")
    return tool / "bin" / "python"


def desktop_app(home: Path) -> Path:
    """What starts the desktop window: civex's own Python, running
    `civex.desktop.tray` (there is no `civex-desktop` command, so that a
    plain `uv tool install civex` doesn't get one that can't work)."""
    return tool_python(home, windowed=True)


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
            # The desktop app's log goes beside this one (desktop/tray.py).
            "CIVEX_LOG_DIR": str(home / "logs"),
        }
    )
    return env


# -- Installing and updating -------------------------------------------------


def released_with() -> str | None:
    """The civex version this app was released with (launcher.spec puts it
    in the app), or None for a build without one."""
    here = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    try:
        version = (here / "civex_version.txt").read_text("utf-8").strip()
    except OSError:
        return None
    return version or None


def requirement() -> str:
    """What to install: at least the civex this app was released with. Not
    `==`: uv keeps a tool to the requirement it was installed with, so that
    would stop every update. A bound that names a pre-release lets uv take
    pre-releases of civex, so a release candidate's app gets that candidate
    (plain `civex[desktop]` took the newest *stable* civex: an older one)."""
    version = released_with()
    return f"{REQUIREMENT}>={version}" if version else REQUIREMENT


def install_command(uv: Path) -> list[str]:
    source = os.environ.get("CIVEX_LAUNCHER_SOURCE") or requirement()
    return [str(uv), "tool", "install", "--force", source]


def upgrade_command(uv: Path, pre: bool) -> list[str]:
    """For an app that doesn't say which version to install (older civex).
    `--prerelease allow` lets in pre-releases of *every* package; a request
    that names the version (`to_command`) lets in civex's alone."""
    return [
        str(uv),
        "tool",
        "upgrade",
        *(["--prerelease", "allow"] if pre else []),
        "civex",
    ]


def to_command(uv: Path, version: str) -> list[str]:
    """Install exactly the civex the app found (or newer): a requirement that
    names a pre-release allows a pre-release for civex and for nothing else
    (`civex.updates.upgrade_command` builds the same)."""
    return [str(uv), "tool", "install", "--force", f"{REQUIREMENT}>={version}"]


def command_busy(home: Path) -> bool:
    """Whether something still runs this app's `civex` command (a `civex serve`
    in a terminal): Windows then won't let the update replace it."""
    if sys.platform != "win32":
        return False
    try:
        os.close(os.open(home / "bin" / f"civex{EXE}", os.O_RDWR))
    except PermissionError:
        return True
    except OSError:
        return False
    return False


def ask_retry(title: str, message: str) -> bool:
    """Retry (True) or Cancel; Cancel without a window to ask in."""
    if HEADLESS:
        print(f"{title}: {message}", file=sys.stderr)
        return False
    root = _new_window()
    if root is None:
        return False
    from tkinter import messagebox

    root.withdraw()
    again = messagebox.askretrycancel(title, message, parent=root)
    root.destroy()
    return bool(again)


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


def _asset(name: str) -> Path:
    """A file bundled with the app (launcher.spec), or beside this script."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / name
    return Path(__file__).resolve().parent / "assets" / name


def _new_window():  # -> tkinter.Tk, or None without a display
    """A Tk root dressed as a native window: sharp text on high-resolution
    Windows screens, the platform's own theme, civex's icon."""
    if sys.platform == "win32":
        try:  # before the first window, or Windows scales a blurry bitmap
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    try:
        import tkinter as tk
        from tkinter import ttk

        root = tk.Tk()
    except Exception:  # no tkinter, or no display
        return None
    style = ttk.Style(root)
    native = {"win32": "vista", "darwin": "aqua"}.get(sys.platform, "clam")
    if native in style.theme_names():
        style.theme_use(native)
    try:
        icon = tk.PhotoImage(file=str(_asset("civex.png")))
        root.iconphoto(True, icon)
        root._civex_icon = icon  # keep a reference, or Tk drops the image
    except Exception:
        pass
    return root


def _centre(root) -> None:
    root.update_idletasks()
    width, height = root.winfo_reqwidth(), root.winfo_reqheight()
    x = (root.winfo_screenwidth() - width) // 2
    y = (root.winfo_screenheight() - height) // 3
    root.geometry(f"+{x}+{y}")


def with_progress(title: str, message: str, work: Callable[[], None]) -> None:
    """Run `work` with a window saying what is happening (the logo, `title`
    as a heading, `message`, a moving bar); without a display (CI, a
    terminal), just run it."""
    root = None if HEADLESS else _new_window()
    if root is None:
        print(message, flush=True)
        work()
        return

    import tkinter as tk
    from tkinter import font, ttk

    root.title("civex")
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=(28, 24, 28, 24))
    frame.pack(fill="both", expand=True)
    try:
        logo = tk.PhotoImage(file=str(_asset("civex.png"))).subsample(16)  # 64 px
        ttk.Label(frame, image=logo).grid(row=0, column=0, rowspan=3, sticky="n")
        frame._civex_logo = logo  # keep a reference
        text_column = 1
    except Exception:
        text_column = 0
    heading = font.nametofont("TkDefaultFont").copy()
    heading.configure(size=heading.cget("size") + 4, weight="bold")
    padx = (18, 0) if text_column else 0
    ttk.Label(frame, text=title, font=heading).grid(
        row=0, column=text_column, sticky="w", padx=padx
    )
    ttk.Label(frame, text=message, wraplength=360, justify="left").grid(
        row=1, column=text_column, sticky="w", padx=padx, pady=(6, 14)
    )
    bar = ttk.Progressbar(frame, mode="indeterminate", length=360)
    bar.grid(row=2, column=text_column, sticky="we", padx=padx)
    bar.start(12)
    root.protocol("WM_DELETE_WINDOW", lambda: None)  # finish what was started
    _centre(root)
    root.lift()
    root.attributes("-topmost", True)  # in front of the installer or Finder
    root.after(500, lambda: root.attributes("-topmost", False))
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
    root = _new_window()
    if root is None:
        print(f"{title}: {message}", file=sys.stderr)
        return
    from tkinter import messagebox

    root.withdraw()
    messagebox.showerror(title, message, parent=root)
    root.destroy()


# -- Starting civex ----------------------------------------------------------


class SetupFailed(Exception):
    pass


def older_than_release(home: Path, env: dict[str, str], installed: str) -> bool:
    """Whether the civex installed here is older than the one this app was
    released with (a newer app installed over an older one). Asked of the
    installed civex's own Python, which has `packaging`; this launcher keeps
    to the standard library."""
    wanted = released_with()
    if not wanted or installed == wanted:
        return False
    result = subprocess.run(
        [
            str(tool_python(home)),
            "-c",
            "import sys; from packaging.version import Version as V; "
            "sys.exit(0 if V(sys.argv[1]) < V(sys.argv[2]) else 1)",
            installed,
            wanted,
        ],
        env=env,
        capture_output=True,
        **_no_window(),
    )
    return result.returncode == 0


def ensure_installed(home: Path, uv: Path, env: dict[str, str], log: Path) -> None:
    installed = civex_version(home, env) if desktop_app(home).exists() else None
    # An explicit source (a wheel from a test build) is installed every time:
    # it is what was asked for, whatever is there already.
    explicit = bool(os.environ.get("CIVEX_LAUNCHER_SOURCE"))
    if installed and not explicit and not older_than_release(home, env, installed):
        return

    def _install() -> None:
        if run_logged(install_command(uv), env, log) != 0:
            raise SetupFailed(
                "civex couldn't be set up. Check the internet connection and "
                f"try again.\n\nDetails: {log}"
            )

    if installed:
        title, message = "Updating civex", "This takes a minute."
    else:
        title, message = "Setting up civex", "This takes a minute or two."
    with_progress(title, message, _install)


_BUSY = (
    "civex is still running from this app's copy, outside the app (a `civex "
    "serve` in a terminal?), so it can't be updated. Stop it (Ctrl+C in its "
    "window), then press Retry."
)


def update(home: Path, uv: Path, env: dict[str, str], log: Path, request: dict) -> None:
    """Upgrade as the app asked, and record what happened for it to show."""
    before = request.get("from") or civex_version(home, env)
    while command_busy(home):
        if not ask_retry("civex", _BUSY):
            if request.get("result"):
                write_result(
                    request["result"],
                    **{
                        "from": before,
                        "to": before,
                        "ok": False,
                        "message": "Not updated: civex was still running from "
                        "this copy outside the app.",
                    },
                )
            return
    to = request.get("to")
    command = (
        to_command(uv, to) if to else upgrade_command(uv, bool(request.get("pre")))
    )
    code: list[int] = []
    with_progress(
        "Updating civex",
        "civex opens again when it's done.",
        lambda: code.append(run_logged(command, env, log)),
    )
    after = civex_version(home, env)
    if after and after != before:
        # civex got there, whatever uv's exit said (an entry point left behind
        # by a file in use is not worth calling the update failed).
        ok, message = True, ""
    elif code and code[0] != 0:
        ok, message = False, f"The update failed; see {log}."
    else:
        ok, message = False, "There was nothing newer to install."
    if request.get("result"):
        write_result(
            request["result"],
            **{"from": before, "to": after, "ok": ok, "message": message},
        )


def run_app(home: Path, args: list[str], env: dict[str, str]) -> None:
    """Start the civex desktop app and wait until it closes."""
    subprocess.run(
        [str(desktop_app(home)), "-m", "civex.desktop.tray", *args],
        env=env,
        **_no_window(),
    )


def main(argv: list[str]) -> int:
    global HEADLESS
    HEADLESS = "--install-only" in argv
    home = app_home()
    home.mkdir(parents=True, exist_ok=True)
    log_dir().mkdir(parents=True, exist_ok=True)
    log = log_dir() / "launcher.log"
    try:
        uv = bundled_uv()
        record_where(home, uv)
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
