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
    assert ran and ran[0][-3:] == ["install", "--upgrade", "civex>=1.3.0"]


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
    # The pre-release named, not --pre: that would let in pre-releases of
    # everything civex depends on.
    assert ran[0][-3:] == ["install", "--upgrade", "civex>=1.3.0rc1"]
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
    # Naming the version lets a pre-release of civex in, and nothing else's.
    assert update_mod.upgrade_command("uv", pre=True, target="1.3.0rc1") == [
        "uv",
        "tool",
        "install",
        "--force",
        "civex>=1.3.0rc1",
    ]
    assert update_mod.upgrade_command("uv", pre=True) == ["uv", "tool", "upgrade", "civex"]


def test_a_uv_install_keeps_its_extras(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from civex import updates

    (tmp_path / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [{ name = "civex", extras = ["server", "ai"], '
        'specifier = ">=2.0.0" }]\n'
    )
    monkeypatch.setattr(updates.sys, "prefix", str(tmp_path))
    monkeypatch.setattr(update_mod.shutil, "which", lambda name: "/usr/bin/" + name)
    assert update_mod.upgrade_command("uv", target="2.0.1")[-1] == "civex[server,ai]>=2.0.1"


def test_repairing_a_uv_install_does_not_pin_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """uv keeps a tool to the requirement it was installed with, so a repair
    with `==` would stop every later update."""
    monkeypatch.setattr(update_mod.shutil, "which", lambda name: "/usr/bin/" + name)
    cmd = update_mod.repair_command("uv", "1.3.0rc1")
    assert cmd[-1] == "civex>=1.3.0rc1" and "--reinstall" in cmd


# -- The desktop app's copy, run from a terminal ------------------------------


@pytest.fixture
def app_copy(monkeypatch: pytest.MonkeyPatch, tmp_path):
    from civex import updates

    home = tmp_path / "app"
    uv = tmp_path / "Programs" / "civex" / "uv.exe"
    uv.parent.mkdir(parents=True)
    uv.write_text("")
    home.mkdir()
    (home / "launcher.json").write_text(f'{{"uv": "{uv.as_posix()}"}}')
    monkeypatch.setenv("CIVEX_APP_HOME", str(home))
    monkeypatch.delenv("CIVEX_UV_BIN", raising=False)
    monkeypatch.setattr(update_mod, "detect_installer", lambda: "app")
    monkeypatch.setattr(updates, "app_is_open", lambda: False)
    monkeypatch.setattr(update_mod, "__version__", "2.0.0rc4")
    monkeypatch.setattr(update_mod, "latest_version", lambda pre=False: "2.0.0rc5")
    return home, uv


def test_the_app_copy_updates_with_its_uv_and_its_folders(
    monkeypatch: pytest.MonkeyPatch, app_copy
) -> None:
    home, uv = app_copy
    monkeypatch.setattr(update_mod.sys, "platform", "linux")

    class _Done:
        returncode = 0

    ran: list[tuple[list[str], dict]] = []
    monkeypatch.setattr(
        update_mod.subprocess,
        "run",
        lambda cmd, env=None: ran.append((cmd, env)) or _Done(),
    )
    monkeypatch.setattr(update_mod, "installed_version", lambda pre=False: "2.0.0rc5")
    result = runner.invoke(app, ["update", "--pre"])
    assert result.exit_code == 0, result.output
    [(cmd, env)] = ran
    assert cmd == [str(uv), "tool", "install", "--force", "civex[desktop]>=2.0.0rc5"]
    assert env["UV_TOOL_DIR"] == str(home / "tools")
    assert env["UV_TOOL_BIN_DIR"] == str(home / "bin")
    assert env["UV_PYTHON_PREFERENCE"] == "only-managed"


def test_on_windows_the_app_copy_is_updated_after_the_command_exits(
    monkeypatch: pytest.MonkeyPatch, app_copy
) -> None:
    monkeypatch.setattr(update_mod.sys, "platform", "win32")
    handed: list[tuple] = []
    monkeypatch.setattr(
        update_mod,
        "update_after_exit",
        lambda pre, target, stopped: handed.append((pre, target, stopped)),
    )
    monkeypatch.setattr(
        update_mod.subprocess, "run", lambda *a, **k: pytest.fail("ran in-process")
    )
    result = runner.invoke(app, ["update", "--pre"])
    assert result.exit_code == 0, result.output
    assert handed == [(True, "2.0.0rc5", [])]
    assert "as soon as this command has finished" in result.output


def test_the_app_copy_is_not_updated_while_the_app_is_open(
    monkeypatch: pytest.MonkeyPatch, app_copy
) -> None:
    from civex import updates

    monkeypatch.setattr(updates, "app_is_open", lambda: True)
    result = runner.invoke(app, ["update"])
    assert result.exit_code == 1
    assert "close it first" in result.output
    # --check still says what is there.
    result = runner.invoke(app, ["update", "--check", "--pre"])
    assert "2.0.0rc5 is available" in result.output
