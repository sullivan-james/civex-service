"""
AppContext bundles all services for a single CLI command invocation (or HTTP request).

build_local_context() wires together the SQLAlchemy repos and the local file store.
An optional file_store parameter lets callers inject a custom object
store instead of the default LocalFileObjectStore.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from civex.config import Config

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

    from civex.repositories.local.audit_repo import LocalAuditRepository
    from civex.repositories.local.file_store import VolumeAwareFileObjectStore
    from civex.services.ai.service import AiService
    from civex.services.ai_usage_service import AiUsageService
    from civex.services.analytics_service import AnalyticsService
    from civex.services.audit_service import AuditService
    from civex.services.container_plugin_service import ContainerPluginService
    from civex.services.dataset_service import DatasetService
    from civex.services.file_service import FileService
    from civex.services.gc_service import GCService
    from civex.services.file_access_service import FileAccessService
    from civex.services.file_info_service import FileInfoService
    from civex.services.transfer_service import TransferService
    from civex.services.plugin_service import PluginService
    from civex.services.policy_service import PolicyService
    from civex.services.record_service import RecordService
    from civex.services.retention_service import RetentionService
    from civex.services.schema_service import SchemaService
    from civex.services.store_service import StoreService
    from civex.services.export_definition_service import ExportDefinitionService
    from civex.services.view_service import ViewService
    from civex.services.workflow_job_service import WorkflowJobService
    from civex.services.workflow_service import WorkflowService


@lru_cache(maxsize=None)
def _get_engine(url: str) -> Engine:
    """Return a cached engine for the given DB URL."""
    from sqlalchemy import create_engine

    from civex.db.engine import enable_sqlite_foreign_keys

    return enable_sqlite_foreign_keys(create_engine(url))


def _plugins_provider(civex_dir: Path):
    """Every registered plugin, user plugins included, resolved fresh on each
    call so WorkflowService validates against the contracts that exist *now*
    rather than the ones present when the context was built."""

    def provider():
        from civex.plugins.registry import all_plugins, discover_user_plugins

        discover_user_plugins(civex_dir / "plugins")
        return all_plugins()

    return provider


@dataclass
class AppContext:
    schema_svc: SchemaService
    dataset_svc: DatasetService
    record_svc: RecordService
    file_svc: FileService
    job_svc: WorkflowJobService
    store_svc: StoreService
    gc_svc: GCService
    file_info_svc: FileInfoService
    file_access_svc: FileAccessService
    transfer_svc: TransferService
    audit_svc: LocalAuditRepository
    history_svc: AuditService
    retention_svc: RetentionService
    ai_svc: AiService
    ai_usage_svc: AiUsageService
    analytics_svc: AnalyticsService
    workflow_svc: WorkflowService
    plugin_svc: PluginService
    container_plugin_svc: ContainerPluginService
    policy_svc: PolicyService
    view_svc: ViewService
    export_def_svc: ExportDefinitionService
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
    from sqlalchemy.orm import Session

    from civex.db.migrate import ensure_schema_current
    from civex.repositories.local.audit_repo import LocalAuditRepository
    from civex.identity import local_actor
    from civex.repositories.local.dataset_repo import LocalDatasetRepository
    from civex.repositories.local.file_ref_repo import LocalFileReferenceRepository
    from civex.repositories.local.file_store import VolumeAwareFileObjectStore
    from civex.repositories.local.job_repo import LocalWorkflowJobRepository
    from civex.repositories.local.record_repo import LocalRecordRepository
    from civex.repositories.local.schema_repo import LocalSchemaRepository
    from civex.repositories.local.export_definition_repo import (
        LocalExportDefinitionRepository,
    )
    from civex.repositories.local.view_repo import LocalViewRepository
    from civex.services.ai.service import AiService
    from civex.services.ai_usage_service import AiUsageService
    from civex.services.analytics_service import AnalyticsService
    from civex.services.audit_service import AuditService
    from civex.services.container_plugin_service import ContainerPluginService
    from civex.services.dataset_service import DatasetService
    from civex.services.file_service import FileService
    from civex.services.gc_service import GCService
    from civex.services.file_access_service import FileAccessService
    from civex.services.file_info_service import FileInfoService
    from civex.repositories.local.transfer_repo import LocalTransferRepository
    from civex.services.transfer_service import TransferService
    from civex.services.plugin_service import PluginService
    from civex.services.policy_service import PolicyService
    from civex.services.record_service import RecordService
    from civex.services.retention_service import RetentionService
    from civex.services.schema_service import SchemaService
    from civex.services.store_service import StoreService
    from civex.services.export_definition_service import ExportDefinitionService
    from civex.services.view_service import ViewService
    from civex.services.workflow_job_service import WorkflowJobService
    from civex.services.workflow_service import WorkflowService

    engine = _get_engine(config.db.url)
    ensure_schema_current(engine)
    session = Session(engine)
    schema_repo = LocalSchemaRepository(session)
    dataset_repo = LocalDatasetRepository(session)
    record_repo = LocalRecordRepository(
        session, is_postgres=engine.dialect.name == "postgresql"
    )
    job_repo = LocalWorkflowJobRepository(session)
    audit_repo = LocalAuditRepository(session, actor=local_actor())
    view_repo = LocalViewRepository(session)
    if file_store is None:
        file_store = VolumeAwareFileObjectStore(
            config.store_config, config.project_root, session=session
        )

    schema_svc = SchemaService(schema_repo, audit_repo, record_repo)
    job_svc = WorkflowJobService(job_repo, config.civex_dir)
    record_svc = RecordService(
        schema_svc, dataset_repo, record_repo, file_store, job_svc, audit_repo
    )
    dataset_svc = DatasetService(
        dataset_repo,
        audit_repo,
        schema_svc,
        record_svc,
        on_purge=lambda collection_id: store_svc.clear_placement(str(collection_id)),
    )
    file_svc = FileService(file_store)
    store_svc = StoreService(config, file_store)
    gc_svc = GCService(file_store, LocalFileReferenceRepository(session))
    file_info_svc = FileInfoService(
        file_store, LocalFileReferenceRepository(session), dataset_repo
    )
    file_access_svc = FileAccessService(
        record_svc, schema_svc, file_store, config.civex_dir
    )
    transfer_svc = TransferService(
        config,
        file_store,
        LocalFileReferenceRepository(session),
        LocalTransferRepository(session),
        dataset_repo,
        store_svc,
        session.commit,
        session.rollback,
    )
    ai_svc = AiService(schema_svc, dataset_svc, record_svc, job_svc)
    ai_usage_svc = AiUsageService(engine)
    analytics_svc = AnalyticsService(
        record_repo, job_repo, audit_repo, ai_usage_svc, schema_svc, dataset_svc
    )
    workflow_svc = WorkflowService(
        config.civex_dir,
        plugins_provider=_plugins_provider(config.civex_dir),
        active_job_counter=job_svc.count_active_for_workflow,
    )
    plugin_svc = PluginService(
        config.civex_dir, workflows_provider=workflow_svc.list_defs
    )
    container_plugin_svc = ContainerPluginService(config.civex_dir)
    policy_svc = PolicyService(config.civex_dir)
    view_svc = ViewService(view_repo, schema_svc, record_svc, audit_repo)
    export_def_svc = ExportDefinitionService(
        LocalExportDefinitionRepository(session), schema_svc, record_svc
    )
    history_svc = AuditService(
        audit_repo, schema_svc, record_svc, dataset_svc, file_store
    )

    retention_svc = RetentionService(
        record_svc,
        dataset_svc,
        schema_svc,
        audit_repo,
        job_repo,
        config.retention,
        # No sync exists yet, so no history waits to be pushed. Sync (CIVEX-307)
        # turns this on while a remote is set.
        False,
    )

    ctx = AppContext(
        schema_svc=schema_svc,
        dataset_svc=dataset_svc,
        record_svc=record_svc,
        file_svc=file_svc,
        job_svc=job_svc,
        store_svc=store_svc,
        gc_svc=gc_svc,
        file_info_svc=file_info_svc,
        file_access_svc=file_access_svc,
        transfer_svc=transfer_svc,
        audit_svc=audit_repo,
        history_svc=history_svc,
        retention_svc=retention_svc,
        ai_svc=ai_svc,
        ai_usage_svc=ai_usage_svc,
        analytics_svc=analytics_svc,
        workflow_svc=workflow_svc,
        plugin_svc=plugin_svc,
        container_plugin_svc=container_plugin_svc,
        policy_svc=policy_svc,
        view_svc=view_svc,
        export_def_svc=export_def_svc,
        _session=session,
    )
    ai_svc._app_ctx = ctx
    return ctx
