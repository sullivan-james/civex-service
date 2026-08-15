from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from civex.db.models import AuditLog, Commit
from civex.domain.dtos import AuditLogDTO, CommitDTO
from civex.repositories.local._bucketing import day_bucket
from civex.repositories.protocols import AuditEventRow


class LocalAuditRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    # ------------------------------------------------------------------
    # Write-side (satisfies AuditRepository protocol — called by services)
    # ------------------------------------------------------------------

    def log_change(
        self,
        action: str,
        entity_type: str,
        entity_id: uuid.UUID,
        old_data: dict[str, Any] | None,
        new_data: dict[str, Any] | None,
    ) -> None:
        self._s.add(
            AuditLog(
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                old_data=old_data,
                new_data=new_data,
                timestamp=datetime.now(timezone.utc),
            )
        )

    def event_counts_by_period(
        self,
        start: datetime | None,
        end: datetime | None,
        entity_type: str | None = None,
        action: str | None = None,
    ) -> list[AuditEventRow]:
        """Audit entries per day, broken out by action and entity_type --
        backs the activity-over-time widget. `entity_type`/`action` narrow
        to a single value each; the breakdown itself is never collapsed."""
        day = day_bucket(AuditLog.timestamp)
        q = self._s.query(
            day, AuditLog.action, AuditLog.entity_type, func.count(AuditLog.id)
        )
        if start is not None:
            q = q.filter(AuditLog.timestamp >= start)
        if end is not None:
            q = q.filter(AuditLog.timestamp < end)
        if entity_type is not None:
            q = q.filter(AuditLog.entity_type == entity_type)
        if action is not None:
            q = q.filter(AuditLog.action == action)
        rows = (
            q.group_by(day, AuditLog.action, AuditLog.entity_type).order_by(day).all()
        )
        return [
            (d, action, entity_type, count) for d, action, entity_type, count in rows
        ]

    # ------------------------------------------------------------------
    # Commit management (used by AuditService / CLI)
    # ------------------------------------------------------------------

    def create_commit(self, message: str | None = None) -> CommitDTO:
        staged = self._staged_entries()
        if not staged:
            raise ValueError("Nothing to commit — no staged changes")

        record_count = sum(1 for e in staged if e.entity_type == "record")
        schema_count = sum(1 for e in staged if e.entity_type in ("schema", "field"))
        dataset_count = sum(1 for e in staged if e.entity_type == "dataset")

        next_seq = (self._s.query(func.max(Commit.seq)).scalar() or 0) + 1
        commit = Commit(
            seq=next_seq,
            message=message,
            record_count=record_count,
            schema_count=schema_count,
            dataset_count=dataset_count,
        )
        self._s.add(commit)
        self._s.flush()

        for entry in staged:
            entry.commit_id = commit.id

        self._s.flush()
        return _commit_dto(commit)

    def count_staged(self) -> dict[str, int]:
        staged = self._staged_entries()
        return {
            "total": len(staged),
            "records": sum(1 for e in staged if e.entity_type == "record"),
            "schemas": sum(1 for e in staged if e.entity_type in ("schema", "field")),
            "datasets": sum(1 for e in staged if e.entity_type == "dataset"),
        }

    def list_commits(self, limit: int = 50, offset: int = 0) -> list[CommitDTO]:
        rows = (
            self._s.query(Commit)
            .order_by(Commit.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [_commit_dto(r) for r in rows]

    def list_audit(
        self,
        entity_id: uuid.UUID | None = None,
        entity_type: str | None = None,
        commit_id: uuid.UUID | None = None,
        entity_ids: list[uuid.UUID] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditLogDTO]:
        q = self._audit_query(entity_id, entity_type, commit_id, entity_ids)
        return [
            _audit_dto(r)
            for r in q.order_by(AuditLog.timestamp.desc())
            .offset(offset)
            .limit(limit)
            .all()
        ]

    def count_audit(
        self,
        entity_id: uuid.UUID | None = None,
        entity_type: str | None = None,
        commit_id: uuid.UUID | None = None,
        entity_ids: list[uuid.UUID] | None = None,
    ) -> int:
        return self._audit_query(entity_id, entity_type, commit_id, entity_ids).count()

    def _audit_query(
        self,
        entity_id: uuid.UUID | None,
        entity_type: str | None,
        commit_id: uuid.UUID | None,
        entity_ids: list[uuid.UUID] | None,
    ):
        q = self._s.query(AuditLog)
        if entity_ids is not None:
            q = q.filter(AuditLog.entity_id.in_(entity_ids))
        elif entity_id is not None:
            q = q.filter(AuditLog.entity_id == entity_id)
        if entity_type is not None:
            q = q.filter(AuditLog.entity_type == entity_type)
        if commit_id is not None:
            q = q.filter(AuditLog.commit_id == commit_id)
        return q

    def list_unpushed_commits(self) -> list[CommitDTO]:
        rows = (
            self._s.query(Commit)
            .filter(Commit.pushed_at.is_(None))
            .order_by(Commit.created_at)
            .all()
        )
        return [_commit_dto(r) for r in rows]

    def list_audit_for_commits(self, commit_ids: list[uuid.UUID]) -> list[AuditLogDTO]:
        if not commit_ids:
            return []
        rows = (
            self._s.query(AuditLog)
            .filter(AuditLog.commit_id.in_(commit_ids))
            .order_by(AuditLog.timestamp)
            .all()
        )
        return [_audit_dto(r) for r in rows]

    def upsert_commit(self, d: dict) -> None:
        uid = uuid.UUID(d["id"])
        existing = self._s.get(Commit, uid)
        pushed_at = _parse_dt(d.get("pushed_at"))
        if existing is None:
            self._s.add(
                Commit(
                    id=uid,
                    message=d.get("message"),
                    created_at=_parse_dt(d.get("created_at"))
                    or datetime.now(timezone.utc),
                    record_count=d.get("record_count", 0),
                    schema_count=d.get("schema_count", 0),
                    dataset_count=d.get("dataset_count", 0),
                    pushed_at=pushed_at,
                )
            )
        else:
            existing.message = d.get("message")
            if pushed_at and not existing.pushed_at:
                existing.pushed_at = pushed_at

    def upsert_audit_entry(self, d: dict) -> None:
        uid = uuid.UUID(d["id"])
        if self._s.get(AuditLog, uid) is None:
            self._s.add(
                AuditLog(
                    id=uid,
                    commit_id=uuid.UUID(d["commit_id"]) if d.get("commit_id") else None,
                    action=d["action"],
                    entity_type=d["entity_type"],
                    entity_id=uuid.UUID(d["entity_id"]),
                    old_data=d.get("old_data"),
                    new_data=d.get("new_data"),
                    timestamp=_parse_dt(d.get("timestamp"))
                    or datetime.now(timezone.utc),
                )
            )

    def mark_pushed(self, commit_ids: list[uuid.UUID]) -> None:
        now = datetime.now(timezone.utc)
        for cid in commit_ids:
            row = self._s.get(Commit, cid)
            if row:
                row.pushed_at = now

    def _staged_entries(self) -> list[AuditLog]:
        return self._s.query(AuditLog).filter(AuditLog.commit_id.is_(None)).all()


def _commit_dto(r: Commit) -> CommitDTO:
    return CommitDTO(
        id=r.id,
        seq=r.seq,
        message=r.message,
        created_at=r.created_at,
        record_count=r.record_count,
        schema_count=r.schema_count,
        dataset_count=r.dataset_count,
        pushed_at=r.pushed_at,
    )


def _audit_dto(r: AuditLog) -> AuditLogDTO:
    return AuditLogDTO(
        id=r.id,
        commit_id=r.commit_id,
        action=r.action,
        entity_type=r.entity_type,
        entity_id=r.entity_id,
        old_data=r.old_data,
        new_data=r.new_data,
        timestamp=r.timestamp,
    )


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
