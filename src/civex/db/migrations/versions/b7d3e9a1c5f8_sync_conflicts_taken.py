"""sync_conflicts: when a refused thing was taken after all, and an index on the thing

Revision ID: b7d3e9a1c5f8
Revises: e8c1b4d7a925
Create Date: 2026-11-24 18:00:00.000000

`taken_at` marks a refusal of a create whose thing the authority later took
(filling it sent the thing again), kept apart from how a person settled the
refusal. Filling the authority looks conflicts up by thing a page at a time:
the index makes that a lookup instead of a scan of every conflict.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7d3e9a1c5f8"
down_revision: Union[str, None] = "e8c1b4d7a925"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("sync_conflicts")}
    if "taken_at" not in columns:
        with op.batch_alter_table("sync_conflicts") as batch:
            batch.add_column(
                sa.Column("taken_at", sa.DateTime(timezone=True), nullable=True)
            )
    indexes = {i["name"] for i in inspector.get_indexes("sync_conflicts")}
    if "ix_sync_conflicts_entity" not in indexes:
        op.create_index("ix_sync_conflicts_entity", "sync_conflicts", ["entity_id"])


def downgrade() -> None:
    op.drop_index("ix_sync_conflicts_entity", table_name="sync_conflicts")
    with op.batch_alter_table("sync_conflicts") as batch:
        batch.drop_column("taken_at")
