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
    with urllib.request.urlopen(_PYPI_URL, timeout=timeout) as resp:  # noqa: S310
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


def detect_installer() -> str:
    """How this civex was installed: ``desktop`` (the desktop launcher) |
    ``frozen`` (an old all-in-one desktop build) | ``editable`` | ``pipx`` |
    ``uv`` | ``pip``."""
    if os.environ.get(REQUEST_ENV):
        return "desktop"
    if getattr(sys, "frozen", False):
        return "frozen"
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


def _start_helper(plan: dict[str, Any]) -> None:
    """Copy the helper out of the package it will replace and start it on its
    own, so it outlives this process."""
    workdir = Path(tempfile.mkdtemp(prefix="civex-update-"))
    helper = workdir / "civex_update_helper.py"
    shutil.copyfile(Path(__file__).with_name("_update_helper.py"), helper)
    (workdir / "plan.json").write_text(json.dumps(plan), "utf-8")
    Path(plan["log"]).parent.mkdir(parents=True, exist_ok=True)
    # The base interpreter, not this environment's: a running python.exe
    # inside the environment would stop the upgrade on Windows.
    python = getattr(sys, "_base_executable", None) or sys.executable
    kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "close_fds": True}
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
