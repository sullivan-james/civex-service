"""sync: the tables a project needs to be kept in step with another copy

`sync_meta` (one row: the project's id, the authority's counter, a device's
cursor), `sync_ops` (an authority's record of changes it was sent, so a repeat
is answered, not redone), `sync_devices` (who may sync, by hashed token) and
`sync_conflicts` (changes that did not go in as made). `audit_log` also gets the
two indexes the sync queries use.

Every existing project gets a `project_id` of its own: until it syncs, it is
nobody else's copy.

Revision ID: c9e1f4a7b3d2
Revises: a3d8f0b6c125
Create Date: 2026-10-05 00:00:00.000000
"""

from __future__ import annotations

import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import civex.db.models

revision: str = "c9e1f4a7b3d2"
down_revision: Union[str, None] = "a3d8f0b6c125"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(
    sa.dialects.postgresql.JSONB(astext_type=sa.Text()), "postgresql"
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "sync_meta" not in tables:
        op.create_table(
            "sync_meta",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Uuid(), nullable=False),
            sa.Column("head_seq", sa.BigInteger(), nullable=False),
            sa.Column("cursor", sa.BigInteger(), nullable=False),
            sa.Column("seeded_by", sa.String(36), nullable=True),
            sa.Column("last_synced_at", civex.db.models._UTCDateTime(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("last_error_at", civex.db.models._UTCDateTime(), nullable=True),
            sa.CheckConstraint("id = 1", name="ck_sync_meta_single_row"),
        )
        op.execute(
            sa.text(
                "INSERT INTO sync_meta (id, project_id, head_seq, cursor) "
                "VALUES (1, :pid, 0, 0)"
            ).bindparams(sa.bindparam("pid", uuid.uuid4(), type_=sa.Uuid()))
        )

    if "sync_ops" not in tables:
        op.create_table(
            "sync_ops",
            sa.Column("op_id", sa.Uuid(), primary_key=True),
            sa.Column("device_id", sa.String(36), nullable=True),
            sa.Column("device_name", sa.String(100), nullable=True),
            sa.Column("entity_type", sa.String(50), nullable=False),
            sa.Column("entity_id", sa.Uuid(), nullable=False),
            sa.Column("status", sa.String(12), nullable=False),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("conflicts", _JSON, nullable=False),
            sa.Column("hub_seq", sa.BigInteger(), nullable=True),
            sa.Column("received_at", civex.db.models._UTCDateTime(), nullable=False),
        )

    if "sync_devices" not in tables:
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

    if "sync_conflicts" not in tables:
        op.create_table(
            "sync_conflicts",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("entity_type", sa.String(50), nullable=False),
            sa.Column("entity_id", sa.Uuid(), nullable=False),
            sa.Column("field", sa.String(200), nullable=True),
            sa.Column("yours", _JSON, nullable=True),
            sa.Column("theirs", _JSON, nullable=True),
            sa.Column("op_id", sa.Uuid(), nullable=True),
            sa.Column("device_name", sa.String(100), nullable=True),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("status", sa.String(10), nullable=False, server_default="open"),
            sa.Column("created_at", civex.db.models._UTCDateTime(), nullable=False),
            sa.Column("resolved_at", civex.db.models._UTCDateTime(), nullable=True),
            sa.Column("resolution", sa.String(10), nullable=True),
        )
        op.create_index(
            "ix_sync_conflicts_status", "sync_conflicts", ["status", "created_at"]
        )

    indexes = {i["name"] for i in inspector.get_indexes("audit_log")}
    if "ix_audit_log_hub_seq" not in indexes:
        op.create_index("ix_audit_log_hub_seq", "audit_log", ["hub_seq"])
    if "ix_audit_log_unsynced" not in indexes:
        op.create_index(
            "ix_audit_log_unsynced",
            "audit_log",
            ["timestamp"],
            postgresql_where=sa.text("sync_state = 'pending'"),
            sqlite_where=sa.text("sync_state = 'pending'"),
        )


def downgrade() -> None:
    op.drop_index("ix_audit_log_unsynced", table_name="audit_log")
    op.drop_index("ix_audit_log_hub_seq", table_name="audit_log")
    op.drop_index("ix_sync_conflicts_status", table_name="sync_conflicts")
    op.drop_table("sync_conflicts")
    op.drop_table("sync_devices")
    op.drop_table("sync_ops")
    op.drop_table("sync_meta")
