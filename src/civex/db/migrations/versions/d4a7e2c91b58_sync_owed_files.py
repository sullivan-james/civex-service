"""sync: remember files a device still owes its authority

A change can cite a file this computer cannot read right now (a drive that is
unplugged, or bytes that are still to be recovered). The change is sent anyway;
the file's hash is kept here and uploaded as soon as it can be read.

Revision ID: d4a7e2c91b58
Revises: c9e1f4a7b3d2
Create Date: 2026-10-05 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d4a7e2c91b58"
down_revision: Union[str, None] = "c9e1f4a7b3d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "owed_files" not in {c["name"] for c in inspector.get_columns("sync_meta")}:
        with op.batch_alter_table("sync_meta") as batch:
            batch.add_column(sa.Column("owed_files", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sync_meta") as batch:
        batch.drop_column("owed_files")
