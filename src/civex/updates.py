"""Updating civex itself: what is available, how this copy was installed, and
how to update it -- the one rule behind `civex update`, `/api/update` and the
app's Updates page.

An install is never replaced while civex is running from it: on Windows a
running program can't be overwritten, and anywhere a half-replaced package
can't be trusted. So an update from the app happens *after* civex exits:

- The desktop app is started by the civex launcher, which waits for it. The
  app writes a request to the file named by ``REQUEST_ENV`` and closes; the
  launcher upgrades with its own uv and starts it again.
- ``civex serve`` hands over to ``_update_helper.py`` (stdlib only, copied out
  of the package it is about to replace), which waits for the server to stop,
  runs the same upgrade ``civex update`` would, and starts it again.

Either way the outcome is written to ``result_path()`` and reported by the next
``check``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import Any

from civex import __version__

_PYPI_URL = "https://pypi.org/pypi/civex/json"

#: Set by the desktop launcher for the app it starts: where to ask for an update.
REQUEST_ENV = "CIVEX_UPDATE_REQUEST"
#: Set by `civex serve`: its own arguments, so it can be started again.
SERVE_ARGS_ENV = "CIVEX_SERVE_ARGS"


# -- What is available -------------------------------------------------------


def latest_version(pre: bool = False, timeout: float = 10.0) -> str:
    """Latest civex version published on PyPI: the latest stable one, or with
    `pre` the newest of all, release candidates and betas included."""
    from civex.tls import ssl_context

    with urllib.request.urlopen(  # noqa: S310
        _PYPI_URL, timeout=timeout, context=ssl_context()
    ) as resp:
        data = json.load(resp)
    if not pre:
        return data["info"]["version"]
    return newest_release(data["releases"]) or data["info"]["version"]


def newest_release(releases: dict[str, list[dict]]) -> str | None:
    """The highest version in PyPI's `releases` that has files and isn't
    wholly yanked; pre-releases count."""
    from packaging.version import InvalidVersion, Version

    found: list[Version] = []
    for number, files in releases.items():
        if not files or all(f.get("yanked") for f in files):
            continue
        try:
            found.append(Version(number))
        except InvalidVersion:
            continue
    return str(max(found)) if found else None


def is_prerelease(version: str) -> bool:
    from packaging.version import InvalidVersion, Version

    try:
        return Version(version).is_prerelease
    except InvalidVersion:
        return False


# -- How this copy was installed ---------------------------------------------


def app_home() -> Path:
    """The desktop app's own folder, by the launcher's rule
    (`desktop-launcher/civex_launcher.py` `app_home`, which can't import civex;
    `tests/test_desktop_launcher.py` holds the two together)."""
    if override := os.environ.get("CIVEX_APP_HOME"):
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    return base / "civex" / "app"


def _is_app_copy() -> bool:
    """This civex is the one the desktop app installed (in its own folder),
    however it was started: by the app, or as the `civex` command it can put
    on PATH."""
    try:
        return Path(sys.prefix).resolve() == (app_home() / "tools" / "civex").resolve()
    except OSError:
        return False


def _app_uv_candidates() -> list[Path]:
    """Where the desktop app's own uv may be: where its launcher last said it
    is, else the app's standard install folder (PyInstaller puts it in
    `_internal\\uv` on Windows and `Contents/Frameworks/uv` in the macOS app)."""
    out: list[Path] = []
    try:
        recorded = json.loads((app_home() / "launcher.json").read_text("utf-8"))
        if isinstance(recorded, dict) and recorded.get("uv"):
            out.append(Path(str(recorded["uv"])))
    except (OSError, ValueError):
        pass
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
        out.append(local / "Programs" / "civex" / "_internal" / "uv" / "uv.exe")
    elif sys.platform == "darwin":
        for apps in (Path("/Applications"), Path.home() / "Applications"):
            out.append(apps / "civex.app" / "Contents" / "Frameworks" / "uv" / "uv")
    return out


def app_uv() -> Path | None:
    """The uv that updates the desktop app's copy: the one the app gave civex
    (`CIVEX_UV_BIN`, set when the app starts it), the app's own, or any uv on
    PATH (it is told the app's folders, so any uv updates the right copy)."""
    if given := os.environ.get("CIVEX_UV_BIN"):
        return Path(given)
    for candidate in _app_uv_candidates():
        if candidate.is_file():
            return candidate
    found = shutil.which("uv")
    return Path(found) if found else None


def app_uv_env() -> dict[str, str]:
    """The environment uv updates the desktop app's copy with: the launcher's
    own folders (`civex_launcher.environment`), so it finds that copy and uses
    the Python and cache the app already has."""
    home = app_home()
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH", "CONDA_PREFIX")
    }
    env.update(
        {
            "UV_TOOL_DIR": str(home / "tools"),
            "UV_TOOL_BIN_DIR": str(home / "bin"),
            "UV_PYTHON_INSTALL_DIR": str(home / "python"),
            "UV_CACHE_DIR": str(home / "cache"),
            "UV_PYTHON_PREFERENCE": "only-managed",
        }
    )
    return env


