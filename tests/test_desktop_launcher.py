"""desktop-launcher/civex_launcher.py: starting, updating and restarting the
desktop app. The install itself (uv from PyPI or a wheel) is exercised by the
release workflow on every OS; these hold the loop and its records."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "civex_launcher",
    Path(__file__).resolve().parent.parent / "desktop-launcher/civex_launcher.py",
)
assert _SPEC and _SPEC.loader
launcher = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(launcher)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CIVEX_APP_HOME", str(tmp_path / "app"))
    monkeypatch.setattr(launcher, "bundled_uv", lambda: Path("/bundled/uv"))
    monkeypatch.setattr(launcher, "ensure_installed", lambda *a: None)
    monkeypatch.setattr(launcher, "with_progress", lambda title, msg, work: work())
    return tmp_path / "app"


def test_everything_stays_in_the_launcher_s_own_folder(home: Path) -> None:
    env = launcher.environment(home, Path("/bundled/uv"))
    assert env["UV_TOOL_DIR"] == str(home / "tools")
    assert env["UV_PYTHON_INSTALL_DIR"] == str(home / "python")
    assert env["UV_PYTHON_PREFERENCE"] == "only-managed"
    assert env["CIVEX_UV_BIN"] == "/bundled/uv"


def test_upgrades_take_pre_releases_only_when_asked() -> None:
    uv = Path("/u/uv")
    assert launcher.upgrade_command(uv, pre=False) == [
        "/u/uv",
        "tool",
        "upgrade",
        "civex",
    ]
    assert "--prerelease" in launcher.upgrade_command(uv, pre=True)


def test_closing_the_app_ends_the_launcher(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[list[str]] = []
    monkeypatch.setattr(launcher, "run_app", lambda h, args, env: started.append(args))
    assert launcher.main([]) == 0
    assert started == [[]]


def test_an_update_request_upgrades_records_and_reopens_the_project(
    home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = tmp_path / "update-result.json"
    started: list[list[str]] = []

    def app(h: Path, args: list[str], env: dict[str, str]) -> None:
        started.append(args)
        if len(started) == 1:  # the first run asks for an update and closes
            Path(env[launcher.REQUEST_ENV]).write_text(
                json.dumps(
                    {
                        "from": "1.2.0",
                        "pre": True,
                        "result": str(result),
                        "project": "/p",
                    }
                )
            )

    ran: list[list[str]] = []
    monkeypatch.setattr(launcher, "run_app", app)
    monkeypatch.setattr(
        launcher, "run_logged", lambda cmd, env, log: ran.append(cmd) or 0
    )
    monkeypatch.setattr(launcher, "civex_version", lambda h, env: "1.3.0rc1")
    assert launcher.main([]) == 0
    assert started == [[], ["--project", "/p"]]
    assert ran == [["/bundled/uv", "tool", "upgrade", "--prerelease", "allow", "civex"]]
    record = json.loads(result.read_text())
    assert record["ok"] and (record["from"], record["to"]) == ("1.2.0", "1.3.0rc1")
    assert not (home / "update-request.json").exists()


@pytest.mark.parametrize(
    ("code", "after", "says"),
    [(1, "1.2.0", "The update failed"), (0, "1.2.0", "nothing newer")],
)
def test_a_failed_update_is_recorded_and_civex_opens_anyway(
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    code: int,
    after: str,
    says: str,
) -> None:
    result = tmp_path / "update-result.json"
    started: list[list[str]] = []

    def app(h: Path, args: list[str], env: dict[str, str]) -> None:
        started.append(args)
        if len(started) == 1:
            Path(env[launcher.REQUEST_ENV]).write_text(
                json.dumps({"from": "1.2.0", "result": str(result)})
            )

    monkeypatch.setattr(launcher, "run_app", app)
    monkeypatch.setattr(launcher, "run_logged", lambda cmd, env, log: code)
    monkeypatch.setattr(launcher, "civex_version", lambda h, env: after)
    assert launcher.main([]) == 0
    assert len(started) == 2
    record = json.loads(result.read_text())
    assert not record["ok"] and says in record["message"]


def test_a_broken_request_file_is_treated_as_a_plain_close(tmp_path: Path) -> None:
    path = tmp_path / "request.json"
    path.write_text("not json")
    assert launcher.take_request(path) is None
    assert not path.exists()


def test_a_built_app_never_borrows_a_uv_from_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A uv missing from the app went unnoticed on CI runners, which have
    one on PATH, and would have failed only on people's computers."""
    monkeypatch.setattr(launcher.sys, "frozen", True, raising=False)
    monkeypatch.setattr(launcher.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/uv")
    with pytest.raises(RuntimeError, match="missing its uv"):
        launcher.bundled_uv()
    inside = tmp_path / "uv" / f"uv{launcher.EXE}"
    inside.parent.mkdir()
    inside.touch()
    assert launcher.bundled_uv() == inside


def _released(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, version: str) -> None:
    (tmp_path / "civex_version.txt").write_text(version)
    monkeypatch.setattr(launcher.sys, "_MEIPASS", str(tmp_path), raising=False)


def test_it_installs_at_least_the_civex_it_was_released_with(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Plain civex[desktop] took the newest *stable* civex, so a release
    candidate's app installed an older one (v2.0.0rc1's got 1.2.0)."""
    monkeypatch.delenv("CIVEX_LAUNCHER_SOURCE", raising=False)
    monkeypatch.setattr(launcher.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert launcher.requirement() == "civex[desktop]"  # a dry run's app
    _released(monkeypatch, tmp_path, "2.0.0rc1")
    assert launcher.requirement() == "civex[desktop]>=2.0.0rc1"
    assert launcher.install_command(Path("/u/uv"))[-1] == "civex[desktop]>=2.0.0rc1"
    monkeypatch.setenv("CIVEX_LAUNCHER_SOURCE", "civex[desktop] @ file:///w.whl")
    assert launcher.install_command(Path("/u/uv"))[-1].endswith("w.whl")


@pytest.mark.parametrize(
    ("installed", "older", "installs"),
    [(None, False, True), ("1.2.0", True, True), ("2.0.0rc1", False, False)],
)
def test_a_newer_app_brings_an_older_civex_up_to_its_own(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    installed: str | None,
    older: bool,
    installs: bool,
) -> None:
    home = tmp_path / "app"
    if installed:
        launcher.desktop_app(home).parent.mkdir(parents=True)
        launcher.desktop_app(home).touch()
    monkeypatch.setattr(launcher, "civex_version", lambda h, env: installed)
    monkeypatch.setattr(launcher, "older_than_release", lambda h, env, v: older)
    monkeypatch.setattr(launcher, "with_progress", lambda title, msg, work: work())
    ran: list[list[str]] = []
    monkeypatch.setattr(
        launcher, "run_logged", lambda cmd, env, log: ran.append(cmd) or 0
    )
    launcher.ensure_installed(home, Path("/u/uv"), {}, tmp_path / "log")
    assert bool(ran) is installs


@pytest.mark.posix_only
def test_older_than_release_asks_the_installed_python(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _released(monkeypatch, tmp_path, "2.0.0rc1")
    home = tmp_path / "app"
    python = home / "tools" / "civex" / "bin" / "python"
    python.parent.mkdir(parents=True)
    # Stands in for the installed civex's Python, which has `packaging`.
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    python.chmod(0o755)
    env = dict(os.environ)
    assert launcher.older_than_release(home, env, "1.2.0")
    assert not launcher.older_than_release(home, env, "2.0.0rc1")
    assert not launcher.older_than_release(home, env, "2.0.0")


def test_the_window_is_civex_s_own_python_running_the_desktop_module(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No `civex-desktop` command (every install got one that only works with
    the desktop extra); on Windows pythonw, so no console window."""
    ran: list[list[str]] = []
    monkeypatch.setattr(launcher.subprocess, "run", lambda cmd, **kw: ran.append(cmd))
    launcher.run_app(tmp_path, ["--project", "/p"], {})
    python = ran[0][0]
    assert python.endswith("pythonw.exe" if sys.platform == "win32" else "bin/python")
    assert ran[0][1:] == ["-m", "civex.desktop.tray", "--project", "/p"]


def test_the_app_logs_beside_the_launcher(tmp_path: Path) -> None:
    env = launcher.environment(tmp_path, Path("/u/uv"))
    assert env["CIVEX_LOG_DIR"] == str(tmp_path / "logs")


def test_an_explicit_source_is_installed_even_over_an_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """How a test build's wheel is tried in its app: CIVEX_LAUNCHER_SOURCE."""
    home = tmp_path / "app"
    launcher.desktop_app(home).parent.mkdir(parents=True)
    launcher.desktop_app(home).touch()
    monkeypatch.setattr(launcher, "civex_version", lambda h, env: "1.2.0")
    monkeypatch.setattr(launcher, "older_than_release", lambda h, env, v: False)
    monkeypatch.setattr(launcher, "with_progress", lambda title, msg, work: work())
    ran: list[list[str]] = []
    monkeypatch.setattr(
        launcher, "run_logged", lambda cmd, env, log: ran.append(cmd) or 0
    )
    monkeypatch.setenv("CIVEX_LAUNCHER_SOURCE", "civex[desktop] @ file:///w.whl")
    launcher.ensure_installed(home, Path("/u/uv"), {}, tmp_path / "log")
    assert ran and ran[0][-1].endswith("w.whl")


def test_civex_knows_the_apps_folders_as_the_launcher_does(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`civex update` from a terminal updates the app's copy itself, so civex
    must find the app's folder and give uv the same folders the launcher does
    (it can't import the launcher, nor the launcher civex)."""
    from civex import updates

    monkeypatch.delenv("CIVEX_APP_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    assert updates.app_home() == launcher.app_home()
    monkeypatch.setenv("CIVEX_APP_HOME", str(tmp_path / "app"))
    home = launcher.app_home()
    assert updates.app_home() == home

    theirs = launcher.environment(home, Path("/bundled/uv"))
    ours = updates.app_uv_env()
    for name in (
        "UV_TOOL_DIR",
        "UV_TOOL_BIN_DIR",
        "UV_PYTHON_INSTALL_DIR",
        "UV_CACHE_DIR",
        "UV_PYTHON_PREFERENCE",
    ):
        assert ours[name] == theirs[name], name
    assert (
        updates.upgrade_command("app", pre=True)[1:]
        == launcher.upgrade_command(Path("/bundled/uv"), pre=True)[1:]
    )


def test_the_launcher_says_where_its_uv_is(home: Path) -> None:
    home.mkdir(parents=True)
    launcher.record_where(home, Path("/bundled/uv"))
    recorded = json.loads((home / "launcher.json").read_text())
    assert recorded["uv"] == str(Path("/bundled/uv"))
