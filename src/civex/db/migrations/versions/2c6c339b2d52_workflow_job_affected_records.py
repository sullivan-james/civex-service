"""workflow job affected records

Adds workflow_jobs.affected_records: the list of records a run created or
updated, in touch order -- [{record_id, schema_name, natural_name, action}].
WorkflowContext builds it live as steps call create_record()/update_record()
and it's persisted alongside step_executions when the job finishes (or
fails partway through), giving the run a forward link to the data it
actually touched.

Revision ID: 2c6c339b2d52
Revises: b3d71a04f6c2
Create Date: 2026-08-09 22:54:23.313342
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "2c6c339b2d52"
down_revision: Union[str, None] = "b3d71a04f6c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors models._JSON — JSONB on PostgreSQL, plain JSON elsewhere.
_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("workflow_jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("affected_records", _JSON, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workflow_jobs", schema=None) as batch_op:
        batch_op.drop_column("affected_records")
