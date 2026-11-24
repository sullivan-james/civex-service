"""sync_meta.seed_open: a first upload was begun and has not finished

A first upload (seed) is resumed by the next sync only if something says it
did not finish. The changes it sets aside said so, but a project whose history
was all settled with another authority sets none aside, so an interrupted seed
left nothing behind and its records never went. The flag is kept in the
project's sync state instead.

Revision ID: c5e2a8d7f1b9
Revises: d7a3c9e5f2b8
Create Date: 2026-11-23 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5e2a8d7f1b9"
down_revision: Union[str, None] = "d7a3c9e5f2b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("sync_meta")}
    if "seed_open" not in columns:
        op.add_column(
            "sync_meta",
            sa.Column(
                "seed_open",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    with op.batch_alter_table("sync_meta") as batch:
        batch.drop_column("seed_open")
