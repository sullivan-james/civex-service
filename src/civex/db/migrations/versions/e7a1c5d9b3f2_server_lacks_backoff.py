"""server_lacks: how often the server said so, and when to ask again

Revision ID: e7a1c5d9b3f2
Revises: c8d2f4a6b1e7
Create Date: 2026-11-22 18:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7a1c5d9b3f2"
down_revision: Union[str, None] = "c8d2f4a6b1e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("server_lacks") as batch:
        batch.add_column(
            sa.Column("misses", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(
            sa.Column(
                "retry_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            )
        )
    # Asked again at the next pass, as before.
    op.execute("UPDATE server_lacks SET retry_at = asked_at")


def downgrade() -> None:
    with op.batch_alter_table("server_lacks") as batch:
        batch.drop_column("retry_at")
        batch.drop_column("misses")
