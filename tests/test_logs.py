"""civex.logs and its API and CLI: every log civex keeps, in one place."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from civex import logs
from civex.domain.exceptions import NotFoundError
from civex.main import app


@pytest.fixture
def places(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Path]:
    state = tmp_path / "state"
    home = tmp_path / "app"
    monkeypatch.setenv("CIVEX_USER_STATE", str(state / "sync.toml"))
    monkeypatch.setenv("CIVEX_APP_HOME", str(home))
    monkeypatch.delenv("CIVEX_LOG_DIR", raising=False)
    return {"state": state, "home": home}


def _project_log(civex_dir: Path) -> Path:
    path = civex_dir / "logs" / "civex.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "timestamp": "2026-10-08T10:00:00Z",
            "level": "info",
            "event": "started",
            "logger": "civex",
        },
        {
            "timestamp": "2026-10-08T10:00:01Z",
            "level": "warning",
            "event": "sync is slow",
            "logger": "civex.sync",
        },
        {
            "timestamp": "2026-10-08T10:00:02Z",
            "level": "error",
            "event": "push failed",
            "logger": "civex.sync",
            "request_id": "r1",
        },
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def test_the_logs_there_are_and_only_those(
    places: dict[str, Path], tmp_path: Path
) -> None:
    civex_dir = tmp_path / "proj" / "_civex"
    ids = [s.id for s in logs.sources(civex_dir)]
    assert ids == ["project"]  # listed even before anything is written

    launcher = places["home"] / "logs" / "launcher.log"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("[2026-10-08T10:46:37Z] uv tool upgrade\n")
    places["state"].mkdir(parents=True)
    (places["state"] / "update.log").write_text("updating\n")
    (places["state"] / "serve-8100.log").write_text("Starting civex server\n")
    ids = [s.id for s in logs.sources(civex_dir)]
    assert ids == ["project", "launcher", "update", "serve-8100"]
    with pytest.raises(NotFoundError):
        logs.find(civex_dir, "../../etc/passwd")


def test_structured_lines_read_back_with_their_fields(tmp_path: Path, places) -> None:
    civex_dir = tmp_path / "_civex"
    _project_log(civex_dir)
    source = logs.find(civex_dir, "project")
    lines = logs.read(source)
    assert [line.message for line in lines] == [
        "started",
        "sync is slow",
        "push failed",
    ]
    assert lines[2].level == "error" and lines[2].fields == {
        "logger": "civex.sync",
        "request_id": "r1",
    }
    assert [line.message for line in logs.read(source, level="warning")] == [
        "sync is slow",
        "push failed",
    ]
    assert [line.message for line in logs.read(source, q="PUSH")] == ["push failed"]
    assert [line.message for line in logs.read(source, lines=1)] == ["push failed"]


def test_plain_lines_say_their_time_and_level(tmp_path: Path, places) -> None:
    log = places["home"] / "logs" / "civex-desktop.log"
    log.parent.mkdir(parents=True)
    log.write_text(
        "2026-10-08 10:00:00,123 INFO civex.desktop: opening C:\\ocean\n"
        "2026-10-08 10:00:05,000 ERROR civex.desktop: the server didn't start\n"
        "a line with nothing to say\n"
    )
    lines = logs.read(logs.find(None, "desktop"))
    assert [(l.time, l.level) for l in lines] == [
        ("2026-10-08 10:00:00,123", "info"),
        ("2026-10-08 10:00:05,000", "error"),
        (None, None),
    ]


def test_a_big_log_is_read_from_its_end(tmp_path: Path, places) -> None:
    places["state"].mkdir(parents=True)
    path = places["state"] / "update.log"
    path.write_text("".join(f"line {i}\n" for i in range(200_000)))
    lines = logs.read(logs.find(None, "update"), lines=3)
    assert [l.message for l in lines] == ["line 199997", "line 199998", "line 199999"]


def test_the_api_lists_reads_and_downloads(
    client: TestClient, project_dir: Path, places
) -> None:
    _project_log(project_dir / "_civex")
    listed = client.get("/api/logs").json()
    assert listed[0]["id"] == "project" and listed[0]["exists"] is True
    read = client.get("/api/logs/project", params={"level": "error"}).json()
    assert [l["message"] for l in read["lines"]] == ["push failed"]
    assert client.get("/api/logs/nope").status_code == 404
    download = client.get("/api/logs/project/download")
    assert download.status_code == 200 and "push failed" in download.text
    # Not from this computer (the test client isn't loopback): nothing opens.
    assert client.post("/api/logs/project/open").json() == {"opened": False}


def test_the_cli_shows_a_logs_lines(project_dir: Path, places) -> None:
    _project_log(project_dir / "_civex")
    result = CliRunner().invoke(app, ["logs", "show", "project", "--level", "error"])
    assert result.exit_code == 0, result.output
    assert "push failed" in result.output and "started" not in result.output
    result = CliRunner().invoke(app, ["logs", "list"])
    assert "project" in result.output
