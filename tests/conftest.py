"""Shared fixtures for the civex test suite.

`project_dir` + `client` support CLI/HTTP-level tests (the original smoke-test
style). `ctx` + the `make_*` factories support service-level tests that talk
to AppContext directly, skipping the CLI/HTTP layers for speed and to avoid
parsing Rich console output.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from civex.config import load_config
from civex.context import AppContext, build_local_context
from civex.domain.dtos import DatasetDTO, RecordDTO, SchemaDTO
from civex.main import app as cli_app

runner = CliRunner()


@pytest.fixture()
def strict_schema_lists() -> None:
    """Request this to run a test with the real "a collection only holds
    records of its enabled schemas" check (see the autouse fixture below)."""


@pytest.fixture(autouse=True)
def _schema_lists_not_enforced(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Most tests are about something else and create collections without
    enabling schemas on them, so the schema-list check is off unless a test
    asks for `strict_schema_lists`. The rule has its own tests
    (tests/services/test_collection_scope.py)."""
    if "strict_schema_lists" in request.fixturenames:
        return
    from civex.services.record_service import RecordService

    monkeypatch.setattr(
        RecordService, "_check_schema_allowed", lambda self, dataset, schema: None
    )


@pytest.fixture()
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Initialise a civex project in a temp dir and cd into it."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli_app, ["init", "--sqlite", str(tmp_path)])
    assert result.exit_code == 0, result.output
    return tmp_path


@pytest.fixture()
def ctx(project_dir: Path):
    """An AppContext wired against the temp project, for service-level tests."""
    context = build_local_context(load_config())
    yield context
    context.close()


@pytest.fixture()
def client(project_dir: Path) -> TestClient:
    from civex.server.app import create_app
    return TestClient(create_app(), raise_server_exceptions=False)


@pytest.fixture()
def make_schema(ctx: AppContext):
    """make_schema("trial", fields=[("subject", "string")]) -> SchemaDTO"""

    def _make(name: str, fields: list[tuple[str, str]] | None = None, **kwargs: Any) -> SchemaDTO:
        ctx.schema_svc.create(name, **kwargs)
        for field_name, dtype in fields or []:
            ctx.schema_svc.add_field(name, field_name, dtype)
        ctx.commit()
        return ctx.schema_svc.get(name)

    return _make


@pytest.fixture()
def make_collection(ctx: AppContext):
    """make_collection("study") -> DatasetDTO"""

    def _make(name: str, **kwargs: Any) -> DatasetDTO:
        collection = ctx.dataset_svc.create(name, **kwargs)
        ctx.commit()
        return collection

    return _make


@pytest.fixture()
def make_record(ctx: AppContext):
    """make_record("study", "trial", {"subject": "S01"}) -> RecordDTO"""

    def _make(
        collection_name: str, schema_name: str, data: dict[str, Any] | None = None, **kwargs: Any
    ) -> RecordDTO:
        record = ctx.record_svc.add(collection_name, schema_name, data or {}, **kwargs)
        ctx.commit()
        return record

    return _make
