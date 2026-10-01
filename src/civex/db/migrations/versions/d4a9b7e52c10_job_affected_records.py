"""job_affected_records: indexed link from a workflow run to the records it touched

"Runs that touched this record" (on every record's page) filtered jobs by the
`affected_records` JSON in Python: every job loaded, with its step executions,
on each view. This table holds one row per (job, record), so it is an indexed
lookup. Backfilled here from each job's existing `affected_records`.

Revision ID: d4a9b7e52c10
Revises: c3f8a1d27e64
Create Date: 2026-10-01 00:00:00.000000
"""

from __future__ import annotations

import uuid
from typing import Iterable, Sequence, Union

from alembic import op
import sqlalchemy as sa

import civex.db.models

revision: str = "d4a9b7e52c10"
down_revision: Union[str, None] = "c3f8a1d27e64"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BATCH = 2000
_JSON = civex.db.models._JSON


def _batched(rows: Iterable, n: int = _BATCH):
    batch: list = []
    for row in rows:
        batch.append(row)
        if len(batch) >= n:
            yield batch
            batch = []
    if batch:
        yield batch


def _backfill() -> None:
    bind = op.get_bind()
    jobs = sa.table(
        "workflow_jobs",
        sa.column("id", sa.Uuid()),
        sa.column("affected_records", _JSON),
    )
    links = sa.table(
        "job_affected_records",
        sa.column("job_id", sa.Uuid()),
        sa.column("record_id", sa.Uuid()),
    )

    def _rows():
        stream = bind.execute(
            sa.select(jobs.c.id, jobs.c.affected_records).where(
                jobs.c.affected_records.is_not(None)
            ),
            execution_options={"stream_results": True},
        )
        for job_id, affected in stream:
            seen: set[uuid.UUID] = set()
            for entry in affected or []:
                raw = entry.get("record_id") if isinstance(entry, dict) else None
                try:
                    record_id = uuid.UUID(str(raw))
                except ValueError:
                    continue
                if record_id not in seen:
                    seen.add(record_id)
                    yield {"job_id": job_id, "record_id": record_id}

    for batch in _batched(_rows()):
        bind.execute(sa.insert(links), batch)


def upgrade() -> None:
    op.create_table(
        "job_affected_records",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["workflow_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id", "record_id"),
    )
    op.create_index(
        "ix_job_affected_records_record", "job_affected_records", ["record_id"]
    )
    _backfill()


def downgrade() -> None:
    op.drop_index("ix_job_affected_records_record", table_name="job_affected_records")
    op.drop_table("job_affected_records")
