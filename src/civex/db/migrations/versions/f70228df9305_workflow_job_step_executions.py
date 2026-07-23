"""workflow job step executions

Adds workflow_jobs.step_executions: a list of per-step execution records
(step id, plugin, status, resolved inputs, outputs, duration, error), in
execution order (CIVEX-117). `executor.run()` already knew all of this in
memory; only the flat `log` stdout/logging blob was persisted before. `log`
is left alone -- this is additive, not a replacement of it.

Revision ID: f70228df9305
Revises: d89dffcd2e46
Create Date: 2026-07-23 22:46:39.502956
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f70228df9305"
down_revision: Union[str, None] = "d89dffcd2e46"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors models._JSON — JSONB on PostgreSQL, plain JSON elsewhere.
_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("workflow_jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("step_executions", _JSON, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workflow_jobs", schema=None) as batch_op:
        batch_op.drop_column("step_executions")
