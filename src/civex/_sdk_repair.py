"""One-time self-repair for upgrades from civex <= 1.0.6.

Those releases shipped ``civex_plugin_sdk`` *inside* the civex wheel. Since
then the SDK is its own PyPI package that civex depends on. When pip upgrades
across that change it installs the new SDK first, then uninstalls the old
civex -- whose file list still includes the ``civex_plugin_sdk/`` paths -- and
so deletes the SDK it just installed. The SDK's metadata survives, so
``pip check`` is happy, but ``import civex_plugin_sdk`` fails.

The signature is exact: distribution metadata present, module missing. Fresh
installs and every later upgrade never match it. A forced no-deps reinstall of
the same version restores the files. Nothing here may raise: this runs on
``import civex``, and a failed repair must not make the CLI worse than it
already was.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version

_DIST = "civex-plugin-sdk"
_MODULE = "civex_plugin_sdk"


def _needs_repair() -> str | None:
    """The SDK version whose files are missing, or None if nothing's wrong."""
    if importlib.util.find_spec(_MODULE) is not None:
        return None
    try:
        return version(_DIST)
    except PackageNotFoundError:
        return None  # not this situation; leave it alone


def _install_commands(sdk_version: str) -> list[list[str]]:
    spec = f"{_DIST}=={sdk_version}"
    commands = [
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--force-reinstall",
            "--no-deps",
            "--quiet",
            spec,
        ]
    ]
    uv = shutil.which("uv")
    if uv:  # uv-managed tool environments have no pip
        commands.append(
            [uv, "pip", "install", "--python", sys.executable, "--reinstall", spec]
        )
    return commands


def repair_sdk_if_needed() -> bool:
    """Restore the SDK's files if the upgrade deleted them. True if repaired."""
    try:
        sdk_version = _needs_repair()
        if sdk_version is None:
            return False
        print(
            f"civex: restoring {_DIST} {sdk_version} (one-time repair after "
            "upgrading from civex 1.0.6 or earlier)...",
            file=sys.stderr,
        )
        for cmd in _install_commands(sdk_version):
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0 and _needs_repair() is None:
                return True
        print(
            f"civex: couldn't restore {_DIST} automatically. Run: "
            f"pip install --force-reinstall --no-deps {_DIST}=={sdk_version}",
            file=sys.stderr,
        )
    except Exception:  # noqa: BLE001 -- never break `import civex`
        pass
    return False
