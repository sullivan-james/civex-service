"""server_lacks: files the authority said it hasn't got

A device remembers which files the authority answered it lacks, so a file that
is on no drive here either can be told apart as missing (nothing can send it)
from one that simply hasn't been asked about yet. Starts empty: the next pass
of sending files asks and fills it.

Revision ID: d2f6a9c4e8b1
Revises: c1e8f4a2b7d3
Create Date: 2026-10-14 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d2f6a9c4e8b1"
down_revision: Union[str, None] = "c1e8f4a2b7d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "server_lacks",
        sa.Column("sha256", sa.String(length=64), primary_key=True),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("server_lacks")
