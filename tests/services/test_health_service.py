"""`civex doctor` and the Health page share one service: they say the same
things, repair backs up and is safe to repeat, and a host without a machine
gets no machine checks."""

from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from civex.config import load_config, load_config_at
from civex.domain import features as f
from civex.install_check import Check
from civex.main import app as cli_app
from civex.project import Project
from civex.server.app import create_app
from civex.services import health_service
from civex.services.sync_lock import sync_lock

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_install(monkeypatch: pytest.MonkeyPatch) -> None:
    """The machine running the tests has its own install problems."""
    monkeypatch.setattr(
        health_service, "run_install_checks", lambda: [Check("uv", "ok", "found")]
    )


@pytest.fixture()
def project(project_dir: Path) -> Project:
    return Project.local(load_config())


def _db_file(project: Project) -> Path:
    return Path(project.config.db.url.removeprefix("sqlite:///"))


def _edit_after_the_fact(project: Project) -> None:
    """What happened on the desktop: a migration was edited after it ran, so a
    database stamped at head lacks its table and column."""
    with sqlite3.connect(_db_file(project)) as db:
        db.execute("DROP TRIGGER IF EXISTS audit_log_local_seq")
        db.execute("DROP TABLE audit_log")
        db.execute("ALTER TABLE sync_ops DROP COLUMN already_done")


def test_a_healthy_project_has_no_problems(project: Project):
    report = health_service.check_health(project)
    assert report.problems() == [] and report.data_checked


def test_repair_fixes_a_database_stamped_at_head_that_lacks_a_table_and_column(
    project: Project,
):
    _edit_after_the_fact(project)
    before = health_service.check_health(project)
    assert (
        "audit_log" in before.structure and "sync_ops.already_done" in before.structure
    )
    assert not before.data_checked and before.repairable

    result = health_service.repair_database(project)

    assert result.backup.is_file() and result.backup.parent.name == "backups"
    assert "audit_log" in result.added
    after = health_service.check_health(project)
    assert after.problems() == [] and after.data_checked
    with sqlite3.connect(_db_file(project)) as db:
        assert db.execute(
            "SELECT name FROM sqlite_master WHERE name='audit_log_local_seq'"
        ).fetchone()


def test_the_backup_holds_what_was_there_before(project: Project):
    _edit_after_the_fact(project)
    result = health_service.repair_database(project)
    with sqlite3.connect(result.backup) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master")}
    assert "audit_log" not in tables and "schemas" in tables


def test_repair_twice_changes_nothing_the_second_time(project: Project):
    _edit_after_the_fact(project)
    health_service.repair_database(project)
    again = health_service.repair_database(project)
    assert again.added == [] and again.backup.is_file()
    assert health_service.check_health(project).problems() == []


def test_repair_is_refused_while_a_sync_runs_and_changes_nothing(project: Project):
    _edit_after_the_fact(project)
    with sync_lock(project.config.civex_dir):
        with pytest.raises(health_service.RepairRefused, match="Syncing"):
            health_service.repair_database(project)
    assert not (project.config.civex_dir / "backups").exists()
    assert "audit_log" in health_service.check_health(project).structure


def test_the_command_says_what_the_service_says(project: Project):
    _edit_after_the_fact(project)
    out = runner.invoke(cli_app, ["doctor"]).output
    assert runner.invoke(cli_app, ["doctor"]).exit_code == 1
    for problem in health_service.check_health(project).problems():
        if problem.kind == "database":
            assert " ".join(problem.message.split()[:8]) in " ".join(out.split())


def test_the_command_repairs(project: Project):
    _edit_after_the_fact(project)
    result = runner.invoke(cli_app, ["doctor", "--repair"])
    assert result.exit_code == 0, result.output
    assert "Backed the database up" in result.output
    assert health_service.check_health(project).problems() == []


def test_the_api_answers_like_the_service(project: Project, client: TestClient):
    _edit_after_the_fact(project)
    answer = client.get("/api/health").json()
    expected = health_service.check_health(project)
    assert [p["message"] for p in answer["problems"]] == [
        p.message for p in expected.problems()
    ]
    assert answer["can_repair"] is True

    done = client.post("/api/health/repair")
    assert done.status_code == 200 and Path(done.json()["backup"]).is_file()
    assert done.json()["health"]["ok"] is True


def test_the_api_refuses_repair_while_a_sync_runs(project: Project, client: TestClient):
    _edit_after_the_fact(project)
    with sync_lock(project.config.civex_dir):
        assert client.post("/api/health/repair").status_code == 409


def _hosted(project_dir: Path, features: frozenset[str]) -> TestClient:
    app = create_app(features=features)
    app.state.project_resolver = lambda request: dataclasses.replace(
        Project.local(load_config_at(project_dir)), features=features
    )
    return TestClient(app, raise_server_exceptions=False)


def test_a_host_without_a_machine_gets_no_machine_checks(project_dir: Path):
    hosted = _hosted(project_dir, f.LOCAL_FEATURES - {f.UPDATES, f.VOLUMES, f.DB_ADMIN})
    answer = hosted.get("/api/health")
    assert answer.status_code == 200
    body = answer.json()
    assert body["checks"] is None and body["repair_offered"] is False
    assert hosted.post("/api/health/repair").status_code == 501
    local = TestClient(create_app()).get("/api/health").json()
    assert local["checks"] and local["repair_offered"] is True


def test_the_report_leaves_out_files_on_drives_for_a_host_without_volumes(
    project: Project,
):
    hosted = dataclasses.replace(
        project, features=f.LOCAL_FEATURES - {f.VOLUMES, f.UPDATES}
    )
    report = health_service.check_health(hosted)
    assert report.install is None and report.left_on_drives == 0
