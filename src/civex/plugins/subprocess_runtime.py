"""The process side of the subprocess (Tier 1) launcher: finding uv and
building `uv run --no-project <plugin>.py`, the sandbox a plugin process
starts in (a throwaway working folder, a minimal environment, its own
process group, no console window), reading its stderr as it comes, and
stopping it. Driving the protocol is `runtime`'s, the same for every tier;
`launchers.UvLauncher` puts the two together, and `describe_plugin`/
`run_plugin` here are the short way to use it for one script.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import weakref
from collections import deque
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version as _dist_version
from pathlib import Path
from typing import Any, Callable, Iterator, TextIO

from civex_plugin_sdk.protocol import DescribeResult

from civex.domain.exceptions import ConfigError
from civex.plugins import runtime
from civex.plugins.base import StepResult, WorkflowContext
from civex.plugins.runtime import plugin_output
from civex.processes import new_group_kwargs, no_window_kwargs, terminate_tree

# -- uv / SDK resolution ------------------------------------------------------


def find_uv_binary() -> str:
    """CIVEX_UV_BIN (the desktop app's launcher sets it to the uv it carries),
    else `uv` on PATH. Raises ConfigError with an actionable message if
    neither is there."""
    env_override = os.environ.get("CIVEX_UV_BIN")
    if env_override:
        return env_override
    found = shutil.which("uv")
    if found:
        return found
    raise ConfigError(
        "No 'uv' binary found. Install uv (https://docs.astral.sh/uv/) or set "
        "CIVEX_UV_BIN to its path -- required to run custom (subprocess-tier) "
        "plugins."
    )


def _find_sdk_source() -> Path | None:
    """Walk up from this file looking for a sibling civex-plugin-sdk/ source
    directory -- true in this repo's own uv workspace checkout, absent in a
    real install."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "civex-plugin-sdk"
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return None


@lru_cache(maxsize=1)
def _sdk_find_links_dir() -> Path | None:
    """Only in a dev checkout: a directory holding a wheel freshly built from
    the sibling `civex-plugin-sdk/` source, so a plugin resolves the SDK being
    worked on (possibly unpublished) rather than whatever is on PyPI.

    In a real install this is None: `civex-plugin-sdk` is a published
    dependency of `civex`, so `uv run --no-project` resolves it from the index
    like any other package, and `_build_command` pins it to the version this
    install runs (see `_sdk_pin_version`)."""
    sdk_source = _find_sdk_source()
    if sdk_source is None:
        return None
    wheel_dir = Path(tempfile.mkdtemp(prefix="civex-plugin-sdk-wheel-"))
    subprocess.run(
        [find_uv_binary(), "build", "--wheel", "-o", str(wheel_dir), str(sdk_source)],
        check=True,
        capture_output=True,
        text=True,
    )
    return wheel_dir


def _local_sdk_version(wheel_dir: Path) -> str | None:
    """Version of the wheel `_sdk_find_links_dir` just built, read off its
    filename (`civex_plugin_sdk-<version>-py3-none-any.whl`)."""
    for wheel in sorted(wheel_dir.glob("civex_plugin_sdk-*.whl")):
        parts = wheel.name.split("-")
        if len(parts) > 1:
            return parts[1]
    return None


def _installed_sdk_version() -> str | None:
    """Version of the civex-plugin-sdk this host itself imports."""
    try:
        return _dist_version("civex-plugin-sdk")
    except PackageNotFoundError:
        return None


def _sdk_pin_version(find_links: Path | None) -> str | None:
    """The SDK version a plugin's environment must use: the freshly built
    dev wheel's, or -- in a real install -- the one this host imports."""
    if find_links is not None:
        return _local_sdk_version(find_links)
    return _installed_sdk_version()


def lockfile_of(plugin_path: Path) -> Path:
    """Where uv keeps a script's lockfile: beside it, `<name>.py.lock`."""
    return plugin_path.with_name(plugin_path.name + ".lock")


def _build_command(uv_bin: str, plugin_path: Path) -> list[str]:
    argv = [uv_bin, "run", "--no-project"]
    find_links = _sdk_find_links_dir()
    if find_links is None and lockfile_of(plugin_path).is_file():
        # Locked when it was saved (`lock_plugin`): uv runs what the lock
        # says without asking a package index (it relocks only if the
        # header's dependencies were edited since). Its SDK is the one it was
        # saved with; the protocol version agreed at `describe` is what keeps
        # that and this host compatible, so no pin is added and an update of
        # civex doesn't rebuild the plugin's environment.
        return [*argv, str(plugin_path)]
    if find_links is not None:
        argv += ["--find-links", str(find_links)]
    # Not locked: pin the SDK the *host* speaks. `uv run` caches a
    # per-script environment keyed on the requirements it was given, and a
    # plugin's own header asks for `civex-plugin-sdk` unpinned -- which
    # whatever version that cached environment already holds satisfies
    # forever. Naming the version makes it part of the cache key, so a new
    # SDK release re-resolves.
    version = _sdk_pin_version(find_links)
    if version is not None:
        argv += ["--with", f"civex-plugin-sdk=={version}"]
    argv.append(str(plugin_path))
    return argv


def lock_plugin(plugin_path: Path, timeout: float = 300.0) -> Path | None:
    """Write `plugin_path`'s lockfile (`uv lock --script`): the exact
    versions its header's dependencies resolve to now, so every later run
    uses those without asking a package index. Returns the lockfile, or None
    in a development checkout, where plugins resolve the SDK being worked on
    from a wheel built per process (a lock would name a file that goes)."""
    if _sdk_find_links_dir() is not None:
        return None
    result = subprocess.run(
        [find_uv_binary(), "lock", "--script", str(plugin_path)],
        cwd=str(plugin_path.parent),
        env=sandboxed_env(),
        capture_output=True,
        text=True,
        timeout=timeout,
        **no_window_kwargs(),
    )
    if result.returncode != 0:
        raise ConfigError(
            f"Couldn't lock {plugin_path.name}'s dependencies: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return lockfile_of(plugin_path)


# -- sandboxed spawn (CIVEX-139) ----------------------------------------------


def sandboxed_env() -> dict[str, str]:
    """Minimal environment for a plugin subprocess: PATH/HOME plus whatever a
    few uv/Python variables it needs, deliberately excluding the rest of
    civex-service's own process environment (DB URL, AI API keys, ...) so a
    plugin can't read ambient secrets it was never granted a capability
    for -- the same "no ambient access" principle as the sandboxed cwd
    below, just applied to env instead of the filesystem."""
    allowed = (
        "PATH",
        "HOME",
        "UV_CACHE_DIR",
        "UV_PYTHON",
        "UV_PYTHON_INSTALL_DIR",
        "UV_PYTHON_PREFERENCE",
        "UV_NATIVE_TLS",
        "TMPDIR",
        # Corporate networks: without these uv can't reach the package index.
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "SSL_CERT_FILE",
    )
    env = {k: os.environ[k] for k in allowed if k in os.environ}
    if sys.platform == "win32":
        # uv finds the interpreters the Python install manager put under
        # %LOCALAPPDATA%\Python. Without LOCALAPPDATA it resolves that
        # location relative to the scratch cwd and fails with "did not find
        # executable at ...\Temp\civex-plugin-...\Python\...".
        for k in (
            "SYSTEMROOT",
            "WINDIR",
            "COMSPEC",
            "PATHEXT",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "HOMEDRIVE",
            "HOMEPATH",
            "LOCALAPPDATA",
            "APPDATA",
            "PROGRAMDATA",
            "PROGRAMFILES",
            "PROGRAMFILES(X86)",
        ):
            if k in os.environ:
                env[k] = os.environ[k]
    return env


def _spawn(argv: list[str], scratch_dir: Path) -> subprocess.Popen:
    """cwd is a throwaway scratch dir, never `_civex/` or the project root --
    a plugin gets no ambient filesystem path into real project data, only
    what it fetches over the RPC capability calls it declared. The process
    (and anything uv itself spawns under it) gets its own process group, so a
    runaway/forked plugin can be killed as a unit (CIVEX-138) rather than
    leaving orphans behind, and no console window on Windows.

    stderr is read as it comes (`_StderrTail`): a process that lives for many
    runs would otherwise fill the pipe and stop, waiting for a reader."""
    proc = subprocess.Popen(
        argv,
        cwd=str(scratch_dir),
        env=sandboxed_env(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        **new_group_kwargs(),
    )
    _TAILS[proc] = _StderrTail(proc)
    return proc


class _StderrTail:
    """Reads a process's stderr on a thread of its own, keeping the last
    `LINES` lines for the message when the process dies."""

    LINES = 200

    def __init__(self, proc: subprocess.Popen) -> None:
        self._lines: deque[str] = deque(maxlen=self.LINES)
        self._done = threading.Event()
        #: Told each line as it comes, while a run is going on (`_relaying`).
        self.listener: Callable[[str], None] | None = None
        stream = proc.stderr
        if stream is None:
            self._done.set()
            return
        threading.Thread(
            target=self._read, args=(stream,), name="civex-plugin-stderr", daemon=True
        ).start()

    def _read(self, stream: TextIO) -> None:
        try:
            for line in stream:
                self._lines.append(line)
                listener = self.listener
                if listener is not None:
                    listener(line.rstrip("\n"))
        except (OSError, ValueError):
            pass  # closed under us: the process is being stopped
        finally:
            self._done.set()

    def text(self, wait: float = 1.0) -> str:
        """What the process wrote to stderr, once it has finished writing
        (waiting up to `wait` seconds for the end)."""
        self._done.wait(wait)
        return "".join(self._lines)


@contextlib.contextmanager
def _relaying(proc: subprocess.Popen) -> Iterator[None]:
    """While a run lasts, the plugin's stderr (warnings, `logging`, a
    traceback) goes to the run's log line by line, as its print()s do."""
    tail = _TAILS.get(proc)
    if tail is None:
        yield
        return
    tail.listener = lambda line: plugin_output.warning("│ %s", line)
    try:
        yield
    finally:
        tail.listener = None


_TAILS: weakref.WeakKeyDictionary[subprocess.Popen, _StderrTail] = (
    weakref.WeakKeyDictionary()
)


def _kill_process_group(proc: subprocess.Popen, grace_seconds: float = 2.0) -> None:
    terminate_tree(proc, grace_seconds)


def _ensure_terminated(
    proc: subprocess.Popen,
    grace_seconds: float = 2.0,
    kill: Callable[[], None] | None = None,
) -> None:
    """Best-effort cleanup after a run that already finished normally: close
    stdin so the plugin's serve_loop sees EOF and exits on its own, falling
    back to `kill` (default: the process group) if it doesn't."""
    if proc.poll() is not None:
        return
    try:
        if proc.stdin:
            proc.stdin.close()
    except Exception:
        pass
    try:
        proc.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    if kill is not None:
        kill()
    else:
        _kill_process_group(proc, grace_seconds=grace_seconds)


def _dead_process_message(proc: subprocess.Popen) -> str:
    stderr = ""
    tail = _TAILS.get(proc)
    if tail is not None:
        stderr = tail.text()
    elif proc.stderr is not None:
        try:
            stderr = proc.stderr.read()
        except Exception:
            stderr = ""
    detail = f": {stderr.strip()}" if stderr.strip() else ""
    message = (
        f"plugin process exited without a response (exit code {proc.poll()}){detail}"
    )
    if "did not find executable at" in stderr:
        # uv reuses a plugin's cached environment, and one built while its
        # Python was somewhere that has since gone points at nothing.
        message += (
            "\nThis plugin's cached environment points at a Python that no longer "
            "exists. Run `civex doctor --fix` to remove it; it is rebuilt on the "
            "next run."
        )
    return message


# -- entry points ----------------------------------------------------------------


def describe_plugin(plugin_path: Path, timeout: float = 20.0) -> DescribeResult:
    """Ask a plugin script to describe itself (`runtime.describe` with a
    `UvLauncher`). The process is kept, so the first run after discovery
    finds it started."""
    from civex.plugins.launchers import UvLauncher

    return runtime.describe(UvLauncher(plugin_path), timeout)


def run_plugin(
    plugin_path: Path,
    inputs: dict[str, Any],
    config: dict[str, Any],
    ctx: WorkflowContext,
    capabilities: list[str],
    timeout: float,
) -> StepResult:
    """Run one step of a plugin script (`runtime.run` with a `UvLauncher`)."""
    from civex.plugins.launchers import UvLauncher

    return runtime.run(
        UvLauncher(plugin_path), inputs, config, ctx, capabilities, timeout
    )
