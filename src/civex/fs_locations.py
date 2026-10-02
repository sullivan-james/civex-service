"""Looking at the local filesystem on behalf of the volume pickers: the folders
inside a directory, the drives that are mounted (network ones included), and a
time limit for any call that could hang on a dead network mount. Read-only and
platform-aware, with no knowledge of civex's own configuration."""

from __future__ import annotations

import concurrent.futures
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar

# Filesystems that are never a place to keep files.
_PSEUDO_FS = frozenset(
    {
        "proc", "sysfs", "devtmpfs", "devpts", "tmpfs", "cgroup", "cgroup2",
        "overlay", "squashfs", "securityfs", "debugfs", "tracefs", "mqueue",
        "hugetlbfs", "pstore", "bpf", "configfs", "fusectl", "binfmt_misc",
        "autofs", "efivarfs", "rpc_pipefs", "nsfs", "ramfs", "selinuxfs",
        "fuse.gvfsd-fuse", "fuse.portal", "fuse.lxcfs", "devfs",
    }
)  # fmt: skip
# Filesystems that live on another machine. A network location can be slow and
# can stop answering, which is why every call that touches one is time-limited.
_NETWORK_FS = frozenset(
    {
        "nfs", "nfs4", "cifs", "smb", "smb3", "smbfs", "afpfs", "webdav", "davfs",
        "ceph", "glusterfs", "fuse.glusterfs", "fuse.sshfs", "fuse.rclone",
        "fuse.s3fs", "fuse.gcsfuse", "lustre", "ncpfs", "afs",
    }
)  # fmt: skip
# Mount points that belong to the operating system, not to the user.
_SYSTEM_PREFIXES = (
    "/proc", "/sys", "/dev", "/boot", "/snap", "/var/lib", "/var/snap", "/usr", "/etc",
    "/init", "/Docker", "/mnt/wsl", "/mnt/wslg",
)  # fmt: skip
_OPAQUE_NAME = re.compile(r"[0-9a-f]{32,}")  # container/bind-mount ids, not drives
_NETWORK_URL = re.compile(
    r"^(smb|cifs|nfs|afp|sftp|ssh|ftp|ftps|http|https|dav)s?://", re.IGNORECASE
)

MAX_ENTRIES = 1000
FS_TIMEOUT = 3.0  # seconds to wait on one filesystem call before giving up

T = TypeVar("T")


@dataclass(frozen=True)
class Mount:
    source: str  # a device, `server:/export`, or `//server/share`
    path: str
    fstype: str

    @property
    def network(self) -> bool:
        return self.fstype in _NETWORK_FS


@dataclass(frozen=True)
class Drive:
    label: str
    path: str
    network: bool = False
    source: str | None = None  # where a network drive really lives


class Unresponsive(Exception):
    """A filesystem call didn't answer in time -- typically a network mount
    whose server has gone away."""


_pool = concurrent.futures.ThreadPoolExecutor(
    max_workers=16, thread_name_prefix="civex-fs"
)
_pending: dict[str, concurrent.futures.Future[Any]] = {}
_pending_lock = threading.Lock()


