"""
AppContext bundles all services for a single CLI command invocation (or HTTP request).

build_local_context() wires together the SQLAlchemy repos and the local file store.
If a [remote] is configured, a transport is passed to FileService for lazy object fetch.
An optional file_store parameter lets callers (e.g. civex-hub) inject a custom object
store instead of the default LocalFileObjectStore.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

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
from civex.repositories.protocols import FileObjectStore
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
    _session: Session

    def commit(self) -> None:
        self._session.commit()

    def close(self) -> None:
        self._session.close()


def _apply_migrations(session: Session, engine: Engine) -> None:
    """Create any missing tables and apply idempotent column additions for existing databases."""
    from civex.db.models import Base
    Base.metadata.create_all(engine, checkfirst=True)

    from sqlalchemy import text
    migrations = [
        "ALTER TABLE workflow_jobs ADD COLUMN log TEXT",
        "ALTER TABLE records ADD COLUMN search_vector TSVECTOR",
        "CREATE INDEX IF NOT EXISTS ix_records_search_vector ON records USING gin(search_vector)",
        (
            "UPDATE records "
            "SET search_vector = to_tsvector('simple', ("
            "  SELECT coalesce(string_agg(value, ' '), '') "
            "  FROM jsonb_each_text(data) "
            "  WHERE value IS NOT NULL "
            "    AND value NOT IN ('true', 'false') "
            "    AND value NOT LIKE '{%'"
            "))"
        ),
        "ALTER TABLE commits ADD COLUMN seq INTEGER",
        "ALTER TABLE schemas ADD COLUMN display_field VARCHAR(255)",
    ]
    for sql in migrations:
        try:
            session.execute(text(sql))
            session.commit()
        except Exception:
            session.rollback()

    # Backfill seq for any commits that predate the column.
    from civex.db.models import Commit as _Commit
    unsequenced = (
        session.query(_Commit)
        .filter(_Commit.seq.is_(None))
        .order_by(_Commit.created_at)
        .all()
    )
    if unsequenced:
        from sqlalchemy import func as _func
        max_seq = session.query(_func.max(_Commit.seq)).scalar() or 0
        for i, row in enumerate(unsequenced, start=max_seq + 1):
            row.seq = i
        session.commit()


def build_local_context(
    config: Config,
    file_store: FileObjectStore | None = None,
) -> AppContext:
    engine = _get_engine(config.db.url)
    session = Session(engine)
    _apply_migrations(session, engine)
    schema_repo = LocalSchemaRepository(session)
    dataset_repo = LocalDatasetRepository(session)
    record_repo = LocalRecordRepository(session, is_postgres=engine.dialect.name == "postgresql")
    job_repo = LocalWorkflowJobRepository(session)
    audit_repo = LocalAuditRepository(session)
    if file_store is None:
        file_store = VolumeAwareFileObjectStore(config.store_config, config.project_root)

    remote_transport = None
    if config.remote:
        from civex.sync.transport import get_transport
        remote_transport, _path = get_transport(config.remote.url, remote_civex=config.remote.remote_civex)

    schema_svc = SchemaService(schema_repo, audit_repo)
    dataset_svc = DatasetService(dataset_repo, audit_repo)
    job_svc = WorkflowJobService(job_repo, config.civex_dir)
    record_svc = RecordService(schema_svc, dataset_repo, record_repo, file_store, job_svc, audit_repo)
    file_svc = FileService(file_store, remote_transport=remote_transport)
    store_svc = StoreService(config, file_store)

    return AppContext(
        schema_svc=schema_svc,
        dataset_svc=dataset_svc,
        record_svc=record_svc,
        file_svc=file_svc,
        job_svc=job_svc,
        store_svc=store_svc,
        audit_svc=audit_repo,
        _session=session,
    )
