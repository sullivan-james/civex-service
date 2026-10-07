from __future__ import annotations

import pytest
from typer.testing import CliRunner

from civex.cli import update as update_mod
from civex.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _not_editable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_mod, "detect_installer", lambda: "pip")
    monkeypatch.setattr(update_mod, "installed_missing_requirements", lambda: [])
    monkeypatch.setattr(update_mod, "_warn_if_shadowed", lambda expected: None)


def test_up_to_date(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_mod, "__version__", "1.2.0")
    monkeypatch.setattr(update_mod, "latest_version", lambda pre=False: "1.2.0")
    result = runner.invoke(app, ["update"])
    assert result.exit_code == 0
    assert "up to date" in result.output


def test_check_reports_newer_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_mod, "__version__", "1.2.0")
    monkeypatch.setattr(update_mod, "latest_version", lambda pre=False: "1.3.0")
    ran: list[list[str]] = []
    monkeypatch.setattr(update_mod.subprocess, "run", lambda cmd: ran.append(cmd))
    result = runner.invoke(app, ["update", "--check"])
    assert result.exit_code == 1
    assert "1.3.0" in result.output
    assert not ran


def test_update_runs_installer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_mod, "__version__", "1.2.0")
    monkeypatch.setattr(update_mod, "latest_version", lambda pre=False: "1.3.0")

    class _Done:
        returncode = 0

    ran: list[list[str]] = []
    monkeypatch.setattr(
        update_mod.subprocess, "run", lambda cmd: ran.append(cmd) or _Done()
    )
    monkeypatch.setattr(update_mod, "installed_version", lambda pre=False: "1.3.0")
    result = runner.invoke(app, ["update"])
    assert result.exit_code == 0
    assert "Updated to 1.3.0" in result.output
    assert ran and ran[0][-3:] == ["install", "--upgrade", "civex"]


def test_update_detects_silent_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """pip exiting 0 without changing the installed version is a failure."""
    monkeypatch.setattr(update_mod, "__version__", "1.2.0")
    monkeypatch.setattr(update_mod, "latest_version", lambda pre=False: "1.3.0")

    class _Done:
        returncode = 0

    monkeypatch.setattr(update_mod.subprocess, "run", lambda cmd: _Done())
    monkeypatch.setattr(update_mod, "installed_version", lambda pre=False: "1.2.0")
    result = runner.invoke(app, ["update"])
    assert result.exit_code == 1
    assert "still 1.2.0" in result.output


def test_editable_install_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_mod, "detect_installer", lambda: "editable")
    result = runner.invoke(app, ["update"])
    assert result.exit_code == 1
    assert "editable" in result.output


def test_pipx_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_mod.shutil, "which", lambda name: "/usr/bin/" + name)
    assert update_mod.upgrade_command("pipx") == ["pipx", "upgrade", "civex"]
    assert update_mod.upgrade_command("uv") == ["uv", "tool", "upgrade", "civex"]


def test_update_reinstalls_when_requirements_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(update_mod, "__version__", "1.2.0")
    monkeypatch.setattr(update_mod, "latest_version", lambda pre=False: "1.2.0")
    states = iter([["pandas>=2"], []])
    monkeypatch.setattr(
        update_mod, "installed_missing_requirements", lambda: next(states)
    )
    ran: list[list[str]] = []
    monkeypatch.setattr(update_mod.subprocess, "run", lambda cmd: ran.append(cmd))
    result = runner.invoke(app, ["update"])
    assert result.exit_code == 0, result.output
    assert ran and ran[0][-1] == "civex==1.2.0"
    assert "pandas" in result.output


def test_update_fails_if_requirements_stay_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(update_mod, "__version__", "1.2.0")
    monkeypatch.setattr(update_mod, "latest_version", lambda pre=False: "1.2.0")
    monkeypatch.setattr(update_mod, "installed_missing_requirements", lambda: ["x"])
    monkeypatch.setattr(update_mod.subprocess, "run", lambda cmd: None)
    assert runner.invoke(app, ["update"]).exit_code == 1


def test_check_does_not_install_anything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_mod, "__version__", "1.2.0")
    monkeypatch.setattr(update_mod, "latest_version", lambda pre=False: "1.2.0")
    monkeypatch.setattr(update_mod, "installed_missing_requirements", lambda: ["x"])
    ran: list[list[str]] = []
    monkeypatch.setattr(update_mod.subprocess, "run", lambda cmd: ran.append(cmd))
    assert runner.invoke(app, ["update", "--check"]).exit_code == 0
    assert not ran


def test_newest_release_counts_pre_releases_but_not_yanked_or_empty() -> None:
    releases = {
        "1.2.0": [{"yanked": False}],
        "1.3.0rc1": [{"yanked": False}],
        "1.3.0rc2": [{"yanked": True}],
        "1.4.0": [],
        "not-a-version": [{"yanked": False}],
    }
    assert update_mod.newest_release(releases) == "1.3.0rc1"
    assert update_mod.newest_release({}) is None


def test_pre_asks_for_pre_releases_and_installs_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(update_mod, "__version__", "1.2.0")
    asked: list[bool] = []
    monkeypatch.setattr(
        update_mod,
        "latest_version",
        lambda pre=False: asked.append(pre) or ("1.3.0rc1" if pre else "1.2.0"),
    )

    class _Done:
        returncode = 0

    ran: list[list[str]] = []
    monkeypatch.setattr(
        update_mod.subprocess, "run", lambda cmd: ran.append(cmd) or _Done()
    )
    monkeypatch.setattr(update_mod, "installed_version", lambda: "1.3.0rc1")
    result = runner.invoke(app, ["update", "--pre"])
    assert result.exit_code == 0, result.output
    assert asked == [True]
    assert ran[0][-4:] == ["install", "--upgrade", "--pre", "civex"]
    assert "Updated to 1.3.0rc1" in result.output


def test_without_pre_a_pre_release_is_not_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(update_mod, "__version__", "1.3.0rc1")
    monkeypatch.setattr(update_mod, "latest_version", lambda pre=False: "1.2.0")
    result = runner.invoke(app, ["update"])
    assert result.exit_code == 0
    assert "up to date" in result.output
    assert "civex update --pre" in result.output


def test_pre_upgrade_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_mod.shutil, "which", lambda name: "/usr/bin/" + name)
    assert update_mod.upgrade_command("pipx", pre=True) == [
        "pipx",
        "upgrade",
        "--pip-args=--pre",
        "civex",
    ]
    assert update_mod.upgrade_command("uv", pre=True) == [
        "uv",
        "tool",
        "upgrade",
        "--prerelease",
        "allow",
        "civex",
    ]
