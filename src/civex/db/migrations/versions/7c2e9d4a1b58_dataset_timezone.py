"""dataset timezone

Adds a nullable IANA timezone to datasets: the zone datetime values in that
collection are read (when they carry no UTC offset) and shown in.

Nullable with no backfill on purpose: NULL means "unset", which is exactly
how every existing dataset already behaves -- offset-less input read as UTC,
viewers seeing their own zone. Stored datetimes are UTC instants and are not
touched.

Revision ID: 7c2e9d4a1b58
Revises: e5b81c3d7a04
Create Date: 2026-09-30 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "7c2e9d4a1b58"
down_revision: Union[str, None] = "e5b81c3d7a04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("datasets", schema=None) as batch_op:
        batch_op.add_column(sa.Column("timezone", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("datasets", schema=None) as batch_op:
        batch_op.drop_column("timezone")
