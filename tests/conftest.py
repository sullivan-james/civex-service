"""Shared fixtures for the civex test suite.

`project_dir` + `client` support CLI/HTTP-level tests (the original smoke-test
style). `ctx` + the `make_*` factories support service-level tests that talk
to AppContext directly, skipping the CLI/HTTP layers for speed and to avoid
parsing Rich console output.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from civex.config import load_config
from civex.context import AppContext, build_local_context
from civex.domain.dtos import DatasetDTO, RecordDTO, SchemaDTO
from civex.main import app as cli_app

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

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
    "test_bundle.py",
    "test_bundle_service.py",
    "test_bundle_router.py",
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


@pytest.fixture(autouse=True)
def _run_folders_in_the_test_dir(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Workflow run folders (`civex.plugins.runtime.new_run_dir`) go under
    pytest's own temp dir, never the user's cache."""
    monkeypatch.setenv("CIVEX_RUNS_DIR", str(tmp_path_factory.getbasetemp() / "runs"))


@pytest.fixture(autouse=True)
def _no_warm_plugin_processes() -> Iterator[None]:
    """Plugin processes are kept between runs (`civex.plugins.workers`); no
    test may find one an earlier test left, and none outlives its test (each
    test's plugin is a new file, so they would pile up until the idle timeout)."""
    from civex.plugins.workers import POOL

    POOL.close()
    yield
    POOL.close()


@pytest.fixture(autouse=True)
def _never_a_real_project(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    """No test may find a real project. Looking for one walks up from the
    working directory, so a test that loses its temporary folder (an undone
    chdir) would otherwise open whatever project sits above the checkout and
    change it, migrations included. Any project found outside pytest's own
    temporary folders fails the test instead. Installed by hand rather than
    with `monkeypatch`, so a test's `monkeypatch.undo()` can't remove it."""
    import sys

    import civex.config as config

    real = config.find_project_root
    base = tmp_path_factory.getbasetemp().resolve()

    def only_test_projects(start: Path | None = None):
        root = real(start)
        if root is not None:
            resolved = root.resolve()
            if resolved != base and base not in resolved.parents:
                raise RuntimeError(
                    f"A test reached a real civex project at {root}; tests must "
                    "only use projects in their own temporary folders"
                )
        return root

    patched = [
        module
        for name, module in list(sys.modules.items())
        if name.startswith("civex")
        and getattr(module, "find_project_root", None) is real
    ]
    for module in patched:
        module.find_project_root = only_test_projects  # type: ignore[attr-defined]
    try:
        yield
    finally:
        for module in patched:
            module.find_project_root = real  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def _stop_the_transfer_worker() -> Iterator[None]:
    """The server's transfer worker is a process-wide singleton that starts the
    first time a move is queued. Left running, it would carry on polling
    whichever project a later test is using, so stop it after each test."""
    yield
    from civex.services.index_jobs import index_jobs
    from civex.services.transfer_jobs import jobs

    jobs.shutdown()
    index_jobs.shutdown()  # likewise the field-index upkeep thread


@pytest.fixture(autouse=True)
def background_upkeep(monkeypatch) -> list:
    """A CLI command that changes which fields are indexed starts a process of
    its own to build them (`index_jobs.start_background_upkeep`). Tests never
    start one: they get the list of projects it would have been started for,
    and build in the foreground (`run_upkeep`) where they need the index."""
    from civex.services import index_jobs as jobs

    started: list = []
    monkeypatch.setattr(
        jobs, "start_background_upkeep", lambda root, civex_dir: started.append(root)
    )
    return started


_template: dict[str, sqlite3.Connection] = {}


@pytest.fixture(autouse=True)
def _migrate_from_a_template(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Migrating a new SQLite database takes ~0.3 s and nearly every test makes
    one, which was half the suite's time. Migrate one database per process,
    then copy it (SQLite's backup API) into each new empty database, with a
    project id of its own. A database
    that isn't empty migrates as usual, and tests/db, which tests migrating
    itself, never uses the copy."""
    if request.node.nodeid.startswith("tests/db/"):
        return
    from sqlalchemy import create_engine, inspect

    import civex.db.migrate as migrate

    migrate_for_real = migrate._migrate_connection

    def template() -> sqlite3.Connection:
        if "db" not in _template:
            path = tmp_path_factory.mktemp("migrated") / "template.db"
            engine = create_engine(f"sqlite:///{path}")
            with engine.connect() as connection:
                migrate_for_real(connection)
            engine.dispose()
            _template["db"] = sqlite3.connect(path, check_same_thread=False)
        return _template["db"]

    def from_template(connection: Connection, layout=None) -> None:
        if connection.dialect.name != "sqlite":
            return migrate_for_real(connection, layout)
        empty = not inspect(connection).get_table_names()
        connection.rollback()
        if not empty:
            return migrate_for_real(connection, layout)
        template().backup(connection.connection.dbapi_connection)
        # The one thing a migration makes at random: every project its own id.
        connection.exec_driver_sql(
            f"UPDATE sync_meta SET project_id = '{uuid.uuid4().hex}'"
        )
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()

    monkeypatch.setattr(migrate, "_migrate_connection", from_template)


@pytest.fixture(autouse=True)
def _forget_engines() -> Iterator[None]:
    """`context._get_engine` keeps one engine per database URL for the life of
    the process, and every test's project has its own URL. Kept, each holds its
    pool and compiled statements, and a worker grows by megabytes a test until
    WSL runs out of memory, so drop them after each test."""
    yield
    from civex import context

    context._get_engine.cache_clear()


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
        record = ctx.record_svc.add(collection_name, schema_name, data or {}, **kwargs)
        ctx.commit()
        return record

    return _make


@pytest.fixture()
def sign_in_over_http():
    """sign_in_over_http(client, invite) -> a session token: join with the
    invite and sign in over HTTP, as a new machine would."""
    import time
    import uuid as _uuid

    from civex import keys
    from civex.domain.sync import protocol_header, session_request

    def _sign_in(client, invite: str) -> str:
        device_id, private = str(_uuid.uuid4()), keys.new_private_key()
        headers = {"X-Civex-Protocol": protocol_header()}
        body = {
            "invite": invite,
            "device_id": device_id,
            "public_key": keys.public_of(private),
        }
        joined = client.post("/api/sync/v1/join", headers=headers, json=body)
        assert joined.status_code == 200, joined.text
        at = int(time.time())
        request = session_request(joined.json()["authority_key"], device_id, at)
        body = {
            "device_id": device_id,
            "at": at,
            "signature": keys.sign(private, request),
        }
        grant = client.post("/api/sync/v1/session", headers=headers, json=body)
        assert grant.status_code == 200, grant.text
        return grant.json()["token"]

    return _sign_in


@pytest.fixture(autouse=True)
def _forget_failed_sign_ins():
    """The peer API counts failed joins and sign-ins per caller, in memory; a
    test starts with none counted."""
    import sys

    peer = sys.modules.get("civex.server.routers.sync_peer")
    if peer is not None:
        peer._attempts._failed.clear()
    yield
