from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


def test_status_says_so_when_not_following_an_authority(project_dir: Path) -> None:
    result = runner.invoke(app, ["sync", "status"])
    assert result.exit_code == 0, result.output
    assert "Not following" in result.output


def test_sync_now_without_an_authority_explains(project_dir: Path) -> None:
    result = runner.invoke(app, ["sync", "now"])
    assert result.exit_code == 1
    assert "civex sync connect" in result.output


def test_authority_devices_get_tokens_that_can_be_revoked(project_dir: Path) -> None:
    assert runner.invoke(app, ["sync", "authority", "enable"]).exit_code == 0
    added = runner.invoke(app, ["sync", "device", "add", "laptop"])
    assert added.exit_code == 0, added.output
    listed = runner.invoke(app, ["sync", "device", "list"])
    assert "laptop" in listed.output and "active" in listed.output
    assert runner.invoke(app, ["sync", "device", "revoke", "laptop"]).exit_code == 0
    assert "revoked" in runner.invoke(app, ["sync", "device", "list"]).output
    assert runner.invoke(app, ["sync", "device", "revoke", "laptop"]).exit_code == 1


def test_conflicts_lists_nothing_on_a_fresh_project(project_dir: Path) -> None:
    result = runner.invoke(app, ["sync", "conflicts"])
    assert result.exit_code == 0
    assert "No conflicts" in result.output


def test_the_recorded_name_can_be_chosen_and_reset(project_dir: Path) -> None:
    assert "Dana" in runner.invoke(app, ["sync", "user", "Dana"]).output
    assert "Dana" in runner.invoke(app, ["sync", "user"]).output
    assert "Dana" not in runner.invoke(app, ["sync", "user", "--reset"]).output


def test_the_name_lives_in_this_projects_config(project_dir: Path) -> None:
    runner.invoke(app, ["sync", "user", "Dana"])
    assert 'name = "Dana"' in (project_dir / "_civex" / "config.toml").read_text()


def test_the_interval_can_be_never(project_dir: Path) -> None:
    assert "only when asked" in runner.invoke(app, ["sync", "interval", "never"]).output
    assert runner.invoke(app, ["sync", "interval", "2"]).exit_code == 1
