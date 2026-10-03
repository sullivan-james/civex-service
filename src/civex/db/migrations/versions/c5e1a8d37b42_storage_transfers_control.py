"""storage_transfers.control: a pause or cancel asked for, saved on the row

The column was first added by editing the migration that created the table, so
a database that had already run it lacks the column. Add it where it is missing
(a database created since has it already).

Revision ID: c5e1a8d37b42
Revises: b8d2f4a61c93
Create Date: 2026-10-03 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c5e1a8d37b42"
down_revision: Union[str, None] = "b8d2f4a61c93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {
        c["name"] for c in sa.inspect(op.get_bind()).get_columns("storage_transfers")
    }
    if "control" not in columns:
        with op.batch_alter_table("storage_transfers") as batch:
            batch.add_column(sa.Column("control", sa.String(length=10), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("storage_transfers") as batch:
        batch.drop_column("control")
