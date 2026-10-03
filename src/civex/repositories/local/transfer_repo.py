from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from civex.db.models import StorageTransfer
from civex.domain.transfers import (
    STATUS_RUNNING,
    TargetShare,
    TransferFailure,
    TransferPlan,
    TransferProgress,
    TransferRecord,
    TransferSpec,
)


def _plan_from(data: dict[str, Any] | None) -> TransferPlan | None:
    if data is None:
        return None
    return TransferPlan(
        **{**data, "targets": [TargetShare(**t) for t in data.get("targets", [])]}
    )


def _to_record(row: StorageTransfer) -> TransferRecord:
    return TransferRecord(
        id=str(row.id),
        kind=row.kind,
        status=row.status,
        spec=TransferSpec(**row.spec),
        progress=TransferProgress(**row.progress),
        plan=_plan_from(row.plan),
        failures=[TransferFailure(**f) for f in row.failures],
        failures_total=row.failures_total,
        pause_reason=row.pause_reason,
        auto_resume=row.auto_resume,
        error=row.error,
        control=row.control,
        frozen=dict(row.frozen),
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        updated_at=row.updated_at,
    )


def _asdict(value: Any) -> dict[str, Any]:
    from dataclasses import asdict

    return asdict(value)


class LocalTransferRepository:
    """The saved account of each transfer. The caller commits."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def create(self, record: TransferRecord) -> None:
        now = datetime.now(timezone.utc)
        self._s.add(
            StorageTransfer(
                id=uuid.UUID(record.id),
                kind=record.kind,
                status=record.status,
                spec=_asdict(record.spec),
                plan=_asdict(record.plan) if record.plan else None,
                progress=_asdict(record.progress),
                failures=[_asdict(f) for f in record.failures],
                failures_total=record.failures_total,
                pause_reason=record.pause_reason,
                auto_resume=record.auto_resume,
                error=record.error,
                control=record.control,
                frozen=dict(record.frozen),
                created_at=record.created_at or now,
                started_at=record.started_at,
                finished_at=record.finished_at,
                updated_at=now,
            )
        )
        self._s.flush()

    def get(self, transfer_id: str) -> TransferRecord | None:
        try:
            key = uuid.UUID(transfer_id)
        except ValueError:
            return None
        row = self._s.get(StorageTransfer, key)
        if row is not None:
            self._s.refresh(row)  # another process may have saved since
        return _to_record(row) if row else None

    def recent(self, limit: int = 50) -> list[TransferRecord]:
        rows = self._s.execute(
            select(StorageTransfer)
            .order_by(StorageTransfer.created_at.desc())
            .limit(limit)
        ).scalars()
        return [_to_record(r) for r in rows]

    def control(self, transfer_id: str) -> str | None:
        """The pause or cancel asked for, read straight from the database (the
        running process asks this as it saves progress)."""
        row = self._s.execute(
            select(StorageTransfer.control).where(
                StorageTransfer.id == uuid.UUID(transfer_id)
            )
        ).first()
        return row[0] if row else None

    def set_control(self, transfer_id: str, value: str | None) -> None:
        self._s.execute(
            update(StorageTransfer)
            .where(StorageTransfer.id == uuid.UUID(transfer_id))
            .values(control=value)
        )
        self._s.flush()

    def running(self) -> list[TransferRecord]:
        rows = self._s.execute(
            select(StorageTransfer).where(StorageTransfer.status == STATUS_RUNNING)
        ).scalars()
        return [_to_record(r) for r in rows]

    def save(self, record: TransferRecord) -> None:
        """Write the record's current state. `updated_at` is set here: it is the
        heartbeat that tells a live transfer from one whose process has died.
        `control` is deliberately not written: a pause someone asks for while
        progress is being saved must not be overwritten by the stale copy."""
        self._s.execute(
            update(StorageTransfer)
            .where(StorageTransfer.id == uuid.UUID(record.id))
            .values(
                status=record.status,
                plan=_asdict(record.plan) if record.plan else None,
                progress=_asdict(record.progress),
                failures=[_asdict(f) for f in record.failures],
                failures_total=record.failures_total,
                pause_reason=record.pause_reason,
                auto_resume=record.auto_resume,
                error=record.error,
                frozen=dict(record.frozen),
                started_at=record.started_at,
                finished_at=record.finished_at,
                updated_at=datetime.now(timezone.utc),
            )
        )
        self._s.flush()
