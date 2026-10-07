"""history: which device a synced change came through

A change a device sends is recorded with two facts: who made it (`actor`, the
name the person chose, as they gave it) and the device whose token sent it
(`device`, stamped by the authority, which it can vouch for). Until now the
authority overwrote `actor` with the device's name, so a change made by "l2"
on a device called "backup" read "backup" everywhere.

A conflict's "who wrote the value that stayed" gets the same second part
(`sync_conflicts.theirs_device`).

Structure only: nullable columns. Older entries keep the device's name as
their author and have no device.

Revision ID: b5e1d8f2a647
Revises: a4d9e2c7f310
Create Date: 2026-10-07 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b5e1d8f2a647"
down_revision: Union[str, None] = "a4d9e2c7f310"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    have = {c["name"] for c in inspector.get_columns("audit_log")}
    if "device" not in have:
        op.add_column("audit_log", sa.Column("device", sa.String(100), nullable=True))
    have = {c["name"] for c in inspector.get_columns("sync_conflicts")}
    if "theirs_device" not in have:
        op.add_column(
            "sync_conflicts", sa.Column("theirs_device", sa.String(100), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("sync_conflicts") as batch:
        batch.drop_column("theirs_device")
    with op.batch_alter_table("audit_log") as batch:
        batch.drop_column("device")
