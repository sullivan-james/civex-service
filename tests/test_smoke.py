"""End-to-end smoke test: verify the whole stack (CLI -> service -> DB -> HTTP)
wires together. Granular CLI/service/HTTP behavior lives in tests/cli/,
tests/services/, and tests/server/ — keep this file small.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


def test_init_creates_civex_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--sqlite", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "_civex").is_dir()
    assert (tmp_path / "_civex" / "config.toml").exists()
    assert (tmp_path / "_civex" / "civex.db").exists()


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_full_flow_schema_collection_record(project_dir: Path) -> None:
    """Schema -> collection -> record, via the CLI, exercising the full stack."""
    assert runner.invoke(app, ["schema", "create", "trial"]).exit_code == 0
    assert (
        runner.invoke(
            app, ["schema", "add-field", "trial", "subject", "--type", "string"]
        ).exit_code
        == 0
    )
    assert runner.invoke(app, ["collection", "create", "study"]).exit_code == 0

    result = runner.invoke(
        app, ["record", "add", "--to", "study", "--schema", "trial"], input="S01\n"
    )
    assert result.exit_code == 0

    result = runner.invoke(app, ["record", "find", "--in", "study"])
    assert result.exit_code == 0
    assert "trial" in result.output


def test_file_upload_round_trip_and_config_save(client: TestClient) -> None:
    """The parts of a run that touch the real filesystem: the object store
    (write, atomic rename, read back) and the atomic config.toml rewrite."""
    from civex.config import load_config, save_config

    payload = b"hello from the object store\r\nsecond line\r\n"
    uploaded = client.post(
        "/api/files", files={"file": ("note.txt", payload, "text/plain")}
    )
    assert uploaded.status_code == 201
    sha = uploaded.json()["sha256"]
    assert client.get(f"/api/files/{sha}").content == payload  # bytes untouched

    config = load_config()
    save_config(config)
    assert load_config().project_root == config.project_root
