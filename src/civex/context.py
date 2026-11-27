"""
AppContext bundles all services for a single CLI command invocation (or HTTP request).

build_context(project) wires together the SQLAlchemy repos and the file store
for one `Project` (civex.project): the project's settings, where they are kept,
who is making changes, and optionally a shared engine. build_local_context(config)
is the same for the project in a folder on this machine, as the CLI and
`civex serve` host it. An optional file_store parameter lets callers inject an
object store instead of the one the project's settings name (drives on this
machine, or a bucket with `[store.s3]`).
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta, timezone
import weakref

from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterator

from civex.domain.dtos import RecordUse
from civex.domain import release as release_rules
from civex.config import Config, ConfigStore, PartitionLayout
from civex.domain import features
from civex.domain.exceptions import FeatureUnavailableError
from civex.domain.permissions import Permissions
from civex.domain.query import RecordQuery
from civex.project import Project
from civex.store_copy import CopyResult as CopyResult
from civex.store_copy import copy_objects as copy_objects

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

    from civex.repositories.local.audit_repo import LocalAuditRepository
    from civex.repositories.protocols import ObjectStore
    from civex.repositories.local.sync_repo import LocalSyncRepository
    from civex.services.ai.service import AiService
    from civex.services.ai_usage_service import AiUsageService
    from civex.services.analytics_service import AnalyticsService
    from civex.services.audit_service import AuditService
    from civex.services.container_plugin_service import ContainerPluginService
    from civex.services.dataset_service import DatasetService
    from civex.services.file_service import FileService
    from civex.services.gc_service import GCService
    from civex.services.file_access_service import FileAccessService
    from civex.services.import_service import ImportService
    from civex.services.file_info_service import FileInfoService
    from civex.services.transfer_service import TransferService
    from civex.services.plugin_service import PluginService
    from civex.services.policy_service import PolicyService
    from civex.services.quality_service import QualityService
    from civex.services.record_service import RecordService
    from civex.services.retention_service import RetentionService
    from civex.services.schema_service import SchemaService
    from civex.services.bucket_service import BucketService
    from civex.services.store_service import StoreService
    from civex.services.bundle_service import BundleService
    from civex.services.export_definition_service import ExportDefinitionService
    from civex.services.history_compaction import HistoryCompactionService
    from civex.services.index_service import IndexService
    from civex.services.device_keys import DeviceKeys
    from civex.services.library_service import LibraryService
    from civex.services.sync_authority import SyncAuthorityService
    from civex.services.sync_service import SyncService
    from civex.services.view_service import ViewService
    from civex.services.dashboard_service import DashboardService
    from civex.services.note_service import NoteService
    from civex.services.release_service import ReleaseService
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
    gc_svc: GCService
    file_info_svc: FileInfoService
    file_access_svc: FileAccessService
    import_svc: ImportService
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
    dashboard_svc: DashboardService
    # Notes people leave on records (`domain/notes`).
    note_svc: NoteService
    # Frozen, citable copies of the data (`domain/release`).
    release_svc: ReleaseService
    export_def_svc: ExportDefinitionService
    bundle_svc: BundleService
    sync_repo: LocalSyncRepository
    authority_svc: SyncAuthorityService
    device_keys: DeviceKeys
    sync_svc: SyncService
    library_svc: LibraryService
    compaction_svc: HistoryCompactionService
    # Data checks: what in the records needs a look (`domain/quality`).
    quality_svc: QualityService
    # Which fields have an index in this computer's database.
    index_svc: IndexService
    # Where files are kept: drives or a bucket (`features.STORE_ADMIN`).
    bucket_svc: BucketService
    project: Project
    _session: Session
    # The services of a project whose files are on drives on this machine; None
    # when they are in a bucket (`store_svc`/`transfer_svc` then say so).
    _store_svc: StoreService | None = None
    _transfer_svc: TransferService | None = None
    # True when this context reads from the project's `read_engine` (a replica):
    # it was built `read_only=True` and the project offers one and doesn't
    # need the primary for this request. Such a context refuses writes.
    on_read_engine: bool = False

    @property
    def store_svc(self) -> StoreService:
        """Drives: adding, adopting, homing collections. Only where files are
        on drives on this machine (`features.VOLUMES`)."""
        if self._store_svc is None:
            raise FeatureUnavailableError(features.VOLUMES)
        return self._store_svc

    @property
    def transfer_svc(self) -> TransferService:
        """Moving files between drives. Only where there are drives."""
        if self._transfer_svc is None:
            raise FeatureUnavailableError(features.VOLUMES)
        return self._transfer_svc

    @property
    def config(self) -> Config:
        """This project's settings, as they were when the context was built."""
        return self.project.config

    @property
    def config_store(self) -> ConfigStore:
        """Where this project's settings are kept; the one way to save them."""
        return self.project.config_store

    @property
    def features(self) -> frozenset[str]:
        """What this server does for this project (`domain.features`)."""
        return self.project.features

    @property
    def permissions(self) -> Permissions:
        """What whoever this context is for may do (`domain.permissions`)."""
        return self.project.permissions

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        """Forget everything this context has changed since its last commit:
        for a request that does several things as one and must leave nothing
        when a later one is refused (a file stored, then a record save that
        failed its checks)."""
        self._session.rollback()

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> AppContext:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Commit what the block did, or forget it if the block raised; then
        close."""
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()

    def frame(
        self,
        collection: str | None,
        schema: str,
        *,
        where: dict[str, Any] | list[str] | None = None,
        search: str | None = None,
        search_fields: list[str] | None = None,
        within: str | None = None,
        **options: Any,
    ) -> Any:
        """The records of `schema` in `collection` (None: every collection)
        as a pandas DataFrame with typed columns: `file_access_svc.frame`
        over the query these arguments make. `where` is a filter tree (the
        explorer's) or `["field=value", ...]`; `within` a record id (only
        what is beneath it). `options` are `frame`'s: `columns`, `geo`,
        `files`, `references`."""
        return self.file_access_svc.frame(
            _frame_query(collection, schema, where, search, search_fields, within),
            **options,
        )

    def rows(
        self,
        collection: str | None,
        schema: str,
        *,
        where: dict[str, Any] | list[str] | None = None,
        search: str | None = None,
        search_fields: list[str] | None = None,
        within: str | None = None,
        **options: Any,
    ) -> list[dict[str, Any]]:
        """`frame`'s rows as a list of dicts of Python values, without
        pandas (`file_access_svc.typed_rows`, all pages)."""
        pages = self.file_access_svc.typed_rows(
            _frame_query(collection, schema, where, search, search_fields, within),
            **options,
        )
        return [row for page in pages for row in page]

    @contextmanager
    def chunked_writes(self) -> Iterator[Callable[[], None]]:
        """For work that changes a great many rows (a bulk edit): it writes a
        chunk, calls the `turn` this yields, writes the next. `turn` commits
        (so SQLite's one write lock is held for a chunk, never for the whole
        job) and, when another writer asked for the lock meanwhile, waits
        `GIVE_WAY_SECONDS` before going on, so a person's save goes in between
        two chunks instead of waiting for the job, or failing after
        `busy_timeout`.

        It is the gate index builds give way through (`db/index_gate`), not a
        second one: while the work runs, every other connection's write
        touches the wait file (`upkeep`), and `quiet_for` says whether one
        has since the last turn. The work's own connection is marked as the
        builder's is, so its own writes ask nothing. PostgreSQL locks rows,
        not the database: there `turn` only commits."""
        from civex.db import index_gate

        bind = self._session.get_bind()
        db = (
            index_gate.sqlite_file(bind.url.database)  # type: ignore[union-attr]
            if bind.dialect.name == "sqlite"
            else None
        )
        if db is None:
            yield self.commit
            return
        # The marks are kept by the dict they are in (a connection's own,
        # which outlives the transaction), so one can come off after its
        # transaction has ended (whatever committed it).
        marked: list[dict[Any, Any]] = []

        def mark() -> None:
            info = self._session.connection().info
            info[index_gate.BUILDER] = True
            marked.append(info)

        def unmark() -> None:
            while marked:
                marked.pop().pop(index_gate.BUILDER, None)

        began = [time.time()]

        def turn() -> None:
            # Everything still to be written goes while the connection is
            # marked as this work's own; then the mark comes off (while the
            # connection is still this transaction's) and it commits.
            self._session.flush()
            unmark()
            self.commit()
            if index_gate.quiet_for(db) <= time.time() - began[0]:
                time.sleep(GIVE_WAY_SECONDS)
            began[0] = time.time()
            mark()

        with index_gate.upkeep(db):
            mark()
            try:
                yield turn
            finally:
                unmark()

    @contextmanager
    def all_or_nothing(self) -> Iterator[None]:
        """Keep everything done inside it, or, when it raises, nothing: a SQL
        SAVEPOINT, rolled back on an exception and released otherwise.
        Nothing is committed either way, so what came before it (a workflow
        run's claim) stays, and the caller commits once with the outcome.
        `JobCancelled` keeps what was done: a run stopped on purpose keeps
        what it got through."""
        from civex.domain.exceptions import JobCancelled

        nested = self._session.begin_nested()
        try:
            yield
        except JobCancelled:
            if nested.is_active:
                nested.commit()
            raise
        except BaseException:
            if nested.is_active:
                nested.rollback()
            raise
        else:
            if nested.is_active:
                nested.commit()

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


def _frame_query(
    collection: str | None,
    schema: str,
    where: dict[str, Any] | list[str] | None,
    search: str | None,
    search_fields: list[str] | None,
    within: str | None,
) -> RecordQuery:
    """The query `AppContext.frame`/`rows` take apart as keyword arguments."""
    return RecordQuery(
        dataset=collection,
        schema=schema,
        within=within,
        filter_tree=where if isinstance(where, dict) else None,
        where=list(where) if isinstance(where, list) else [],
        search=search,
        search_fields=search_fields,
    )


# How a background host opens a context when it needs one: a fresh session
# each time, on whichever project the host serves.
ContextFactory = Callable[[], "AppContext"]

# How long chunked work waits, after a chunk, when another writer asked for
# the database meanwhile: longer than SQLite's longest pause between a waiting
# writer's tries (100 ms), so the writer gets the lock.
GIVE_WAY_SECONDS = 0.15


def local_context() -> AppContext:
    """A context on the project in the current directory: what `civex serve`
    and the CLI host. The one factory the server's background jobs default to."""
    from civex.config import load_config

    return build_local_context(load_config())


def context_factory(project: Project) -> ContextFactory:
    """A factory opening fresh contexts on `project`, for work that outlives
    the request that asked for it (a run drained in the background)."""
    return lambda: build_context(project)


def make_store(config: Config, session: "Session | None" = None) -> "ObjectStore":
    """The object store a project's settings name: a bucket when `[store.s3]`
    is set, else the drives of `[store.volumes]` on this machine."""
    s3 = config.store_config.s3
    if s3 is not None:
        from civex.repositories.s3.store import S3ObjectStore

        return S3ObjectStore(s3, session=session)
    from civex.repositories.local.file_store import VolumeAwareFileObjectStore

    return VolumeAwareFileObjectStore(
        config.store_config, config.project_root, session=session
    )


def open_project(path: str | os.PathLike[str] | None = None) -> AppContext:
    """The project in the folder `path` (or a folder above it; the current
    directory by default), opened in this process: the same services the CLI
    and the server use, with no server running. `civex.open` is this.

    Use it as a context manager to commit on success and roll back on an
    error, or call `commit()` and `close()` yourself. Raises ConfigError when
    there is no project there and DatabaseTooNewError when the database was
    upgraded by a newer civex."""
    from civex.config import find_project_root, load_config_at
    from civex.domain.exceptions import ConfigError

    start = Path(path).expanduser() if path is not None else None
    root = find_project_root(start)
    if root is None:
        where = start or Path.cwd()
        raise ConfigError(
            f"No civex project at or above {where}. Run `civex init` there to "
            "create one."
        )
    return build_local_context(load_config_at(root))


def build_local_context(
    config: Config,
    file_store: ObjectStore | None = None,
) -> AppContext:
    """A context on the project in a folder on this machine: its settings in
    its config.toml, changes recorded as its chosen name or the OS user."""
    return build_context(Project.local(config), file_store)


_READ_ONLY_ENGINES: weakref.WeakKeyDictionary[Engine, Engine] = (
    weakref.WeakKeyDictionary()
)


def _read_only_engine(engine: Engine) -> Engine:
    """`engine`, sharing its pool, with every transaction read-only and on one
    snapshot (REPEATABLE READ, so a streamed export reading twice sees the same
    rows). Made once per engine."""
    ro = _READ_ONLY_ENGINES.get(engine)
    if ro is None:
        ro = engine.execution_options(
            postgresql_readonly=True, isolation_level="REPEATABLE READ"
        )
        _READ_ONLY_ENGINES[engine] = ro
    return ro


def uses_read_engine(project: Project, read_only: bool) -> bool:
    """Whether a context built `read_only` for `project` is served by its read
    engine: only when the project has one, the request doesn't need the
    primary, and the database is PostgreSQL (SQLite has no replicas)."""
    replica = project.read_engine
    return (
        read_only
        and replica is not None
        and not project.needs_primary
        and replica.dialect.name == "postgresql"
        # A project following an authority keeps its sync position in the
        # database, in a row a read may have to create: primary only.
        and project.config.sync.remote is None
    )


def build_context(
    project: Project,
    file_store: ObjectStore | None = None,
    *,
    read_only: bool = False,
) -> AppContext:
    """The services for `project`. `read_only=True` is the caller promising to
    only read: the context is then served by `project.read_engine` when there
    is one (see `uses_read_engine`), in a read-only transaction that refuses
    any write. Only the routes and methods that are replica-safe by design ask
    for it (`server.deps.get_read_ctx`); everything else, and anything inside a
    write transaction, gets the primary."""
    from sqlalchemy.orm import Session

    from civex.db.migrate import ensure_audit_partitions_daily, ensure_schema_current
    from civex.repositories.local.audit_repo import LocalAuditRepository
    from civex.repositories.local.dataset_repo import LocalDatasetRepository
    from civex.repositories.local.file_ref_repo import LocalFileReferenceRepository
    from civex.repositories.local.job_repo import LocalWorkflowJobRepository
    from civex.repositories.local.record_repo import LocalRecordRepository
    from civex.repositories.local.schema_repo import LocalSchemaRepository
    from civex.repositories.local.export_definition_repo import (
        LocalExportDefinitionRepository,
    )
    from civex.repositories.local.view_repo import LocalViewRepository
    from civex.repositories.local.dashboard_repo import LocalDashboardRepository
    from civex.repositories.local.note_repo import LocalNoteRepository
    from civex.services.dashboard_service import DashboardService
    from civex.services.note_service import NoteService
    from civex.services.ai.service import AiService
    from civex.services.ai_usage_service import AiUsageService
    from civex.services.analytics_service import AnalyticsService
    from civex.services.audit_service import AuditService
    from civex.services.container_plugin_service import ContainerPluginService
    from civex.services.dataset_service import DatasetService
    from civex.services.file_service import FileService
    from civex.services.gc_service import GCService
    from civex.services.file_access_service import FileAccessService
    from civex.services.import_service import ImportService
    from civex.services.file_info_service import FileInfoService
    from civex.repositories.local.transfer_repo import LocalTransferRepository
    from civex.services.transfer_service import TransferService
    from civex.services.plugin_service import PluginService
    from civex.services.policy_service import PolicyService
    from civex.services.quality_service import QualityService
    from civex.services.record_service import RecordService
    from civex.services.retention_service import RetentionService
    from civex.services.schema_service import SchemaService
    from civex.services.bucket_service import BucketService
    from civex.services.store_service import StoreService
    from civex.repositories.local.file_store import VolumeAwareFileObjectStore
    from civex.services.bundle_service import BundleService
    from civex.services.export_definition_service import ExportDefinitionService
    from civex.services.view_service import ViewService
    from civex.services.workflow_job_service import WorkflowJobService
    from civex.services.workflow_service import WorkflowService
    from civex.repositories.protocols import VolumeStore
    from civex.repositories.local import inventory
    from civex.repositories.s3.store import boto_client

    config = project.config
    engine = project.engine or _get_engine(config.db.url)
    if not project.migrated:
        ensure_schema_current(engine, PartitionLayout.for_config(config.db))
    # A server that stays up for months needs next month's audit partition:
    # at most one cheap check a day per engine.
    ensure_audit_partitions_daily(
        engine, PartitionLayout.for_config(config.db).audit_months_ahead
    )
    on_read_engine = uses_read_engine(project, read_only)
    session_engine: Engine
    if on_read_engine:
        assert project.read_engine is not None
        # Never migrated from here (a replica can't be); the read-only
        # transaction makes a stray write an error rather than a lost update.
        session_engine = _read_only_engine(project.read_engine)
    else:
        session_engine = engine
    session = Session(session_engine)
    if on_read_engine:
        # Connect now, so an unreachable replica fails here, where the host
        # can fall back to the primary, not at some later query.
        try:
            session.connection()
        except BaseException:
            session.close()
            raise
    from civex.db import read_scope

    # A collection this caller may not read is not there for any query below.
    read_scope.install(session, project.permissions.read_scope)
    schema_repo = LocalSchemaRepository(session)
    dataset_repo = LocalDatasetRepository(session)
    record_repo = LocalRecordRepository(
        session, is_postgres=session_engine.dialect.name == "postgresql"
    )
    job_repo = LocalWorkflowJobRepository(session)
    device_id = project.device_id
    if device_id is None and config.sync.remote:
        # Syncing: every entry written here carries which device made it.
        from civex import user_state
        from civex.repositories.local.sync_repo import LocalSyncRepository as _Sync

        device_id = user_state.device_id_for(_Sync(session).meta().project_id)
    audit_repo = LocalAuditRepository(session, actor=project.actor, device_id=device_id)
    view_repo = LocalViewRepository(session)
    if file_store is None:
        file_store = make_store(config, session)
    # The drives on this machine, when that is where the files are: what the
    # services that lay files out on disk or move them between drives need.
    volumes: VolumeStore | None = (
        file_store if isinstance(file_store, VolumeStore) else None
    )

    may = project.permissions
    schema_svc = SchemaService(schema_repo, audit_repo, record_repo, permissions=may)
    job_svc = WorkflowJobService(job_repo, config.civex_dir, project.config_store)
    record_svc = RecordService(
        schema_svc,
        dataset_repo,
        record_repo,
        file_store,
        job_svc,
        audit_repo,
        permissions=may,
    )
    schema_svc.use_chart_check(record_svc.check_chart)
    note_svc = NoteService(
        LocalNoteRepository(session),
        record_repo,
        record_svc.resolve,
        audit_repo,
        permissions=may,
        actor=project.actor,
    )
    dataset_svc = DatasetService(
        dataset_repo,
        audit_repo,
        record_svc,
        on_purge=lambda collection_id: (
            store_svc.clear_placement(str(collection_id)) if store_svc else None
        ),
        permissions=may,
    )
    file_svc = FileService(file_store, volumes, permissions=may)
    if not may.read_scope().unrestricted:
        file_refs = LocalFileReferenceRepository(session)
        file_svc.readable = file_refs.is_readable

        def _readable_many(shas):
            # What `is_readable` answers, for many (two queries per chunk).
            return {
                sha
                for sha, (seen, used) in file_refs.uses(shas).items()
                if seen or not used
            }

        file_svc.readable_many = _readable_many
        record_svc.readable = file_svc.readable

        def _may_cite(sha: str) -> bool:
            # Every question is asked whatever the answers, so the time taken
            # says nothing about which kind of hash this is.
            readable = file_svc.readable(sha)
            here = file_svc.exists(sha)
            used = bool(LocalFileReferenceRepository(session).referenced_subset([sha]))
            return readable and (here or used)

        record_svc.may_cite = _may_cite
        record_svc.as_caller = lambda: read_scope.scoped(session)
    store_svc: StoreService | None = None
    if isinstance(file_store, VolumeAwareFileObjectStore):
        store_svc = StoreService(config, file_store, project.config_store)
    gc_svc = GCService(file_store, LocalFileReferenceRepository(session))
    file_info_svc = FileInfoService(
        file_store, LocalFileReferenceRepository(session), dataset_repo
    )

    def _describe_records(ids: list[uuid.UUID]) -> list[RecordUse]:
        records = record_svc.get_many([str(i) for i in ids])
        trails = record_svc.ancestor_trails(records)
        return [
            RecordUse(
                id=str(r.id),
                name=r.natural_name or str(r.id)[:8],
                collection=r.dataset_name,
                trail=[a.natural_name or str(a.id)[:8] for a in trails.get(r.id, [])],
            )
            for r in records
        ]

    file_info_svc.describe_records = _describe_records
    file_access_svc = FileAccessService(
        record_svc, schema_svc, file_store, config.civex_dir, volumes
    )
    file_access_svc.refs = LocalFileReferenceRepository(session)
    import_svc = ImportService()
    transfer_svc: TransferService | None = None
    if volumes is not None and store_svc is not None:
        transfer_svc = TransferService(
            config,
            volumes,
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
    view_svc = ViewService(
        view_repo, schema_svc, record_svc, audit_repo, permissions=may
    )
    export_def_svc = ExportDefinitionService(
        LocalExportDefinitionRepository(session),
        schema_svc,
        record_svc,
        permissions=may,
    )
    history_svc = AuditService(
        audit_repo,
        schema_svc,
        record_svc,
        dataset_svc,
        file_store,
        # `sync_svc` is built below; history only asks for it when it is read.
        sync_conflicts=lambda ids: sync_svc.conflicts_of_entries(ids),
    )

    retention_svc = RetentionService(
        record_svc,
        dataset_svc,
        schema_svc,
        audit_repo,
        job_repo,
        config.retention,
        # While this project syncs, history the authority hasn't taken yet is
        # the only copy of those changes, so a clean-up keeps it.
        config.sync.remote is not None,
    )

    from civex.repositories.local.sync_repo import LocalSyncRepository
    from civex.services.sync_applier import SyncApplier
    from civex.services.project_rules import ProjectRules
    from civex.repositories.local.db_space import LocalDbSpace
    from civex.services.history_compaction import HistoryCompactionService
    from civex.services.device_keys import DeviceKeys
    from civex.services.sync_authority import SyncAuthorityService

    from civex.domain.sync import CAPABILITIES, DIRECT_FILES
    from civex.services.sync_service import SyncService
    from civex.services.sync_transport import build_transport

    from civex.repositories.local.release_repo import LocalReleaseRepository

    release_repo = LocalReleaseRepository(session)
    sync_repo = LocalSyncRepository(session)
    quality_svc = QualityService(record_svc, schema_svc, permissions=may)
    # A copy that was told it may read only some collections holds only some
    # of the records: what it finds says nothing of the rest.
    quality_svc.partial = lambda: sync_repo.readable() is not None
    applier = SyncApplier(sync_repo, audit_repo)
    device_keys = DeviceKeys(sync_repo)
    authority_svc = SyncAuthorityService(
        sync_repo,
        applier,
        file_store,
        record_svc,
        ProjectRules(schema_svc, record_repo),
        authenticator=device_keys,
        # The authority settles a push against the whole project, then asks the
        # policy about each thing: a hidden collection must not look empty to it.
        unscoped=lambda: read_scope.unscoped(session),
        readable=(None if may.read_scope().unrestricted else file_svc.readable),
        uses=(
            None
            if may.read_scope().unrestricted
            else LocalFileReferenceRepository(session).uses
        ),
        sees=(None if may.read_scope().unrestricted else may.read_scope().sees),
        scope=may.read_scope,
        # The same answer a person at a browser gets, asked of each change a
        # device pushes (the local user's refuses nothing).
        policy=may,
        notes=note_svc,
        capabilities=CAPABILITIES
        + ((DIRECT_FILES,) if features.DIRECT_FILES in project.features else ())
        + (("file_parts",) if file_svc.takes_parts else ()),
    )
    sync_svc = SyncService(
        config,
        sync_repo,
        applier,
        audit_repo,
        file_store,
        session.commit,
        build_transport,
        record_svc,
        project.config_store,
    )

    # Files another device added are fetched from the authority when opened or
    # exported, and say so meanwhile (asked each time: a project can start
    # following one while this context is open).
    def _sync() -> SyncService:
        return ctx.sync_svc  # whatever stands in for it by then (tests wrap it)

    record_svc.files_from_server = lambda: _sync().fetches_files
    record_svc.not_on_server = lambda shas: _sync().not_on_server(shas)
    record_svc.server_lacks = lambda shas: _sync().server_lacks(shas)

    def _recently_received(
        cited: dict[uuid.UUID, set[str]],
    ) -> set[tuple[uuid.UUID, str]]:
        hours = config.sync.arriving_hours
        if hours <= 0:
            return set()
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        return sync_repo.received_since(cited, since)

    record_svc.recently_received = _recently_received
    record_svc.why_not_here = lambda shas: _sync().not_here_reasons(shas)
    file_info_svc.files_from_server = lambda: _sync().fetches_files
    file_access_svc.fetch_missing = (
        lambda shas, on_file=None, volume=None, on_bytes=None: _sync().fetch_files(
            shas=shas, progress=on_file, volume=volume, on_bytes=on_bytes
        )
    )
    file_access_svc.free_files = lambda shas, dry: _sync().free_up_files(
        shas, dry_run=dry
    )
    file_access_svc.why_not_here = lambda shas: _sync().not_here_reasons(shas)

    from civex.repositories.local.field_index_repo import LocalFieldIndexRepository
    from civex.services.index_service import IndexService

    index_svc = IndexService(
        LocalFieldIndexRepository(session),
        schema_svc,
        project.config_store,
        permissions=may,
    )

    from civex.services.release_service import ReleaseService

    bundle_svc = BundleService(
        schema_svc,
        dataset_svc,
        record_svc,
        file_svc,
        session.commit,
        config.civex_dir,
        batch=history_svc.batch,
        after_bulk_write=index_svc.after_bulk_write,
    )
    bundle_svc.fetch_missing = lambda shas: _sync().fetch_files(shas=shas)
    release_svc = ReleaseService(
        release_repo,
        bundle_svc,
        file_store,
        audit_repo,
        permissions=may,
        actor=project.actor,
        collections=lambda: {
            d.id: d.name for d in dataset_svc.list_all(with_count=False)
        },
        refs=LocalFileReferenceRepository(session),
    )
    release_svc.position = lambda: _sync().history_position()
    release_svc.fetch = lambda sha: _sync().fetch_file(sha)
    release_svc.keeps_files = lambda: not _sync().fetches_files
    release_svc.files = file_access_svc
    release_svc.locate = record_svc.locate_pointed
    release_svc.savepoint = lambda: ctx.all_or_nothing()
    release_svc.structure = lambda: release_rules.structure_of(
        schema_svc.list_all(), dataset_svc.list_all(with_count=False)
    )
    release_svc.records_by_id = lambda ids: record_svc.get_many(ids)
    release_svc.read_back = lambda shas, progress=None: file_store.verify(
        shas, progress
    )

    from civex.repositories.local.library_repo import LocalLibraryRepository
    from civex.services.library_service import LibraryService

    library_svc = LibraryService(
        LocalLibraryRepository(session),
        sync_repo,
        config,
        workflow_svc,
        plugin_svc,
        transport=lambda: _sync().transport(),
        author=lambda: project.actor,
    )

    ctx: AppContext = AppContext(
        schema_svc=schema_svc,
        dataset_svc=dataset_svc,
        record_svc=record_svc,
        file_svc=file_svc,
        job_svc=job_svc,
        gc_svc=gc_svc,
        file_info_svc=file_info_svc,
        file_access_svc=file_access_svc,
        import_svc=import_svc,
        audit_svc=audit_repo,
        history_svc=history_svc,
        compaction_svc=HistoryCompactionService(
            audit_repo,
            LocalDbSpace(engine, may_vacuum_full=features.DB_ADMIN in project.features),
        ),
        quality_svc=quality_svc,
        index_svc=index_svc,
        retention_svc=retention_svc,
        ai_svc=ai_svc,
        ai_usage_svc=ai_usage_svc,
        analytics_svc=analytics_svc,
        workflow_svc=workflow_svc,
        plugin_svc=plugin_svc,
        container_plugin_svc=container_plugin_svc,
        policy_svc=policy_svc,
        view_svc=view_svc,
        dashboard_svc=DashboardService(
            LocalDashboardRepository(session),
            schema_svc,
            record_svc,
            dataset_repo,
            audit_repo,
            permissions=may,
        ),
        note_svc=note_svc,
        release_svc=release_svc,
        export_def_svc=export_def_svc,
        bundle_svc=bundle_svc,
        sync_repo=sync_repo,
        authority_svc=authority_svc,
        device_keys=device_keys,
        sync_svc=sync_svc,
        library_svc=library_svc,
        bucket_svc=BucketService(
            project.config_store,
            held=lambda: inventory.held(session),
            client_for=boto_client,
        ),
        project=project,
        _session=session,
        _store_svc=store_svc,
        _transfer_svc=transfer_svc,
        on_read_engine=on_read_engine,
    )
    ai_svc._app_ctx = ctx
    import_svc._app_ctx = ctx
    return ctx
