"""A desktop shortcut that starts civex for a project and opens it.

The shortcut is a small file on the person's Desktop that runs
`civex serve --open` inside the project folder: a `.desktop` entry on Linux,
a `.command` script on macOS, a `.bat` file on Windows. It opens a terminal
window that shows the server's output; closing the window stops civex. If civex
is already running on the port, running the shortcut just opens the browser.

Nothing here touches the project's data or config.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from civex.domain.exceptions import ConfigError

DEFAULT_PORT = 8000


def _platform() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def desktop_dir() -> Path:
    """The person's Desktop folder, or ConfigError when there is none."""
    candidates: list[Path] = []
    if _platform() == "windows":
        candidates.append(Path(os.environ.get("USERPROFILE", Path.home())) / "Desktop")
    else:
        if _platform() == "linux":
            try:
                out = subprocess.run(
                    ["xdg-user-dir", "DESKTOP"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                ).stdout.strip()
                if out:
                    candidates.append(Path(out))
            except (OSError, subprocess.SubprocessError):
                pass
        candidates.append(Path.home() / "Desktop")
    for c in candidates:
        if c.is_dir():
            return c
    raise ConfigError("There is no Desktop folder to put a shortcut in.")


def _filename(project_root: Path) -> str:
    safe = re.sub(r'[\\/:*?"<>|]+', "-", project_root.name).strip() or "project"
    ext = {"linux": ".desktop", "macos": ".command", "windows": ".bat"}[_platform()]
    return f"Civex - {safe}{ext}"


def shortcut_path(project_root: Path) -> Path:
    return desktop_dir() / _filename(project_root)


def shortcut_exists(project_root: Path) -> bool:
    try:
        return shortcut_path(project_root).exists()
    except ConfigError:
        return False


def _command() -> list[str]:
    """How to run civex serve from this installation."""
    if getattr(sys, "frozen", False):  # a packaged app: its own executable
        return [sys.executable, "serve", "--open"]
    return [sys.executable, "-m", "civex.main", "serve", "--open"]


def _quoted(parts: list[str], style: str) -> str:
    if style == "windows":
        return " ".join(f'"{p}"' for p in parts)
    return " ".join(
        '"' + p.replace("\\", "\\\\").replace('"', '\\"') + '"' for p in parts
    )


def create_shortcut(project_root: Path) -> Path:
    """Write the shortcut for `project_root` and return where it is."""
    project_root = project_root.resolve()
    path = shortcut_path(project_root)
    kind = _platform()
    cmd = _quoted(_command(), kind)
    title = f"Civex - {project_root.name}"
    if kind == "linux":
        text = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={title}\n"
            "Comment=Start Civex for this project and open it in the browser\n"
            f"Path={project_root}\n"
            f"Exec={cmd}\n"
            "Terminal=true\n"
        )
    elif kind == "macos":
        text = f'#!/bin/bash\ncd "{project_root}" || exit 1\nexec {cmd}\n'
    else:
        text = f'@echo off\r\ncd /d "{project_root}"\r\n{cmd}\r\npause\r\n'
    path.write_text(text, encoding="utf-8", newline="")
    if kind != "windows":
        path.chmod(0o755)
    if kind == "linux":
        # GNOME will not run a launcher on the Desktop until it is trusted.
        try:
            subprocess.run(
                ["gio", "set", str(path), "metadata::trusted", "true"],
                capture_output=True,
                timeout=3,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    return path


def is_serving(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def open_when_ready(url: str, timeout: float = 30.0) -> None:
    """Open `url` in the browser as soon as the server answers (in the
    background, so the server can start meanwhile)."""

    def wait_then_open() -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(f"{url}/health", timeout=1).close()
                break
            except OSError:
                time.sleep(0.3)
        webbrowser.open(url)

    threading.Thread(target=wait_then_open, daemon=True).start()
