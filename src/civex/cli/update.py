"""civex update -- upgrade this civex install to the latest release.

Deliberately doesn't require a civex project: it updates the software, not
project data. Project databases migrate themselves the next time they're
opened (see ``ensure_schema_current``), so there's nothing to run afterwards.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

import typer

from civex import __version__
from civex.console import console

_PYPI_URL = "https://pypi.org/pypi/civex/json"


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


def detect_installer() -> str:
    """How this civex was installed: ``pipx`` | ``uv`` | ``editable`` | ``pip``."""
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
        [
            sys.executable,
            "-c",
            "from importlib.metadata import version; print(version('civex'))",
        ],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or None if result.returncode == 0 else None


def upgrade_command(installer: str, pre: bool = False) -> list[str]:
    """The command that upgrades civex for *installer*.

    Falls back to pip inside this environment when the installer's own CLI
    isn't on PATH (pip is always present in a pipx venv; uv tool venvs may
    not have it, so that case is reported by the caller instead).
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


def installed_missing_requirements() -> list[str]:
    """What's missing for the civex installed *now*, from a fresh interpreter
    (this process still has the old code and metadata loaded)."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json; from civex.install_check import missing_requirements; "
            "print(json.dumps(missing_requirements()))",
        ],
        capture_output=True,
        text=True,
    )
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return []


def repair_command(installer: str, version: str) -> list[str]:
    """Reinstall civex at `version`, which also installs any dependency that
    is missing (an upgrade alone doesn't when the version is unchanged)."""
    if installer == "uv" and shutil.which("uv"):
        return ["uv", "tool", "install", "--force", f"civex=={version}"]
    return [sys.executable, "-m", "pip", "install", f"civex=={version}"]


def ensure_requirements(installer: str, version: str) -> bool:
    """Make sure every package civex needs is installed, reinstalling if not.
    Returns False if some are still missing afterwards."""
    missing = installed_missing_requirements()
    if not missing:
        return True
    console.print(
        "[warning]Some packages civex needs are missing: "
        f"{', '.join(missing)}. Reinstalling.[/warning]"
    )
    cmd = repair_command(installer, version)
    console.print(f"[dim]{' '.join(cmd)}[/dim]")
    subprocess.run(cmd)
    still = installed_missing_requirements()
    if still:
        console.print(
            f"[error]Still missing: {', '.join(still)}.[/error] "
            "Try `pip install civex` directly to see why."
        )
        return False
    console.print("[success]Required packages are installed.[/success]")
    return True


def update(
    check: bool = typer.Option(
        False, "--check", help="Only report whether a newer version exists."
    ),
    pre: bool = typer.Option(
        False,
        "--pre",
        help="Include pre-releases (release candidates, betas) when looking "
        "for a newer version.",
    ),
) -> None:
    """Update civex to the latest release.

    Detects whether civex was installed with pipx, uv tool or pip and runs the
    matching upgrade. Restart any running `civex serve` afterwards.

    Pre-releases are only installed with --pre. Once on one, a plain
    `civex update` moves on when the final release is out.
    """
    installer = detect_installer()
    if installer == "editable":
        console.print(
            "[warning]This is a development (editable) install -- update it "
            "with git and `uv sync` instead.[/warning]"
        )
        raise typer.Exit(1)

    # Imported here, not at module top: a stale environment missing this
    # dependency must not break every other civex command.
    from packaging.version import InvalidVersion, Version

    try:
        latest = latest_version(pre=pre)
        newer = Version(latest) > Version(__version__)
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
        console.print(f"[error]Couldn't check PyPI for updates: {e}[/error]")
        raise typer.Exit(1)
    except InvalidVersion:
        # Local build with a non-PEP-440 version: can't compare, so let the
        # installer decide.
        latest, newer = "unknown", True

    if not newer:
        console.print(f"[success]civex {__version__} is up to date.[/success]")
        if not pre and _is_prerelease(__version__):
            console.print(
                "[dim]This is a pre-release; `civex update --pre` looks for "
                "newer pre-releases too.[/dim]"
            )
        if not check and not ensure_requirements(installer, __version__):
            raise typer.Exit(1)
        return
    if check:
        console.print(f"civex {latest} is available (you have {__version__}).")
        command = "civex update --pre" if pre else "civex update"
        console.print(f"Run [cyan]{command}[/cyan] to install it.")
        raise typer.Exit(1)

    cmd = upgrade_command(installer, pre=pre)
    console.print(
        f"Updating civex {__version__} -> {latest}: [dim]{' '.join(cmd)}[/dim]"
    )
    result = subprocess.run(cmd)
    if result.returncode != 0:
        console.print("[error]Update failed -- see the output above.[/error]")
        raise typer.Exit(result.returncode)
    # pip can exit 0 yet leave the old version in place (it backtracks to an
    # older release when a newer one's dependencies won't resolve -- what
    # happened with v1.0.5), so confirm rather than trust the exit code.
    now = installed_version()
    if now == __version__:
        console.print(
            f"[error]The upgrade ran but civex is still {__version__}.[/error] "
            f"A dependency of {latest} may not install on this machine; try "
            "`pip install --upgrade civex` directly to see the reason."
        )
        raise typer.Exit(1)
    console.print(
        f"[success]Updated to {now or latest}.[/success] "
        "Restart `civex serve` if it's running."
    )
    ok = ensure_requirements(installer, now or latest)
    _warn_if_shadowed(now or latest)
    if not ok:
        raise typer.Exit(1)


def _is_prerelease(version: str) -> bool:
    from packaging.version import InvalidVersion, Version

    try:
        return Version(version).is_prerelease
    except InvalidVersion:
        return False


def _warn_if_shadowed(expected: str) -> None:
    """After an upgrade, say so if typing `civex` still runs another copy."""
    from civex.install_check import check_shadowing

    try:
        check = check_shadowing(expected)
    except Exception:  # a diagnostic must never fail a successful update
        return
    if check.status != "ok":
        console.print(f"[warning]{check.detail}[/warning]")
        console.print(f"[dim]{check.fix}[/dim]")
