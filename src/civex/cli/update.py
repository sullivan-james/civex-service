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

import typer

from civex import __version__
from civex.console import console

# The rules live in civex.updates, shared with the app's Updates page; these
# names are imported here so the command (and its tests) read them from one
# place.
from civex.updates import (
    app_uv,
    detect_installer,
    installed_version,
    is_prerelease,
    latest_version,
    newest_release,  # noqa: F401  (re-exported for callers of the old module)
    update_after_exit,
    upgrade_command,
    upgrade_env,
    why_not,
)


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


def _run(cmd: list[str], installer: str):  # noqa: ANN202 - CompletedProcess
    """Run an upgrade or repair, with the installer's own environment if it
    has one (the desktop app's copy: the app's folders)."""
    env = upgrade_env(installer)
    return subprocess.run(cmd, env=env) if env is not None else subprocess.run(cmd)


def repair_command(installer: str, version: str) -> list[str]:
    """Reinstall civex at `version`, which also installs any dependency that
    is missing (an upgrade alone doesn't when the version is unchanged).

    For uv, `>=` and not `==`: uv records the requirement a tool was installed
    with, and `uv tool upgrade` keeps to it, so `==` pinned the install and
    every later `civex update` quietly did nothing."""
    if installer == "uv" and shutil.which("uv"):
        return ["uv", "tool", "install", "--force", "--reinstall", f"civex>={version}"]
    if installer == "app":
        uv = app_uv()
        return [
            str(uv or "uv"),
            "tool",
            "install",
            "--force",
            "--reinstall",
            f"civex[desktop]>={version}",
        ]
    return [sys.executable, "-m", "pip", "install", f"civex=={version}"]


def ensure_requirements(installer: str, version: str) -> bool:
    """Make sure every package civex needs is installed, reinstalling if not.
    Returns False if some are still missing afterwards."""
    missing = installed_missing_requirements()
    if not missing:
        return True
    if installer == "app" and sys.platform == "win32":
        # Reinstalling would replace the files this command runs from.
        console.print(
            "[warning]Some packages civex needs are missing: "
            f"{', '.join(missing)}. Update from the desktop app (Settings > "
            "Updates) to put them back.[/warning]"
        )
        return False
    console.print(
        "[warning]Some packages civex needs are missing: "
        f"{', '.join(missing)}. Reinstalling.[/warning]"
    )
    cmd = repair_command(installer, version)
    console.print(f"[dim]{' '.join(cmd)}[/dim]")
    _run(cmd, installer)
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
    # A copy that can't update itself from here still says what is available.
    blocked = ""
    if installer in ("editable", "frozen", "desktop"):
        blocked = why_not(installer, from_app=False) or (
            "This is the desktop app's copy of civex: update it from the app "
            "(Settings > Updates)."
        )
    elif installer == "app":
        blocked = why_not(installer, from_app=False)
    if blocked:
        if not check:
            console.print(f"[warning]{blocked}[/warning]")
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
        if not pre and is_prerelease(__version__):
            console.print(
                "[dim]This is a pre-release; `civex update --pre` looks for "
                "newer pre-releases too.[/dim]"
            )
        if not check and not ensure_requirements(installer, __version__):
            raise typer.Exit(1)
        return
    if check:
        console.print(f"civex {latest} is available (you have {__version__}).")
        if blocked:
            console.print(blocked)
        else:
            command = "civex update --pre" if pre else "civex update"
            console.print(f"Run [cyan]{command}[/cyan] to install it.")
        raise typer.Exit(1)

    cmd = upgrade_command(installer, pre=pre)
    console.print(
        f"Updating civex {__version__} -> {latest}: [dim]{' '.join(cmd)}[/dim]"
    )
    if installer == "app" and sys.platform == "win32":
        # This command runs from the files the upgrade replaces, which Windows
        # won't let go while it runs: the helper does it once this has exited.
        update_after_exit(pre)
        console.print(
            "[dim]It runs as soon as this command has finished; this window "
            "shows how it went.[/dim]"
        )
        return
    result = _run(cmd, installer)
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
