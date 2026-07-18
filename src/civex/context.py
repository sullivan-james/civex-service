"""
AppContext bundles all services for a single CLI command invocation (or HTTP request).

build_local_context() wires together the SQLAlchemy repos and the local file store.
If a [remote] is configured, a transport is passed to FileService for lazy object fetch.
An optional file_store parameter lets callers (e.g. civex-hub) inject a custom object
store instead of the default LocalFileObjectStore.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from civex.config import Config
from civex.repositories.local.audit_repo import LocalAuditRepository
from civex.repositories.local.dataset_repo import LocalDatasetRepository
from civex.repositories.local.file_store import VolumeAwareFileObjectStore
from civex.repositories.local.job_repo import LocalWorkflowJobRepository
from civex.repositories.local.record_repo import LocalRecordRepository
from civex.repositories.local.schema_repo import LocalSchemaRepository
from civex.services.ai.service import AiService
from civex.services.dataset_service import DatasetService
from civex.services.file_service import FileService
from civex.services.record_service import RecordService
from civex.services.schema_service import SchemaService
from civex.services.store_service import StoreService
from civex.services.workflow_job_service import WorkflowJobService


@lru_cache(maxsize=None)
def _get_engine(url: str) -> Engine:
    """Return a cached engine for the given DB URL."""
    return create_engine(url)


@dataclass
class AppContext:
    schema_svc: SchemaService
    dataset_svc: DatasetService
    record_svc: RecordService
    file_svc: FileService
    job_svc: WorkflowJobService
    store_svc: StoreService
    audit_svc: LocalAuditRepository
    ai_svc: AiService
    _session: Session

    def commit(self) -> None:
        self._session.commit()

    def close(self) -> None:
        self._session.close()

    @contextmanager
    def validation_scope(self) -> Iterator[None]:
        """Run code inside a SQL SAVEPOINT that is always rolled back on exit,
        even on success -- for validating a real service call's side effects
        (existence checks, dtype/restriction rules) without persisting them.

        This is the only sanctioned place outside AppContext itself that a
        caller (currently AiService's act-tool proposal builders) may reach
        into _session; everywhere else, go through a service.
        """
        nested = self._session.begin_nested()
        try:
            yield
        finally:
            nested.rollback()


def build_local_context(
    config: Config,
    file_store: VolumeAwareFileObjectStore | None = None,
) -> AppContext:
    from civex.db.migrate import ensure_schema_current

    engine = _get_engine(config.db.url)
    ensure_schema_current(engine)
    session = Session(engine)
    schema_repo = LocalSchemaRepository(session)
    dataset_repo = LocalDatasetRepository(session)
    record_repo = LocalRecordRepository(
        session, is_postgres=engine.dialect.name == "postgresql"
    )
    job_repo = LocalWorkflowJobRepository(session)
    audit_repo = LocalAuditRepository(session)
    if file_store is None:
        file_store = VolumeAwareFileObjectStore(
            config.store_config, config.project_root
        )

    remote_transport = None
    if config.remote:
        from civex.sync.transport import get_transport

        remote_transport, _path = get_transport(
            config.remote.url, remote_civex=config.remote.remote_civex
        )

    schema_svc = SchemaService(schema_repo, audit_repo)
    dataset_svc = DatasetService(dataset_repo, audit_repo)
    job_svc = WorkflowJobService(job_repo, config.civex_dir)
    record_svc = RecordService(
        schema_svc, dataset_repo, record_repo, file_store, job_svc, audit_repo
    )
    file_svc = FileService(file_store, remote_transport=remote_transport)
    store_svc = StoreService(config, file_store)
    ai_svc = AiService(schema_svc, dataset_svc, record_svc, job_svc)

    ctx = AppContext(
        schema_svc=schema_svc,
        dataset_svc=dataset_svc,
        record_svc=record_svc,
        file_svc=file_svc,
        job_svc=job_svc,
        store_svc=store_svc,
        audit_svc=audit_repo,
        ai_svc=ai_svc,
        _session=session,
    )
    ai_svc._app_ctx = ctx
    return ctx
