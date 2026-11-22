"""sync_conflicts: why a refusal was made, and how often it was sent again

A refusal the authority made for permission is sent again by the device by
itself, with a growing pause, since it can go through once the device may do
it. `code` is the authority's reason; `retries` and `retried_at` drive the
pause.

Revision ID: a3c7e1d9f5b4
Revises: b5d8f1a3c6e2
Create Date: 2026-11-22 15:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import civex.db.models

revision: str = "a3c7e1d9f5b4"
down_revision: Union[str, None] = "b5d8f1a3c6e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("sync_conflicts") as batch:
        batch.add_column(sa.Column("code", sa.String(length=16), nullable=True))
        batch.add_column(
            sa.Column("retries", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("retried_at", civex.db.models._UTCDateTime(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("sync_conflicts") as batch:
        batch.drop_column("retried_at")
        batch.drop_column("retries")
        batch.drop_column("code")
