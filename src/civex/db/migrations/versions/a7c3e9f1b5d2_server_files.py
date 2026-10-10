"""server_files: files the authority has said it holds

A device remembers which of its files the authority confirmed (it answered
that it has them, took an upload, or the device downloaded them from it), so it
can say which files are not on the server yet and only ask about those.
Starts empty: the next sync asks about every file once and fills it.

Revision ID: a7c3e9f1b5d2
Revises: f7b3d9e2a6c4
Create Date: 2026-10-09 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c3e9f1b5d2"
down_revision: Union[str, None] = "f7b3d9e2a6c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "server_files",
        sa.Column("sha256", sa.String(length=64), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("server_files")
