"""Show a folder in the operating system's file manager.

Only meaningful when civex runs on the machine the person is sitting at: the
server asks for it when the request came from this machine (see the file-access
router). Returns whether a launcher was started, never raises, so a missing
desktop (a server over ssh) just means "couldn't open it here".
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def is_wsl() -> bool:
    """Running under WSL: Windows apps (Explorer, Raven) will see our files."""
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def open_folder(path: Path) -> bool:
    """Open `path` in the file manager. False if there is nothing to open it with."""
    target = str(path)
    try:
        if sys.platform == "win32":
            os.startfile(target)  # type: ignore[attr-defined]
            return True
        if sys.platform == "darwin":
            command = ["open", target]
        elif is_wsl() and shutil.which("explorer.exe") and shutil.which("wslpath"):
            windows_path = subprocess.run(
                ["wslpath", "-w", target], capture_output=True, text=True, timeout=10
            ).stdout.strip()
            if not windows_path:
                return False
            # explorer.exe exits non-zero even when it opened the folder, so the
            # launch itself is the only thing worth checking.
            subprocess.Popen(["explorer.exe", windows_path])
            return True
        elif shutil.which("xdg-open"):
            command = ["xdg-open", target]
        else:
            return False
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (OSError, subprocess.SubprocessError):
        return False
