"""sync: a device may ask to join, for a person to approve

`sync_login_requests`: a device without an invite asks to join and shows a
short code; a person approves it on the authority, which admits the device as
an invite would. Alongside invites, which stay.

Revision ID: c1e8f4a2b7d3
Revises: b9d4e7f2a1c6
Create Date: 2026-10-12 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import civex.db.models

revision: str = "c1e8f4a2b7d3"
down_revision: Union[str, None] = "b9d4e7f2a1c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sync_login_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_code", sa.String(16), nullable=False),
        sa.Column("device_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("device_id", sa.String(36), nullable=False),
        sa.Column("public_key", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=True),
        sa.Column("created_at", civex.db.models._UTCDateTime(), nullable=False),
        sa.Column("expires_at", civex.db.models._UTCDateTime(), nullable=False),
        sa.Column("approved_at", civex.db.models._UTCDateTime(), nullable=True),
        sa.Column("denied_at", civex.db.models._UTCDateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("sync_login_requests")
