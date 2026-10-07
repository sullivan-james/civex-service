"""sync: devices join by invite and sign in with a key

A device used to be allowed by a token it sent with every request. It is now
invited (`sync_invites`: one use, an expiry, only the code's hash kept), joins
with a public key whose private half never leaves it (`sync_devices.public_key`),
and signs in for a short-lived session. The authority has a key of its own
(`sync_meta.authority_key`) that signs its answers.

Devices allowed by a token can't sign in any more, so `sync_devices` is made
anew; sync had not been released, so only trial copies had any. A device's name
is unique among the devices not revoked, so a revoked one's name can be reused.

Revision ID: a8c4e2f6b1d9
Revises: c3f7a9e1d5b8
Create Date: 2026-10-07 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import civex.db.models

revision: str = "a8c4e2f6b1d9"
down_revision: Union[str, None] = "c3f7a9e1d5b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LIVE = sa.text("revoked_at IS NULL")


def _devices() -> None:
    op.create_table(
        "sync_devices",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("device_id", sa.String(36), nullable=False),
        sa.Column("public_key", sa.String(64), nullable=False),
        sa.Column("created_at", civex.db.models._UTCDateTime(), nullable=False),
        sa.Column("last_seen_at", civex.db.models._UTCDateTime(), nullable=True),
        sa.Column("revoked_at", civex.db.models._UTCDateTime(), nullable=True),
    )
    for name, columns in (
        ("ux_sync_devices_name_live", ["name"]),
        ("ux_sync_devices_device_live", ["device_id"]),
    ):
        op.create_index(
            name,
            "sync_devices",
            columns,
            unique=True,
            postgresql_where=_LIVE,
            sqlite_where=_LIVE,
        )


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "sync_devices" in tables:
        op.drop_table("sync_devices")
    _devices()
    if "sync_invites" not in tables:
        op.create_table(
            "sync_invites",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("created_at", civex.db.models._UTCDateTime(), nullable=False),
            sa.Column("expires_at", civex.db.models._UTCDateTime(), nullable=False),
            sa.Column("used_at", civex.db.models._UTCDateTime(), nullable=True),
            sa.Column("revoked_at", civex.db.models._UTCDateTime(), nullable=True),
        )
    if "authority_key" not in {c["name"] for c in inspector.get_columns("sync_meta")}:
        with op.batch_alter_table("sync_meta") as batch:
            batch.add_column(sa.Column("authority_key", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sync_meta") as batch:
        batch.drop_column("authority_key")
    op.drop_table("sync_invites")
    op.drop_table("sync_devices")
    op.create_table(
        "sync_devices",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("device_id", sa.String(36), nullable=True),
        sa.Column("created_at", civex.db.models._UTCDateTime(), nullable=False),
        sa.Column("last_seen_at", civex.db.models._UTCDateTime(), nullable=True),
        sa.Column("revoked_at", civex.db.models._UTCDateTime(), nullable=True),
    )
