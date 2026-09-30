"""file reference table, object inventory, job->schema links, scaling indexes

Adds:
  - `file_references`: live record/job -> blob links, so GC is an indexed
    lookup instead of a scan of every record and job. Backfilled here by
    streaming every record's `data` and every job's `input_data`.
  - `stored_objects`: per-blob inventory so volume usage is a SUM, not a
    filesystem walk. Left empty: the object store bootstraps it from disk
    the first time it needs a volume's usage (see VolumeAwareFileObjectStore).
  - `job_affected_schemas`: indexed job <-> schema link, backfilled from the
    `affected_records` JSON's schema names.
  - Indexes for the job queue, audit log, step analytics and record trees.

Revision ID: e5b81c3d7a04
Revises: a1c7e5f93b2d
Create Date: 2026-09-30 00:00:00.000000
"""

from __future__ import annotations

import uuid
from typing import Iterable, Sequence, Union

from alembic import op
import sqlalchemy as sa

import civex.db.models
from civex.domain.file_refs import collect_sha256_refs

revision: str = "e5b81c3d7a04"
down_revision: Union[str, None] = "a1c7e5f93b2d"
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


def _backfill_file_refs() -> None:
    bind = op.get_bind()
    refs = sa.table(
        "file_references",
        sa.column("id", sa.Uuid()),
        sa.column("sha256", sa.String()),
        sa.column("record_id", sa.Uuid()),
        sa.column("job_id", sa.Uuid()),
    )
    records = sa.table("records", sa.column("id", sa.Uuid()), sa.column("data", _JSON))
    jobs = sa.table(
        "workflow_jobs", sa.column("id", sa.Uuid()), sa.column("input_data", _JSON)
    )

    def _pairs(table, col: str, owner: str):
        # Per-statement option: Connection.execution_options() mutates `bind`
        # in place, which would make the INSERTs below use a server-side cursor.
        stream = bind.execute(
            sa.select(table.c.id, table.c[col]),
            execution_options={"stream_results": True},
        )
        for owner_id, payload in stream:
            for sha in collect_sha256_refs(payload):
                yield {
                    "id": uuid.uuid4(),
                    "sha256": sha,
                    "record_id": owner_id if owner == "record_id" else None,
                    "job_id": owner_id if owner == "job_id" else None,
                }

    for table, col, owner in (
        (records, "data", "record_id"),
        (jobs, "input_data", "job_id"),
    ):
        for batch in _batched(_pairs(table, col, owner)):
            bind.execute(sa.insert(refs), batch)


def _backfill_job_affected_schemas() -> None:
    bind = op.get_bind()
    jobs = sa.table(
        "workflow_jobs",
        sa.column("id", sa.Uuid()),
        sa.column("affected_records", _JSON),
    )
    schemas = sa.table(
        "schemas", sa.column("id", sa.Uuid()), sa.column("name", sa.String())
    )
    by_name = {
        name: sid for sid, name in bind.execute(sa.select(schemas.c.id, schemas.c.name))
    }
    links = sa.table(
        "job_affected_schemas",
        sa.column("job_id", sa.Uuid()),
        sa.column("schema_id", sa.Uuid()),
    )

    def _rows():
        stream = bind.execute(
            sa.select(jobs.c.id, jobs.c.affected_records).where(
                jobs.c.affected_records.is_not(None)
            ),
            execution_options={"stream_results": True},
        )
        for job_id, affected in stream:
            names = {
                e.get("schema_name") for e in affected or [] if isinstance(e, dict)
            }
            for name in names:
                if name in by_name:
                    yield {"job_id": job_id, "schema_id": by_name[name]}

    for batch in _batched(_rows()):
        bind.execute(sa.insert(links), batch)


def upgrade() -> None:
    op.create_table(
        "stored_objects",
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("volume", sa.String(length=255), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", civex.db.models._UTCDateTime(timezone=True), nullable=False
        ),
        sa.PrimaryKeyConstraint("sha256"),
    )
    op.create_index("ix_stored_objects_volume", "stored_objects", ["volume"])

    op.create_table(
        "file_references",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "(record_id IS NOT NULL AND job_id IS NULL) "
            "OR (record_id IS NULL AND job_id IS NOT NULL)",
            name="ck_file_references_one_owner",
        ),
        sa.ForeignKeyConstraint(["record_id"], ["records.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["workflow_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", "sha256", name="uq_file_refs_record_sha"),
        sa.UniqueConstraint("job_id", "sha256", name="uq_file_refs_job_sha"),
    )
    op.create_index("ix_file_references_sha256", "file_references", ["sha256"])

    op.create_table(
        "job_affected_schemas",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("schema_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["workflow_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["schema_id"], ["schemas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id", "schema_id"),
    )
    op.create_index(
        "ix_job_affected_schemas_schema", "job_affected_schemas", ["schema_id"]
    )

    _backfill_file_refs()
    _backfill_job_affected_schemas()

    live = sa.text("deleted_at IS NULL")
    op.create_index("ix_records_parent", "records", ["parent_record_id"])
    op.create_index(
        "ix_records_live_dataset_created",
        "records",
        ["dataset_id", "created_at", "id"],
        postgresql_where=live,
        sqlite_where=live,
    )
    op.create_index(
        "ix_records_live_schema_created",
        "records",
        ["schema_id", "created_at", "id"],
        postgresql_where=live,
        sqlite_where=live,
    )

    op.create_index("ix_audit_log_entity", "audit_log", ["entity_id", "timestamp"])
    op.create_index("ix_audit_log_commit", "audit_log", ["commit_id"])
    op.create_index("ix_audit_log_timestamp", "audit_log", ["timestamp"])
    unstaged = sa.text("commit_id IS NULL")
    op.create_index(
        "ix_audit_log_staged",
        "audit_log",
        ["timestamp"],
        postgresql_where=unstaged,
        sqlite_where=unstaged,
    )

    op.create_index(
        "ix_workflow_jobs_status_created", "workflow_jobs", ["status", "created_at"]
    )
    op.create_index(
        "ix_workflow_jobs_record_created", "workflow_jobs", ["record_id", "created_at"]
    )
    op.create_index("ix_workflow_jobs_created", "workflow_jobs", ["created_at"])
    op.create_index(
        "ix_workflow_jobs_workflow_status",
        "workflow_jobs",
        ["workflow_name", "status"],
    )
    op.create_index(
        "ix_step_executions_plugin_status", "step_executions", ["plugin", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_step_executions_plugin_status", table_name="step_executions")
    op.drop_index("ix_workflow_jobs_workflow_status", table_name="workflow_jobs")
    op.drop_index("ix_workflow_jobs_created", table_name="workflow_jobs")
    op.drop_index("ix_workflow_jobs_record_created", table_name="workflow_jobs")
    op.drop_index("ix_workflow_jobs_status_created", table_name="workflow_jobs")
    op.drop_index("ix_audit_log_staged", table_name="audit_log")
    op.drop_index("ix_audit_log_timestamp", table_name="audit_log")
    op.drop_index("ix_audit_log_commit", table_name="audit_log")
    op.drop_index("ix_audit_log_entity", table_name="audit_log")
    op.drop_index("ix_records_live_schema_created", table_name="records")
    op.drop_index("ix_records_live_dataset_created", table_name="records")
    op.drop_index("ix_records_parent", table_name="records")
    op.drop_table("job_affected_schemas")
    op.drop_table("file_references")
    op.drop_table("stored_objects")
