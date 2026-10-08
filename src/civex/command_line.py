"""Whether the desktop app's civex can be typed in a terminal: putting the
`civex` command the desktop app installed on the person's PATH, and taking it
off again. The one rule behind Settings > Updates (Command line) and, on
Windows, the installer's "Add the civex command to PATH" option, which writes
the same PATH entry this reads.

Only the desktop app's copy needs this: a uv, pipx or pip install is already
on PATH. Nothing is stored: the state is read from where it lives each time
(the user's PATH on Windows, the link on macOS and Linux).

- Windows: the app's `bin` folder in the *user* PATH (HKCU\\Environment, no
  administrator), then the change is announced so new terminals see it.
- macOS and Linux: a link `~/.local/bin/civex` to the app's `civex`, where uv
  puts commands too.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from civex.updates import app_home, detect_installer

EXE = ".exe" if sys.platform == "win32" else ""


@dataclass(frozen=True)
class CommandLineState:
    #: Whether this copy is the desktop app's (the only one this applies to).
    available: bool
    #: Whether a new terminal finds this copy's `civex` (on PATH, or linked).
    on_path: bool
    #: The folder (Windows) or link (macOS, Linux) that does it.
    where: str | None
    #: Another `civex` that a terminal would find first, if there is one.
    shadowed_by: str | None
    #: What a person still has to do, or why it can't be done; blank if nothing.
    note: str


def app_bin() -> Path | None:
    """The desktop app's command folder (where its `civex` is), or None when
    this isn't the desktop app's copy. The launcher sets UV_TOOL_BIN_DIR to it;
    run from a terminal, it is the bin folder in the app's own folder."""
    if detect_installer() not in ("desktop", "app"):
        return None
    folder = os.environ.get("UV_TOOL_BIN_DIR")
    return Path(folder) if folder else app_home() / "bin"


def _link() -> Path:
    return Path.home() / ".local" / "bin" / "civex"


# -- Windows: the user PATH ----------------------------------------------------


def _winreg() -> Any:
    """The Windows registry module (it exists only there, where this runs)."""
    import importlib

    return importlib.import_module("winreg")


def _user_path() -> list[str]:
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, "Path")
    except FileNotFoundError:
        return []
    return [p for p in str(value).split(";") if p]


def _set_user_path(entries: list[str]) -> None:
    import ctypes

    winreg = _winreg()
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, ";".join(entries))
    # Tell Explorer, so terminals opened from now on get the new PATH.
    hwnd_broadcast, wm_settingchange, abort_if_hung = 0xFFFF, 0x001A, 0x0002
    ctypes.windll.user32.SendMessageTimeoutW(  # type: ignore[attr-defined]
        hwnd_broadcast, wm_settingchange, 0, "Environment", abort_if_hung, 5000, None
    )


def _same(a: str, b: Path) -> bool:
    return os.path.normcase(os.path.normpath(os.path.expandvars(a))) == (
        os.path.normcase(os.path.normpath(str(b)))
    )


# -- macOS and Linux: the shell's PATH -----------------------------------------


def _shell_path() -> list[str]:
    """The PATH a new terminal gets. An app opened from the Dock or a menu
    has a minimal one of its own, so ask the login shell."""
    shell = os.environ.get("SHELL") or "/bin/sh"
    try:
        result = subprocess.run(
            [shell, "-l", "-c", 'printf %s "$PATH"'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        found = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    except (OSError, subprocess.TimeoutExpired, IndexError):
        found = ""
    return (found or os.environ.get("PATH", "")).split(os.pathsep)


def _first_civex(path: list[str]) -> str | None:
    found = shutil.which("civex", path=os.pathsep.join(path))
    return found


# -- The state, and changing it ------------------------------------------------


def state() -> CommandLineState:
    bin_dir = app_bin()
    if bin_dir is None:
        return CommandLineState(
            available=False,
            on_path=False,
            where=None,
            shadowed_by=None,
            note="Only the desktop app's civex is added here; this one is "
            "already a command (it was installed with uv, pipx or pip).",
        )
    ours = bin_dir / f"civex{EXE}"
    if sys.platform == "win32":
        user = _user_path()
        on_path = any(_same(p, bin_dir) for p in user)
        machine = os.environ.get("PATH", "").split(os.pathsep)
        first = _first_civex([*user, *machine]) if on_path else None
        return CommandLineState(
            available=True,
            on_path=on_path,
            where=str(bin_dir),
            shadowed_by=_other(first, ours),
            note="Open a new terminal to use it." if on_path else "",
        )
    link = _link()
    on_path = link.is_symlink() and link.resolve() == ours.resolve()
    shell = _shell_path()
    note = ""
    if on_path and not any(_same(p, link.parent) for p in shell):
        note = f"Add {link.parent} to your shell's PATH to use it."
    first = _first_civex(shell) if on_path else None
    return CommandLineState(
        available=True,
        on_path=on_path,
        where=str(link),
        shadowed_by=_other(first, link),
        note=note,
    )


def _other(found: str | None, ours: Path) -> str | None:
    """`found`, when it is a civex other than this one."""
    if not found:
        return None
    try:
        if Path(found).resolve() == ours.resolve():
            return None
    except OSError:
        pass
    return found


class CommandLineError(RuntimeError):
    """Why the command couldn't be added or removed, in plain words."""


def add() -> CommandLineState:
    bin_dir = app_bin()
    if bin_dir is None:
        raise CommandLineError(state().note)
    if sys.platform == "win32":
        user = _user_path()
        if not any(_same(p, bin_dir) for p in user):
            _set_user_path([*user, str(bin_dir)])
        return state()
    link, ours = _link(), bin_dir / "civex"
    if link.exists() or link.is_symlink():
        if link.is_symlink() and link.resolve() == ours.resolve():
            return state()
        raise CommandLineError(
            f"{link} is already another civex. Remove it first to use this one."
        )
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(ours)
    return state()


def remove() -> CommandLineState:
    bin_dir = app_bin()
    if bin_dir is None:
        raise CommandLineError(state().note)
    if sys.platform == "win32":
        user = _user_path()
        kept = [p for p in user if not _same(p, bin_dir)]
        if kept != user:
            _set_user_path(kept)
        return state()
    link, ours = _link(), bin_dir / "civex"
    if link.is_symlink() and link.resolve() == ours.resolve():
        link.unlink()  # only ever our own link
    return state()
