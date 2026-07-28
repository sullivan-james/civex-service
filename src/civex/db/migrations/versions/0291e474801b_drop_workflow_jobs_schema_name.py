"""drop workflow_jobs schema_name

Drops workflow_jobs.schema_name (CIVEX-171): a copy of
records.schema_id -> schemas.name taken at enqueue time, so renaming a
schema silently made every historical job row wrong -- a textbook
transitive-dependency violation, not an intentional snapshot. record_id is a
hard FK with no cascade, so a job's record can never be deleted out from
under it; the join is always available, so there's nothing worth
snapshotting. Readers now resolve it via record_id -> records.schema_id ->
schemas.name (see job_repo._to_dto).

Revision ID: 0291e474801b
Revises: 23bbe21d0f1e
Create Date: 2026-07-28 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0291e474801b"
down_revision: Union[str, None] = "23bbe21d0f1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_jobs", schema=None) as batch_op:
        batch_op.drop_column("schema_name")


def downgrade() -> None:
    with op.batch_alter_table("workflow_jobs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("schema_name", sa.String(length=255), nullable=True)
        )

    op.execute(
        """
        UPDATE workflow_jobs
        SET schema_name = (
            SELECT schemas.name
            FROM records
            JOIN schemas ON schemas.id = records.schema_id
            WHERE records.id = workflow_jobs.record_id
        )
        """
    )

    with op.batch_alter_table("workflow_jobs", schema=None) as batch_op:
        batch_op.alter_column(
            "schema_name", existing_type=sa.String(length=255), nullable=False
        )
