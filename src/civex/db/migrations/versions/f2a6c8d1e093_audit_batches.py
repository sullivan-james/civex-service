"""audit_batches, audit_log.batch_id: a bulk operation as one event

An import, a delete that takes a whole tree, a workflow run: each wrote one
audit row per record, so history was thousands of lines. A batch ties those
rows together so they can be shown, filtered and undone as one.

Revision ID: f2a6c8d1e093
Revises: e1d5a39c7b84
Create Date: 2026-10-04 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import civex.db.models

revision: str = "f2a6c8d1e093"
down_revision: Union[str, None] = "e1d5a39c7b84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "audit_batches" not in inspector.get_table_names():
        op.create_table(
            "audit_batches",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("kind", sa.String(30), nullable=False),
            sa.Column("label", sa.String(500), nullable=True),
            sa.Column("ref", sa.String(100), nullable=True),
            sa.Column("created_at", civex.db.models._UTCDateTime(), nullable=False),
        )
    columns = {c["name"] for c in inspector.get_columns("audit_log")}
    if "batch_id" not in columns:
        with op.batch_alter_table("audit_log") as batch:
            batch.add_column(sa.Column("batch_id", sa.Uuid(), nullable=True))
            batch.create_foreign_key(
                "fk_audit_log_batch", "audit_batches", ["batch_id"], ["id"]
            )
            batch.create_index("ix_audit_log_batch", ["batch_id"])


def downgrade() -> None:
    with op.batch_alter_table("audit_log") as batch:
        batch.drop_index("ix_audit_log_batch")
        batch.drop_constraint("fk_audit_log_batch", type_="foreignkey")
        batch.drop_column("batch_id")
    op.drop_table("audit_batches")
