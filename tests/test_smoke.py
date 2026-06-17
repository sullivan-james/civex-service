"""Smoke tests: verify core CLI and API paths work end-to-end."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


@pytest.fixture()
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Initialise a civex project in a temp dir and cd into it."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--sqlite", str(tmp_path)])
    assert result.exit_code == 0, result.output
    return tmp_path


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

def test_init_creates_civex_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--sqlite", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / ".civex").is_dir()
    assert (tmp_path / ".civex" / "config.toml").exists()
    assert (tmp_path / ".civex" / "civex.db").exists()


def test_init_config_has_valid_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import tomllib
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init", "--sqlite", str(tmp_path)])
    config_text = (tmp_path / ".civex" / "config.toml").read_bytes()
    data = tomllib.loads(config_text.decode())
    assert "db" in data
    assert data["db"]["url"].startswith("sqlite:///")


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------

def test_schema_create_and_list(project_dir: Path) -> None:
    result = runner.invoke(app, ["schema", "create", "trial", "--description", "A trial"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["schema", "list"])
    assert result.exit_code == 0
    assert "trial" in result.output


def test_schema_add_field(project_dir: Path) -> None:
    runner.invoke(app, ["schema", "create", "trial"])
    result = runner.invoke(app, ["schema", "add-field", "trial", "subject", "--type", "string", "--required"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["schema", "show", "trial"])
    assert result.exit_code == 0
    assert "subject" in result.output


def test_schema_inheritance(project_dir: Path) -> None:
    runner.invoke(app, ["schema", "create", "base"])
    runner.invoke(app, ["schema", "add-field", "base", "subject", "--type", "string"])
    runner.invoke(app, ["schema", "create", "child", "--parent", "base"])

    result = runner.invoke(app, ["schema", "show", "child"])
    assert result.exit_code == 0
    assert "subject" in result.output


# ---------------------------------------------------------------------------
# dataset
# ---------------------------------------------------------------------------

def test_dataset_create_and_list(project_dir: Path) -> None:
    result = runner.invoke(app, ["dataset", "create", "my-study"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["dataset", "list"])
    assert result.exit_code == 0
    assert "my-study" in result.output


# ---------------------------------------------------------------------------
# record
# ---------------------------------------------------------------------------

def test_record_add_and_find(project_dir: Path) -> None:
    runner.invoke(app, ["schema", "create", "trial"])
    runner.invoke(app, ["schema", "add-field", "trial", "subject", "--type", "string"])
    runner.invoke(app, ["dataset", "create", "study"])

    # Provide field value via stdin
    result = runner.invoke(app, ["record", "add", "--to", "study", "--schema", "trial"], input="S01\n")
    assert result.exit_code == 0

    result = runner.invoke(app, ["record", "find", "--in", "study"])
    assert result.exit_code == 0
    assert "trial" in result.output  # schema name appears in the summary table


def test_record_not_found_exits_nonzero(project_dir: Path) -> None:
    result = runner.invoke(app, ["record", "show", "nonexistent-id"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

def test_health_endpoint(project_dir: Path) -> None:
    from fastapi.testclient import TestClient
    from civex.server.app import create_app

    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_schemas_empty(project_dir: Path) -> None:
    from fastapi.testclient import TestClient
    from civex.server.app import create_app

    client = TestClient(create_app())
    response = client.get("/api/schemas")
    assert response.status_code == 200
    assert response.json() == []


def test_api_create_schema(project_dir: Path) -> None:
    from fastapi.testclient import TestClient
    from civex.server.app import create_app

    client = TestClient(create_app())
    response = client.post("/api/schemas", json={"name": "trial", "description": "A trial schema"})
    assert response.status_code == 201
    assert response.json()["name"] == "trial"

    response = client.get("/api/schemas")
    assert any(s["name"] == "trial" for s in response.json())


def test_api_create_dataset(project_dir: Path) -> None:
    from fastapi.testclient import TestClient
    from civex.server.app import create_app

    client = TestClient(create_app())
    response = client.post("/api/datasets", json={"name": "study-2024"})
    assert response.status_code == 201
    assert response.json()["name"] == "study-2024"
