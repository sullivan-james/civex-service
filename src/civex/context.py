"""
AppContext bundles all services for a single CLI command invocation (or HTTP request).

build_local_context() wires together the SQLAlchemy repos and the local file store.
For the future FastAPI server, call build_local_context() once per request, sharing
the cached engine but not the Session.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from civex.config import Config
from civex.db.session import _engine
from civex.repositories.local.dataset_repo import LocalDatasetRepository
from civex.repositories.local.file_store import LocalFileObjectStore
from civex.repositories.local.record_repo import LocalRecordRepository
from civex.repositories.local.schema_repo import LocalSchemaRepository
from civex.services.dataset_service import DatasetService
from civex.services.file_service import FileService
from civex.services.record_service import RecordService
from civex.services.schema_service import SchemaService


@dataclass
class AppContext:
    schema_svc: SchemaService
    dataset_svc: DatasetService
    record_svc: RecordService
    file_svc: FileService
    # Keep the session so CLI commands can commit after all service calls.
    _session: Session

    def commit(self) -> None:
        self._session.commit()

    def close(self) -> None:
        self._session.close()


def build_local_context(config: Config) -> AppContext:
    session = Session(_engine())
    schema_repo = LocalSchemaRepository(session)
    dataset_repo = LocalDatasetRepository(session)
    record_repo = LocalRecordRepository(session)
    file_store = LocalFileObjectStore(config.objects_dir)

    schema_svc = SchemaService(schema_repo)
    dataset_svc = DatasetService(schema_repo, dataset_repo)
    record_svc = RecordService(schema_svc, dataset_repo, record_repo, file_store)
    file_svc = FileService(file_store)

    return AppContext(
        schema_svc=schema_svc,
        dataset_svc=dataset_svc,
        record_svc=record_svc,
        file_svc=file_svc,
        _session=session,
    )
