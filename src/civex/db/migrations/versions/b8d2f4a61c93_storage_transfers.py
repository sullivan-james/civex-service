"""storage_transfers: the durable record of moving files between volumes

A transfer can take hours and be paused, interrupted or resumed, so what it was
asked to do, how far it got and what it couldn't move is kept here, not in the
memory of the thread doing the work.

Revision ID: b8d2f4a61c93
Revises: e7b3c1a9d4f2
Create Date: 2026-10-03 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import civex.db.models

revision: str = "b8d2f4a61c93"
down_revision: Union[str, None] = "e7b3c1a9d4f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = civex.db.models._JSON
_TZ = civex.db.models._UTCDateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "storage_transfers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("spec", _JSON, nullable=False),
        sa.Column("plan", _JSON, nullable=True),
        sa.Column("progress", _JSON, nullable=False),
        sa.Column("failures", _JSON, nullable=False),
        sa.Column("failures_total", sa.Integer(), nullable=False),
        sa.Column("pause_reason", sa.Text(), nullable=True),
        sa.Column("auto_resume", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("control", sa.String(length=10), nullable=True),
        sa.Column("frozen", _JSON, nullable=False),
        sa.Column("created_at", _TZ, nullable=False),
        sa.Column("started_at", _TZ, nullable=True),
        sa.Column("finished_at", _TZ, nullable=True),
        sa.Column("updated_at", _TZ, nullable=False),
    )
    op.create_index("ix_storage_transfers_created", "storage_transfers", ["created_at"])
    op.create_index("ix_storage_transfers_status", "storage_transfers", ["status"])


def downgrade() -> None:
    op.drop_index("ix_storage_transfers_status", table_name="storage_transfers")
    op.drop_index("ix_storage_transfers_created", table_name="storage_transfers")
    op.drop_table("storage_transfers")
