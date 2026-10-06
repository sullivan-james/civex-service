"""Shared fixtures for the civex test suite.

`project_dir` + `client` support CLI/HTTP-level tests (the original smoke-test
style). `ctx` + the `make_*` factories support service-level tests that talk
to AppContext directly, skipping the CLI/HTTP layers for speed and to avoid
parsing Rich console output.
"""

from __future__ import annotations

from collections.abc import Iterator
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

# The tests whose result can differ by operating system: they touch real files,
# paths, processes, mounts or the launcher. CI runs only these on Windows and
# macOS (`pytest -m os_sensitive`); the full suite runs on Linux. Add a test
# file here when it exercises something OS-specific; pure logic does not belong.
OS_SENSITIVE = {
    "test_smoke.py",
    "test_fs_locations.py",
    "test_launcher.py",
    "test_processes.py",
    "test_sqlite_url.py",
    # storage: volumes, the object store, moving and collecting files
    "test_volume_picker.py",
    "test_volume_identity.py",
    "test_file_store_offline.py",
    "test_file_service.py",
    "test_file_service_stream.py",
    "test_file_locations.py",
    "test_gc_service.py",
    "test_transfer_engine.py",
    "test_transfer_jobs.py",
    "test_transfer_service.py",
    "test_placement.py",
    "test_store_placement_service.py",
    "test_store_volumes.py",
    "test_store_move.py",
    "test_store_gc.py",
    "test_store_place.py",
    "test_collection_storage_router.py",
    "test_store_gc_router.py",
    "test_files_stream_router.py",
    "test_records_files_zip_router.py",
    "test_record_files_zip.py",
    # files by name and folder: export trees, links, copies and a file manager
    "test_file_access_service.py",
    "test_file_access_router.py",
    "test_files.py",
    "test_export_defs.py",
    "test_export_definitions_router.py",
    "test_fs_open.py",
    # the database file and project folder
    "test_migrate.py",
    "test_db_move_service.py",
    "test_init.py",
    "test_dump.py",
    "test_dump_service.py",
    "test_view.py",
    # plugin subprocesses and the plugin folder
    "test_subprocess_runtime.py",
    "test_subprocess_runtime_uv_e2e.py",
    "test_registry.py",
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if item.path.name in OS_SENSITIVE:
            item.add_marker(pytest.mark.os_sensitive)


@pytest.fixture()
def strict_schema_lists() -> None:
    """Request this to run a test with the real "a collection only holds
    records of its enabled schemas" check (see the autouse fixture below)."""


@pytest.fixture(autouse=True)
def _stop_the_transfer_worker() -> Iterator[None]:
    """The server's transfer worker is a process-wide singleton that starts the
    first time a move is queued. Left running, it would carry on polling
    whichever project a later test is using, so stop it after each test."""
    yield
    from civex.services.transfer_jobs import jobs

    jobs.shutdown()


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

    def _make(
        name: str, fields: list[tuple[str, str]] | None = None, **kwargs: Any
    ) -> SchemaDTO:
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
        collection_name: str,
        schema_name: str,
        data: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> RecordDTO:
        # As in the app, a collection holds only records of the schemas it
        # lists, so list this one (and those above it) first. The check itself
        # is off for most tests, but restoring follows the list.
        listed = ctx.dataset_svc.get(collection_name).schemas
        schema = ctx.schema_svc.get(schema_name)
        wanted = [schema_name] + [a.name for a in ctx.schema_svc.ancestors(schema)]
        if any(name not in listed for name in wanted):
            ctx.dataset_svc.update(
                collection_name, schemas=sorted(set(listed) | set(wanted))
            )
        record = ctx.record_svc.add(collection_name, schema_name, data or {}, **kwargs)
        ctx.commit()
        return record

    return _make