def app_is_open() -> bool:
    """Whether the desktop app is running from its copy. On Windows its window
    runs the copy's `pythonw.exe`, which can't be opened for writing while it
    runs; elsewhere files in use can be replaced, so this is False."""
    if sys.platform != "win32":
        return False
    pythonw = app_home() / "tools" / "civex" / "Scripts" / "pythonw.exe"
    try:
        os.close(os.open(pythonw, os.O_RDWR))
    except PermissionError:
        return True
    except OSError:
        return False
    return False


def detect_installer() -> str:
    """How this civex was installed: ``desktop`` (the desktop app, started by
    its launcher) | ``app`` (the desktop app's copy, started from a terminal:
    nothing waits to update it) | ``frozen`` (an old all-in-one desktop build)
    | ``editable`` | ``pipx`` | ``uv`` | ``pip``."""
    if os.environ.get(REQUEST_ENV):
        return "desktop"
    if getattr(sys, "frozen", False):
        return "frozen"
    if _is_app_copy():
        return "app"
    try:
        direct_url = distribution("civex").read_text("direct_url.json")
        if direct_url and json.loads(direct_url).get("dir_info", {}).get("editable"):
            return "editable"
    except (PackageNotFoundError, ValueError):
        pass
    parts = Path(sys.prefix).parts
    if "pipx" in parts and "venvs" in parts:
        return "pipx"
    if "uv" in parts and "tools" in parts:
        return "uv"
    return "pip"


def installed_version() -> str | None:
    """civex's version as installed *now*, read in a fresh interpreter.

    ``civex.__version__`` was fixed when this process started, so it can't
    show the effect of the upgrade we just ran.
    """
    result = subprocess.run(
        [sys.executable, "-c", _VERSION_SNIPPET], capture_output=True, text=True
    )
    return result.stdout.strip() or None if result.returncode == 0 else None


_VERSION_SNIPPET = "from importlib.metadata import version; print(version('civex'))"


def upgrade_command(installer: str, pre: bool = False) -> list[str]:
    """The command that upgrades civex for *installer*.

    Falls back to pip inside this environment when the installer's own CLI
    isn't on PATH (pip is always present in a pipx venv; uv tool venvs may
    not have it, so that case is reported by `why_not` instead).
    """
    if installer == "app":
        # As the launcher upgrades it (`civex_launcher.upgrade_command`).
        uv = app_uv()
        return [
            str(uv or "uv"),
            "tool",
            "upgrade",
            *(["--prerelease", "allow"] if pre else []),
            "civex",
        ]
    if installer == "pipx" and shutil.which("pipx"):
        return ["pipx", "upgrade", *(["--pip-args=--pre"] if pre else []), "civex"]
    if installer == "uv" and shutil.which("uv"):
        return [
            "uv",
            "tool",
            "upgrade",
            *(["--prerelease", "allow"] if pre else []),
            "civex",
        ]
    return [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        *(["--pre"] if pre else []),
        "civex",
    ]


def upgrade_env(installer: str) -> dict[str, str] | None:
    """The environment the upgrade command runs with; None: this one."""
    return app_uv_env() if installer == "app" else None


def why_not(installer: str, *, from_app: bool) -> str:
    """Why this copy can't update itself, in plain words; blank when it can.
    `from_app` is the app's Update button, which also has to start civex
    again afterwards."""
    if installer == "editable":
        return "This is a development (editable) install: update it with git and `uv sync`."
    if installer == "frozen":
        return (
            "This copy of the desktop app can't update itself. Download the "
            "current desktop app, which keeps itself up to date."
        )
    if installer == "app":
        if app_uv() is None:
            return (
                "This is the desktop app's copy of civex, and its uv can't be "
                "found. Update it from the app (Settings > Updates)."
            )
        if app_is_open():
            return (
                "The desktop app is open and using this copy of civex: close it "
                "first, or update from the app (Settings > Updates)."
            )
    if installer == "uv" and not shutil.which("uv"):
        return "civex was installed with uv, but `uv` isn't on PATH here."
    if from_app and installer != "desktop":
        if os.environ.get("CIVEX_ALLOW_REMOTE"):
            return (
                "This server is open to other computers (--allow-remote), so "
                "it isn't updated from the browser. Run `civex update` on it."
            )
        if SERVE_ARGS_ENV not in os.environ:
            return (
                "civex wasn't started with `civex serve`, so it can't start "
                "itself again. Run `civex update`, then start it again."
            )
    return ""


# -- Checking ----------------------------------------------------------------


@dataclass(frozen=True)
class UpdateCheck:
    current: str
    #: None when PyPI couldn't be asked (then `error` says why).
    latest: str | None
    newer: bool
    pre: bool
    installer: str
    #: Why the app can't update this copy; blank when it can.
    blocked: str
    error: str
    #: The outcome of the last update from the app, if one has been tried.
    last: dict[str, Any] | None


