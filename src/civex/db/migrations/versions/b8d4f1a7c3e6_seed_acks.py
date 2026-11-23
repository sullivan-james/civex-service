"""seed_acks: what the authority has acknowledged of a first upload

A first upload (seed) that is interrupted resumes where it stopped: each
change it sent that the authority answered is remembered here, and the resumed
upload leaves those out instead of sending the whole project again.

Revision ID: b8d4f1a7c3e6
Revises: f3b8d6a2c9e1
Create Date: 2026-11-23 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8d4f1a7c3e6"
down_revision: Union[str, None] = "f3b8d6a2c9e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "seed_acks",
        sa.Column("entry_id", sa.String(length=36), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("seed_acks")
