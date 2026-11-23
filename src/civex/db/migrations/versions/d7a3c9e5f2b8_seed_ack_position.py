"""seed_acks.head_seq and an index on audit_log.hlc

Each acknowledged change of a first upload is kept with the authority's
position when it answered, so an authority found behind it (restored from a
backup) is known to have lost them. `max(audit_log.hlc)` is read whenever a
change is stamped; without an index each read scans the whole log (on a
partitioned `audit_log` PostgreSQL creates it on every partition).

A separate revision because databases already stamped at b8d4f1a7c3e6 exist.

Revision ID: d7a3c9e5f2b8
Revises: b8d4f1a7c3e6
Create Date: 2026-11-23 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d7a3c9e5f2b8"
down_revision: Union[str, None] = "b8d4f1a7c3e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("seed_acks")}
    if "head_seq" not in columns:
        with op.batch_alter_table("seed_acks") as batch:
            batch.add_column(
                sa.Column("head_seq", sa.Integer(), nullable=False, server_default="0")
            )
    indexes = {i["name"] for i in inspector.get_indexes("audit_log")}
    if "ix_audit_log_hlc" not in indexes:
        op.create_index("ix_audit_log_hlc", "audit_log", ["hlc"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_hlc", table_name="audit_log")
    with op.batch_alter_table("seed_acks") as batch:
        batch.drop_column("head_seq")
