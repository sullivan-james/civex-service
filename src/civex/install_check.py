"""Checks on the civex *installation* (not on a project's data).

Behind ``civex doctor`` and the warning ``civex update`` prints afterwards.
The common failures here have confusing symptoms: after an upgrade ``civex``
still runs the old version because another copy earlier on PATH shadows it, or
a custom plugin fails with a Python error that is really a broken environment.
Each check says what is wrong and what to do about it in plain words.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Status = Literal["ok", "warn", "fail"]

_VERSION_RE = re.compile(r"civex\s+(\S+)")


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    detail: str = ""
    fix: str = ""


def executables_on_path(name: str = "civex") -> list[Path]:
    """Every `name` a shell would find, in the order it would try them
    (like `where` on Windows or `which -a`), without duplicates."""
    dirs = [Path(d) for d in os.environ.get("PATH", "").split(os.pathsep) if d]
    if sys.platform == "win32":
        # cmd.exe looks in the current directory first.
        dirs.insert(0, Path.cwd())
        exts = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";")
        names = [name + e.lower() for e in exts if e]
    else:
        names = [name]
    found: list[Path] = []
    seen: set[str] = set()
    for directory in dirs:
        for candidate_name in names:
            candidate = directory / candidate_name
            try:
                if not candidate.is_file():
                    continue
                if sys.platform != "win32" and not os.access(candidate, os.X_OK):
                    continue
                key = os.path.normcase(os.path.realpath(candidate))
            except OSError:
                continue
            if key not in seen:
                seen.add(key)
                found.append(candidate)
    return found


def _version_of(executable: Path, timeout: float = 20.0) -> str | None:
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = _VERSION_RE.search(result.stdout or "")
    return match.group(1) if match else None


def check_shadowing(expected: str) -> Check:
    """Does typing `civex` run version `expected`?

    It doesn't when an older copy (a stray `pip install civex`, an old
    launcher) sits earlier on PATH than the one that was just installed.
    """
    name = "civex on PATH"
    candidates = executables_on_path("civex")
    if not candidates:
        return Check(
            name,
            "warn",
            "No `civex` command found on PATH.",
            "Run `pipx ensurepath`, then open a new terminal.",
        )
    first = candidates[0]
    version = _version_of(first)
    if version == expected:
        return Check(name, "ok", f"`civex` runs {first} (version {version}).")
    others = [str(c) for c in candidates[1:]]
    detail = (
        f"Typing `civex` runs {first}, which is version {version or 'unknown'}, "
        f"not {expected}."
    )
    if others:
        detail += " Other copies: " + ", ".join(others) + "."
    return Check(
        name,
        "warn",
        detail,
        f"Remove the old copy: if it came from pip, run "
        f"`python -m pip uninstall civex` with the Python it belongs to, "
        f"otherwise delete {first}. Then open a new terminal.",
    )


def check_uv() -> Check:
    from civex.domain.exceptions import ConfigError
    from civex.plugins.subprocess_runtime import find_uv_binary

    name = "uv (runs custom plugins)"
    try:
        return Check(name, "ok", find_uv_binary())
    except ConfigError:
        return Check(
            name,
            "warn",
            "`uv` was not found. Only custom plugins need it.",
            "Install it from https://docs.astral.sh/uv/ or set CIVEX_UV_BIN.",
        )


def check_plugin_sandbox() -> Check:
    """Start Python the way a custom plugin is started: through uv, in a
    scratch folder, with the restricted environment plugins get. Failures
    here (a missing interpreter, a damaged Python) are what a plugin would
    hit, shown without needing a plugin."""
    from civex.domain.exceptions import ConfigError
    from civex.plugins.subprocess_runtime import find_uv_binary, sandboxed_env

    name = "plugin environment"
    try:
        uv = find_uv_binary()
    except ConfigError:
        return Check(name, "warn", "Skipped: uv was not found.")
    with tempfile.TemporaryDirectory(prefix="civex-doctor-") as scratch:
        try:
            result = subprocess.run(
                [uv, "run", "--no-project", "python", "-c", "import locale, sys"],
                cwd=scratch,
                env=sandboxed_env(),
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return Check(
                name,
                "fail",
                "Starting a plugin's Python took more than two minutes.",
                "Check your network (uv may be downloading Python) and try again.",
            )
        except OSError as e:
            return Check(name, "fail", f"Couldn't start uv: {e}")
    if result.returncode == 0:
        return Check(name, "ok", "A plugin's Python starts.")
    lines = [ln for ln in (result.stderr or "").strip().splitlines() if ln.strip()]
    return Check(
        name,
        "fail",
        lines[-1] if lines else f"uv exited with code {result.returncode}.",
        "Custom plugins won't run. Repair or reinstall Python (on Windows: "
        "`py install --force 3.14`), then run `uv cache clean`.",
    )


def missing_requirements() -> list[str]:
    """Declared dependencies of the installed civex that aren't installed (or
    are at a version civex doesn't allow). Optional extras are not counted.
    Read from package metadata, so it reflects what is on disk now."""
    from importlib.metadata import PackageNotFoundError, requires, version

    from packaging.requirements import Requirement

    problems: list[str] = []
    for line in requires("civex") or []:
        req = Requirement(line)
        if req.marker is not None and not req.marker.evaluate({"extra": ""}):
            continue
        try:
            installed = version(req.name)
        except PackageNotFoundError:
            problems.append(str(req))
            continue
        if req.specifier and not req.specifier.contains(installed, prereleases=True):
            problems.append(f"{req} (found {installed})")
    return problems


def check_dependencies() -> Check:
    name = "required packages"
    try:
        missing = missing_requirements()
    except Exception as e:  # metadata unreadable: say so rather than crash
        return Check(name, "warn", f"Couldn't read civex's requirements: {e}")
    if not missing:
        return Check(name, "ok", "Everything civex needs is installed.")
    return Check(
        name,
        "fail",
        "Missing or wrong version: " + ", ".join(missing) + ".",
        "Run `civex update` to reinstall them.",
    )


_PYTHON_NAMES = ("python.exe", "python", "python3", "pypy3", "pypy")


def uv_cache_dir() -> Path | None:
    """Where uv keeps the environments it builds for plugins, asked of uv
    itself and with the environment a plugin gets, so it is the same place."""
    from civex.domain.exceptions import ConfigError
    from civex.plugins.subprocess_runtime import find_uv_binary, sandboxed_env

    try:
        result = subprocess.run(
            [find_uv_binary(), "cache", "dir"],
            env=sandboxed_env(),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (ConfigError, OSError, subprocess.SubprocessError):
        return None
    out = result.stdout.strip()
    return Path(out) if result.returncode == 0 and out else None


def _venv_home(config: Path) -> Path | None:
    try:
        for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "home" and value.strip():
                return Path(value.strip())
    except OSError:
        pass
    return None


def stale_environments(cache_dir: Path) -> list[Path]:
    """Cached plugin environments whose Python is gone.

    uv reuses the environment it built for a plugin's dependencies. One built
    while its interpreter lived somewhere that has since disappeared (a
    temporary folder, an uninstalled Python) fails on every later run with
    "did not find executable at ...", and uv never rebuilds it on its own."""
    envs = cache_dir / "environments-v2"
    if not envs.is_dir():
        return []
    stale: list[Path] = []
    for env in sorted(envs.iterdir()):
        config = env / "pyvenv.cfg"
        if not config.is_file():
            continue
        home = _venv_home(config)
        if home is None:
            continue
        if not any((home / name).is_file() for name in _PYTHON_NAMES):
            stale.append(env)
    return stale


def remove_stale_environments(cache_dir: Path | None = None) -> list[Path]:
    """Delete the stale environments `stale_environments` finds; they are
    rebuilt the next time their plugin runs. Returns what was removed."""
    import shutil

    cache_dir = cache_dir or uv_cache_dir()
    if cache_dir is None:
        return []
    removed: list[Path] = []
    for env in stale_environments(cache_dir):
        shutil.rmtree(env, ignore_errors=True)
        if not env.exists():
            removed.append(env)
    return removed


def check_stale_environments() -> Check:
    name = "cached plugin environments"
    cache_dir = uv_cache_dir()
    if cache_dir is None:
        return Check(name, "warn", "Skipped: couldn't find uv's cache.")
    stale = stale_environments(cache_dir)
    if not stale:
        return Check(name, "ok", "None are out of date.")
    return Check(
        name,
        "warn",
        f"{len(stale)} point at a Python that no longer exists, so the plugins "
        'that use them fail with "did not find executable".',
        "Run `civex doctor --fix` to remove them; they are rebuilt on next use.",
    )


def run_install_checks() -> list[Check]:
    from civex import __version__

    checks = [check_shadowing(__version__), check_dependencies(), check_uv()]
    if checks[-1].status == "ok":
        checks.append(check_plugin_sandbox())
        checks.append(check_stale_environments())
    return checks
