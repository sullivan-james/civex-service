"""soft delete deleted_at columns

Adds a nullable deleted_at timestamp to schemas, datasets and records so
deletes become reversible (see docs/guide/soft-delete.md): a delete sets
deleted_at instead of removing the row, normal queries filter it out, and a
"Recently deleted" view lists rows where it's set until they're restored or
purged past the retention window.

Revision ID: 6f1a2e9c4d17
Revises: 2c6c339b2d52
Create Date: 2026-08-10 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import civex.db.models

revision: str = "6f1a2e9c4d17"
down_revision: Union[str, None] = "2c6c339b2d52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("schemas", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "deleted_at",
                civex.db.models._UTCDateTime(timezone=True),
                nullable=True,
            )
        )
    with op.batch_alter_table("datasets", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "deleted_at",
                civex.db.models._UTCDateTime(timezone=True),
                nullable=True,
            )
        )
    with op.batch_alter_table("records", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "deleted_at",
                civex.db.models._UTCDateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.create_index("ix_records_deleted_at", ["deleted_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("records", schema=None) as batch_op:
        batch_op.drop_index("ix_records_deleted_at")
        batch_op.drop_column("deleted_at")
    with op.batch_alter_table("datasets", schema=None) as batch_op:
        batch_op.drop_column("deleted_at")
    with op.batch_alter_table("schemas", schema=None) as batch_op:
        batch_op.drop_column("deleted_at")
