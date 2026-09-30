from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from civex.config import Config, save_config
from civex.repositories.local.audit_repo import LocalAuditRepository
from civex.repositories.protocols import FileObjectStore
from civex.sync.exporter import export_bundle
from civex.sync.importer import apply_bundle
from civex.sync.transport import SyncError, get_transport

log = logging.getLogger(__name__)


@dataclass
class SyncResult:
    schemas: int
    datasets: int
    records: int
    objects: int
    from_seq: int
    to_seq: int

    @property
    def is_empty(self) -> bool:
        return self.to_seq == self.from_seq


class SyncService:
    """Encapsulates push and pull logic shared by the CLI and the HTTP server."""

    def __init__(
        self,
        config: Config,
        session: Session,
        audit_repo: LocalAuditRepository,
        file_store: FileObjectStore,
    ) -> None:
        self._config = config
        self._session = session
        self._audit_repo = audit_repo
        self._file_store = file_store

    def _transport(self):
        if self._config.remote is None:
            raise SyncError("No remote configured. Run `civex remote set <url>` first.")
        transport, _ = get_transport(
            self._config.remote.url,
            remote_civex=self._config.remote.remote_civex,
        )
        return transport

    def push(self) -> SyncResult:
        if self._config.remote is None:
            raise SyncError("No remote configured. Run `civex remote set <url>` first.")

        transport = self._transport()
        remote = self._config.remote

        # Auto-commit any staged changes so they're included in the push.
        staged = self._audit_repo.count_staged()
        if staged["total"] > 0:
            self._audit_repo.create_commit(message="push")
            self._session.commit()

        bundle = export_bundle(self._session, remote.last_pushed_seq)
        unpushed_ids = [c.id for c in self._audit_repo.list_unpushed_commits()]

        if bundle.to_seq == remote.last_pushed_seq:
            return SyncResult(
                schemas=0,
                datasets=0,
                records=0,
                objects=0,
                from_seq=remote.last_pushed_seq,
                to_seq=remote.last_pushed_seq,
            )

        # Push objects before the DB bundle so the receiver can access them immediately.
        pushed_objects = 0
        for sha256 in bundle.object_refs:
            if self._file_store.exists(sha256):
                try:
                    transport.put_object(sha256, self._file_store.get(sha256))
                    pushed_objects += 1
                except SyncError as e:
                    # One object failing to push (network blip, remote out
                    # of space) shouldn't abort the whole push -- the DB
                    # bundle itself still goes out below -- but a silent
                    # skip here previously gave no way to tell why
                    # `objects` in the result came back lower than expected.
                    log.warning("Failed to push object %s: %s", sha256, e)

        transport.receive_pack(bundle)

        remote.last_pushed_seq = bundle.to_seq
        remote.last_pushed_at = datetime.now(timezone.utc)
        save_config(self._config)

        if unpushed_ids:
            self._audit_repo.mark_pushed(unpushed_ids)
            self._session.commit()

        return SyncResult(
            schemas=len(bundle.schemas),
            datasets=len(bundle.datasets),
            records=len(bundle.records),
            objects=pushed_objects,
            from_seq=bundle.from_seq,
            to_seq=bundle.to_seq,
        )

    def pull(self) -> SyncResult:
        if self._config.remote is None:
            raise SyncError("No remote configured. Run `civex remote set <url>` first.")

        transport = self._transport()
        remote = self._config.remote

        bundle = transport.transfer_pack(since_seq=remote.last_pulled_seq)

        if bundle.to_seq == remote.last_pulled_seq:
            return SyncResult(
                schemas=0,
                datasets=0,
                records=0,
                objects=0,
                from_seq=remote.last_pulled_seq,
                to_seq=remote.last_pulled_seq,
            )

        apply_bundle(self._session, bundle)
        self._session.commit()

        remote.last_pulled_seq = bundle.to_seq
        remote.last_pulled_at = datetime.now(timezone.utc)
        save_config(self._config)

        return SyncResult(
            schemas=len(bundle.schemas),
            datasets=len(bundle.datasets),
            records=len(bundle.records),
            objects=len(bundle.object_refs),
            from_seq=bundle.from_seq,
            to_seq=bundle.to_seq,
        )
