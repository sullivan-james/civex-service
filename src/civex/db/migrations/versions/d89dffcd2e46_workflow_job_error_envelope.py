"""workflow job error envelope

Adds workflow_jobs.error_details: the structured {kind, message, retryable,
step} form of a failed job's error (CIVEX-143). `error` is left alone and
keeps holding the human-readable message, so nothing reading it today has to
change; error_details is what anything wanting to *branch* on a failure
reads.

JSON rather than three typed columns so the per-step execution records in
CIVEX-105/117 can extend the shape without another migration.

Revision ID: d89dffcd2e46
Revises: ac425ae391c7
Create Date: 2026-07-22 22:57:51.355821
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d89dffcd2e46"
down_revision: Union[str, None] = "ac425ae391c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors models._JSON — JSONB on PostgreSQL, plain JSON elsewhere.
_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("workflow_jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("error_details", _JSON, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workflow_jobs", schema=None) as batch_op:
        batch_op.drop_column("error_details")
