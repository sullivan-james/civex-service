"""sync_ops: an index on the thing a change was to

Revision ID: a4e9c2b7d6f1
Revises: b7d3e9a1c5f8
Create Date: 2026-11-25 12:00:00.000000

The authority says a file cited by a record that arrived lately is `arriving`
(its device is still uploading it), which needs the latest time a change to
each of a page of records was received: the index makes that a lookup, not a
scan of every change ever received.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "a4e9c2b7d6f1"
down_revision: Union[str, None] = "b7d3e9a1c5f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # Built without blocking writes (a big authority keeps taking pushes):
        # CONCURRENTLY cannot run inside a transaction.
        with op.get_context().autocommit_block():
            op.create_index(
                "ix_sync_ops_entity",
                "sync_ops",
                ["entity_id", "received_at"],
                postgresql_concurrently=True,
                if_not_exists=True,
            )
    else:
        op.create_index(
            "ix_sync_ops_entity",
            "sync_ops",
            ["entity_id", "received_at"],
            if_not_exists=True,
        )


def downgrade() -> None:
    op.drop_index("ix_sync_ops_entity", table_name="sync_ops", if_exists=True)
