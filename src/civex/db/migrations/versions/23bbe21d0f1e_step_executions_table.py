"""step executions table

Normalizes workflow_jobs.step_executions -- a JSON list of per-step
execution records -- into a child `step_executions` table (CIVEX-170).

Analytical questions the JSON blob made expensive (which plugin fails most
often, p95 duration by step, which steps get retried) all required a JSON
scan; the envelope fields that get queried/aggregated (step, plugin, status,
timing) become real columns. `inputs`/`outputs`/`error_details` stay JSON --
arbitrary plugin payloads with no fixed shape, not worth normalizing.
`depends_on` isn't in CIVEX-170's proposed schema but is kept (also as JSON)
since JobStepsDiagram's DAG view depends on it.

Backfills from the existing JSON rows, then drops the column -- nothing
outside this same change reads it directly (frontend + API both moved to
the new table in the same PR), so there's no reason to keep it around for a
release the way the ticket allows.

Revision ID: 23bbe21d0f1e
Revises: 336bf9b1d235
Create Date: 2026-07-28 00:00:00.000000
"""

from __future__ import annotations

import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "23bbe21d0f1e"
down_revision: Union[str, None] = "336bf9b1d235"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors models._JSON — JSONB on PostgreSQL, plain JSON elsewhere.
_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "step_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("step_id", sa.String(length=255), nullable=False),
        sa.Column("plugin", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("error_details", _JSON, nullable=True),
        sa.Column("inputs", _JSON, nullable=True),
        sa.Column("outputs", _JSON, nullable=True),
        sa.Column("depends_on", _JSON, nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["workflow_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "position"),
    )

    connection = op.get_bind()
    workflow_jobs = sa.table(
        "workflow_jobs",
        sa.column("id", sa.Uuid()),
        sa.column("step_executions", _JSON),
    )
    step_executions_table = sa.table(
        "step_executions",
        sa.column("id", sa.Uuid()),
        sa.column("job_id", sa.Uuid()),
        sa.column("position", sa.Integer()),
        sa.column("step_id", sa.String()),
        sa.column("plugin", sa.String()),
        sa.column("status", sa.String()),
        sa.column("duration_seconds", sa.Float()),
        sa.column("error", sa.Text()),
        sa.column("error_details", _JSON),
        sa.column("inputs", _JSON),
        sa.column("outputs", _JSON),
        sa.column("depends_on", _JSON),
    )

    rows = connection.execute(
        sa.select(workflow_jobs.c.id, workflow_jobs.c.step_executions).where(
            workflow_jobs.c.step_executions.is_not(None)
        )
    ).fetchall()

    to_insert = []
    for job_id, executions in rows:
        for position, step in enumerate(executions or []):
            to_insert.append(
                {
                    "id": uuid.uuid4(),
                    "job_id": job_id,
                    "position": position,
                    "step_id": step["step_id"],
                    "plugin": step["plugin"],
                    "status": step["status"],
                    "duration_seconds": step.get("duration_seconds"),
                    "error": step.get("error"),
                    "error_details": step.get("error_details"),
                    "inputs": step.get("inputs"),
                    "outputs": step.get("outputs"),
                    "depends_on": step.get("depends_on"),
                }
            )
    if to_insert:
        op.bulk_insert(step_executions_table, to_insert)

    with op.batch_alter_table("workflow_jobs", schema=None) as batch_op:
        batch_op.drop_column("step_executions")


def downgrade() -> None:
    # Mirrors models._JSON — JSONB on PostgreSQL, plain JSON elsewhere.
    with op.batch_alter_table("workflow_jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("step_executions", _JSON, nullable=True))

    connection = op.get_bind()
    workflow_jobs = sa.table(
        "workflow_jobs",
        sa.column("id", sa.Uuid()),
        sa.column("step_executions", _JSON),
    )
    step_executions_table = sa.table(
        "step_executions",
        sa.column("id", sa.Uuid()),
        sa.column("job_id", sa.Uuid()),
        sa.column("position", sa.Integer()),
        sa.column("step_id", sa.String()),
        sa.column("plugin", sa.String()),
        sa.column("status", sa.String()),
        sa.column("duration_seconds", sa.Float()),
        sa.column("error", sa.Text()),
        sa.column("error_details", _JSON),
        sa.column("inputs", _JSON),
        sa.column("outputs", _JSON),
        sa.column("depends_on", _JSON),
    )

    rows = connection.execute(
        sa.select(step_executions_table).order_by(
            step_executions_table.c.job_id, step_executions_table.c.position
        )
    ).fetchall()

    by_job: dict[uuid.UUID, list[dict]] = {}
    for row in rows:
        by_job.setdefault(row.job_id, []).append(
            {
                "step_id": row.step_id,
                "plugin": row.plugin,
                "status": row.status,
                "inputs": row.inputs,
                "outputs": row.outputs,
                "duration_seconds": row.duration_seconds,
                "error": row.error,
                "depends_on": row.depends_on,
            }
        )

    for job_id, executions in by_job.items():
        connection.execute(
            workflow_jobs.update()
            .where(workflow_jobs.c.id == job_id)
            .values(step_executions=executions)
        )

    op.drop_table("step_executions")