def guarded(key: str, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a filesystem call that might block forever, with a time limit.

    A stat on a hung network mount never returns, and would otherwise freeze
    the request that made it. Raises `Unresponsive` after FS_TIMEOUT seconds;
    any other exception from `fn` (OSError and so on) is raised as usual.

    At most one call per `key` is ever outstanding: while an earlier call on the
    same location is still stuck, later ones fail at once instead of piling up
    blocked threads behind a dead mount."""
    with _pending_lock:
        stuck = _pending.get(key)
        if stuck is not None and not stuck.done():
            raise Unresponsive("an earlier request is still waiting for it")
        future = _pool.submit(fn, *args, **kwargs)
        _pending[key] = future
    try:
        return future.result(timeout=FS_TIMEOUT)
    except concurrent.futures.TimeoutError:
        raise Unresponsive(f"no answer after {FS_TIMEOUT:g}s") from None


def normalise(path: str) -> str:
    """An absolute, `~`-expanded, forward-slash path. Symlinks are kept (not
    resolved), so the picker shows the path the user navigated to."""
    expanded = os.path.expanduser(path.replace("\\", "/"))
    return os.path.normpath(os.path.abspath(expanded)).replace("\\", "/")


def nearest_existing(path: str) -> Path:
    probe = Path(path)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return probe


def disk_usage(path: str) -> tuple[int | None, int | None]:
    """(free, total) bytes of the disk holding `path`, or its nearest existing
    parent -- a folder that doesn't exist yet still lives on some disk."""
    try:
        usage = shutil.disk_usage(nearest_existing(path))
    except OSError:
        return None, None
    return usage.free, usage.total


def list_subdirectories(
    path: str, *, show_hidden: bool = False, limit: int = MAX_ENTRIES
) -> tuple[list[tuple[str, str]], bool]:
    """(name, path) of each folder directly inside `path`, sorted without
    regard to case, and whether the list was cut at `limit`. Raises
    FileNotFoundError, NotADirectoryError or PermissionError."""
    found: list[tuple[str, str]] = []
    with os.scandir(path) as it:
        for entry in it:
            if not show_hidden and entry.name.startswith("."):
                continue
            try:
                if not entry.is_dir():  # follows symlinks to folders
                    continue
            except OSError:
                continue
            found.append((entry.name, normalise(entry.path)))
    found.sort(key=lambda item: item[0].casefold())
    return found[:limit], len(found) > limit


# -- network addresses and mounts -------------------------------------------


def looks_like_network_address(raw: str) -> bool:
    """An address that names a share rather than a mounted folder (`smb://host/x`,
    or `//host/share` where that isn't a valid local path). Civex uses network
    drives the operating system has already mounted; it doesn't mount them."""
    text = raw.strip()
    if _NETWORK_URL.match(text):
        return True
    return sys.platform != "win32" and text.replace("\\", "/").startswith("//")


def all_mounts() -> list[Mount]:
    """Every mount the OS reports (best effort; empty if it can't tell)."""
    if sys.platform == "darwin":
        return _macos_mounts()
    if sys.platform == "win32":
        return []
    return _linux_mounts()


def is_network_path(path: str, mounts: list[Mount] | None = None) -> bool:
    """Whether `path` lives on a network filesystem: the innermost mount
    containing it is a network mount, or (Windows) it is a UNC path or on a
    mapped network drive."""
    if sys.platform == "win32":
        return _windows_is_network(path)
    best: Mount | None = None
    for mount in mounts if mounts is not None else all_mounts():
        base = mount.path.rstrip("/")
        if base == "" or path == base or path.startswith(base + "/"):
            if best is None or len(mount.path) >= len(best.path):
                best = mount
    return best is not None and best.network


def _windows_is_network(path: str) -> bool:
    if path.replace("\\", "/").startswith("//"):
        return True
    try:
        import ctypes

        root = os.path.splitdrive(path)[0] + "\\"
        return ctypes.windll.kernel32.GetDriveTypeW(root) == 4  # type: ignore[attr-defined]  # DRIVE_REMOTE
    except (AttributeError, OSError, ValueError):
        return False


def mounted_drives() -> list[Drive]:
    """Best-effort list of the drives and mounts a user might keep files on,
    network ones included."""
    if sys.platform == "win32":
        listdrives = getattr(os, "listdrives", None)  # Python 3.12+
        letters = list(listdrives()) if listdrives else []
        return [
            Drive(
                d.replace("\\", "/"),
                d.replace("\\", "/"),
                network=_windows_is_network(d),
            )
            for d in letters
        ]
    drives: dict[str, Drive] = {}
    for mount in all_mounts():
        if _is_system_mount(mount):
            continue
        drives.setdefault(
            mount.path,
            Drive(
                os.path.basename(mount.path.rstrip("/")) or mount.path,
                mount.path,
                network=mount.network,
                source=mount.source if mount.network else None,
            ),
        )
    return sorted(drives.values(), key=lambda d: d.path.casefold())


def _is_system_mount(mount: Mount) -> bool:
    if mount.path == "/" or mount.fstype in _PSEUDO_FS:
        return True
    if mount.path.startswith(_SYSTEM_PREFIXES):
        return True
    if mount.path.startswith("/run") and not mount.path.startswith("/run/media"):
        return True
    return bool(_OPAQUE_NAME.fullmatch(os.path.basename(mount.path)))


def _linux_mounts(mounts_file: str = "/proc/mounts") -> list[Mount]:
    try:
        lines = Path(mounts_file).read_text("utf-8", errors="replace").splitlines()
    except OSError:
        return []
    mounts = []
    for line in lines:
        parts = line.split()
        if len(parts) >= 3:
            mounts.append(Mount(parts[0], parts[1].replace("\\040", " "), parts[2]))
    return mounts


def _macos_mounts(output: str | None = None) -> list[Mount]:
    """Parse `mount` output: `//user@host/share on /Volumes/share (smbfs, ...)`."""
    if output is None:
        try:
            output = subprocess.run(
                ["/sbin/mount"], capture_output=True, text=True, timeout=2, check=False
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return []
    mounts = []
    for line in output.splitlines():
        match = re.match(r"^(.+?) on (.+?) \(([\w.]+)", line)
        if match:
            mounts.append(Mount(match[1], match[2], match[3]))
    return mounts
