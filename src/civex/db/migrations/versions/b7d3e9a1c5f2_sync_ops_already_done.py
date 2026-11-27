"""sync ops and audit log: whether a delete found the record already deleted

Revision ID: b7d3e9a1c5f2
Revises: a4e9c2b7d6f1
Create Date: 2026-11-26 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7d3e9a1c5f2"
down_revision: Union[str, None] = "a4e9c2b7d6f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLES = ("sync_ops", "audit_log")


def upgrade() -> None:
    for table in _TABLES:
        have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}
        if "already_done" not in have:
            # (not a batch alter: on SQLite that rebuilds the table and drops
            # audit_log's numbering trigger)
            op.add_column(
                table,
                sa.Column(
                    "already_done",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
            )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "already_done")