def check(pre: bool = False, fetch: Callable[[bool], str] | None = None) -> UpdateCheck:
    """Whether a newer civex is available, and whether the app can install it."""
    from packaging.version import InvalidVersion, Version

    installer = detect_installer()
    latest: str | None = None
    newer, error = False, ""
    try:
        latest = (fetch or (lambda p: latest_version(pre=p)))(pre)
        newer = Version(latest) > Version(__version__)
    except (urllib.error.URLError, TimeoutError, OSError, KeyError, ValueError) as e:
        error = f"Couldn't ask PyPI for the latest version: {e}"
    except InvalidVersion:
        newer = latest is not None  # a local build: let the installer decide
    return UpdateCheck(
        current=__version__,
        latest=latest,
        newer=newer,
        pre=pre,
        installer=installer,
        blocked=why_not(installer, from_app=True),
        error=error,
        last=last_result(),
    )


# -- Updating after civex exits ----------------------------------------------


def result_path() -> Path:
    """Where the outcome of an update from the app is written (beside the
    per-user state, never in a project)."""
    from civex.user_state import state_path

    return state_path().parent / "update-result.json"


def last_result() -> dict[str, Any] | None:
    try:
        data = json.loads(result_path().read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


_quit_app: Callable[[], None] | None = None


def on_quit_for_update(quit_app: Callable[[], None]) -> None:
    """The desktop app registers how to close itself, so the launcher can
    update it."""
    global _quit_app
    _quit_app = quit_app


def restart_args(argv: list[str]) -> list[str]:
    """`civex serve` arguments to start it again with: the same, but without
    opening another browser tab (the open one reloads by itself)."""
    return [a for a in argv if a != "--open"]


def begin(pre: bool) -> Callable[[], None]:
    """Hand the update over to what runs after civex exits, and return how to
    exit (the caller does that once its answer is sent). Raises RuntimeError
    when this copy can't be updated from the app."""
    installer = detect_installer()
    reason = why_not(installer, from_app=True)
    if reason:
        raise RuntimeError(reason)
    attempt = {"from": __version__, "pre": pre, "result": str(result_path())}
    if installer == "desktop":
        if _quit_app is None:
            raise RuntimeError("The desktop app can't be closed from here.")
        # The project open now, so the launcher reopens it afterwards.
        attempt["project"] = os.getcwd()
        Path(os.environ[REQUEST_ENV]).write_text(json.dumps(attempt), "utf-8")
        return _quit_app
    _start_helper(
        {
            **attempt,
            "wait_pid": os.getpid(),
            "upgrade": upgrade_command(installer, pre=pre),
            "env": upgrade_env(installer),
            "version": [sys.executable, "-c", _VERSION_SNIPPET],
            "restart": [
                sys.executable,
                "-m",
                "civex.main",
                *restart_args(json.loads(os.environ[SERVE_ARGS_ENV])),
            ],
            "cwd": os.getcwd(),
            "log": str(result_path().with_name("update.log")),
        }
    )
    return _stop_server


def update_after_exit(pre: bool) -> None:
    """`civex update` on the desktop app's copy on Windows: the upgrade can't
    replace the files this very command runs from, so the helper does it once
    this process has exited, in the same terminal, and says how it went."""
    _start_helper(
        {
            "from": __version__,
            "pre": pre,
            "result": str(result_path()),
            "wait_pid": os.getpid(),
            "upgrade": upgrade_command("app", pre=pre),
            "env": upgrade_env("app"),
            "version": [sys.executable, "-c", _VERSION_SNIPPET],
            "restart": None,
            "log": str(result_path().with_name("update.log")),
        },
        attached=True,
    )


def _start_helper(plan: dict[str, Any], attached: bool = False) -> None:
    """Copy the helper out of the package it will replace and start it on its
    own, so it outlives this process. `attached`: in this terminal, its
    output shown there (`civex update`), rather than detached into the log."""
    workdir = Path(tempfile.mkdtemp(prefix="civex-update-"))
    helper = workdir / "civex_update_helper.py"
    shutil.copyfile(Path(__file__).with_name("_update_helper.py"), helper)
    (workdir / "plan.json").write_text(json.dumps(plan), "utf-8")
    Path(plan["log"]).parent.mkdir(parents=True, exist_ok=True)
    # The base interpreter, not this environment's: a running python.exe
    # inside the environment would stop the upgrade on Windows.
    python = getattr(sys, "_base_executable", None) or sys.executable
    kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "close_fds": True}
    if attached:
        subprocess.Popen(
            [python, "-I", str(helper), str(workdir / "plan.json")], **kwargs
        )
        return
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        )
    else:
        kwargs["start_new_session"] = True
    with open(plan["log"], "a", encoding="utf-8") as log:
        subprocess.Popen(
            [python, "-I", str(helper), str(workdir / "plan.json")],
            stdout=log,
            stderr=subprocess.STDOUT,
            **kwargs,
        )


def _stop_server() -> None:
    """Stop `civex serve` the way Ctrl+C does, and for good if a connection
    keeps it from stopping."""
    import signal
    import threading

    def _force() -> None:
        time.sleep(15)
        os._exit(0)

    threading.Thread(target=_force, daemon=True).start()
    signal.raise_signal(signal.SIGINT)
