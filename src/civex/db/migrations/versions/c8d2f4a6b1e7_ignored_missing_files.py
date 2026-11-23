"""ignored_missing_files: files a person chose to stop being told are missing

Revision ID: c8d2f4a6b1e7
Revises: a3c7e1d9f5b4
Create Date: 2026-11-22 16:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8d2f4a6b1e7"
down_revision: Union[str, None] = "a3c7e1d9f5b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ignored_missing_files",
        sa.Column("sha256", sa.String(length=64), primary_key=True),
        sa.Column("ignored_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ignored_missing_files")
