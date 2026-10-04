"""workflow_jobs.trigger_detail: what caused a run

A run said only "record_updated". This keeps which fields changed (with a short
before and after, and which of them the workflow was watching) and, when the
run was started by another run's own save, which run and workflow that was, so
a chain of workflows triggering each other can be followed.

Revision ID: e1d5a39c7b84
Revises: c4a9e17d5b20
Create Date: 2026-10-04 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import civex.db.models

revision: str = "e1d5a39c7b84"
down_revision: Union[str, None] = "c4a9e17d5b20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {
        c["name"] for c in sa.inspect(op.get_bind()).get_columns("workflow_jobs")
    }
    if "trigger_detail" not in columns:
        with op.batch_alter_table("workflow_jobs") as batch:
            batch.add_column(
                sa.Column("trigger_detail", civex.db.models._JSON, nullable=True)
            )


def downgrade() -> None:
    with op.batch_alter_table("workflow_jobs") as batch:
        batch.drop_column("trigger_detail")
